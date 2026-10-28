import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Chip, actorLabel, fmtTime, ROLE_LABEL } from './common.jsx'
import { RawLink } from './Raw.jsx'

export function evidenceCell(s) {
  const fs = s.findings.filter(f => f.cls !== 'other')
  if (s.profiling !== 'Done') return <span className="muted">—</span>
  if (!fs.length) return <Chip label="No resistance variants" kind="none" />
  return <span className="row" style={{ gap: 4 }}>{fs.map(f => <span key={f.fid} className={'chip ' + (f.review === 'Reviewed' ? 'c-Reviewed' : f.cls === 'uncertain' ? 'c-uncertain' : 'c-tech')}>{f.drug}</span>)}</span>
}
export function reviewCell(s) {
  const fs = s.findings.filter(f => f.review !== 'Not required')
  if (s.profiling !== 'Done') return <span className="muted">—</span>
  if (!fs.length) return <Chip label="Not required" kind="none" />
  if (fs.some(f => f.review === 'Pending')) return <Chip label="Pending" />
  return <Chip label={fs.some(f => f.review === 'Needs more data') ? 'Needs more data' : 'Reviewed'} kind={fs.some(f => f.review === 'Needs more data') ? 'Hold' : 'Reviewed'} />
}

export default function Samples({ st, openSample }) {
  return (
    <>
      <p className="muted">Four statuses stay separate for every run: eligibility, quality control, resistance evidence and scientific review. Click a row for its decision history, the Evidence Analyst's notes and overrides.</p>
      <div className="tw"><table><thead><tr><th>Run</th><th>Study</th><th>Location</th><th>Eligibility</th><th>Quality Control</th><th>Profiling</th><th>Resistance evidence</th><th>Review</th></tr></thead><tbody>
        {st.samples.map(s => <tr key={s.run} className="click" onClick={() => openSample(s.run)}>
          <td className="mono">{s.run}</td><td className="mono">{s.study}</td><td>{s.location}</td><td><Chip label={s.eligibility || 'Not assessed'} kind={s.eligibility || 'none'} /></td>
          <td><Chip label={s.qc || '—'} kind={s.qc || 'none'} /></td><td><Chip label={s.profiling || '—'} kind={s.profiling ? s.profiling.split(' ')[0] : 'none'} /></td><td>{evidenceCell(s)}</td><td>{reviewCell(s)}</td></tr>)}
        {!st.samples.length && <tr><td colSpan={8} className="muted">No runs yet — run Stage 2.</td></tr>}
      </tbody></table></div>
    </>
  )
}

export function Drawer({ run, st, pending, act, who, close, version }) {
  const s = st.samples.find(x => x.run === run)
  const [hist, setHist] = useState([])
  const [field, setField] = useState('eligibility')
  const [to, setTo] = useState('Hold')
  const [why, setWhy] = useState('')
  useEffect(() => { api.decisions(run).then(setHist).catch(() => setHist([])) }, [run, version])
  if (!s) return null
  const mine = pending.filter(p => p.run === run)
  return (
    <>
      <div className="scrim" onClick={close} />
      <aside className="drawer" aria-label={`Run ${run}`}>
        <div className="row between"><div><span className="eyebrow">Run</span><h2 className="mono" style={{ fontSize: '1.1rem' }}>{s.run}</h2></div><button className="btn small" onClick={close}>Close</button></div>
        <dl className="kv box"><dt>Study</dt><dd className="mono">{s.study}</dd><dt>BioSample</dt><dd className="mono">{s.biosample}</dd><dt>Location</dt><dd>{s.location}</dd>
          <dt>Library</dt><dd>{s.library_strategy} · {s.platform}</dd><dt>Est. coverage</dt><dd>{s.coverage ?? '—'}×</dd><dt>Matched DST</dt><dd>{Object.keys(s.dst).length ? Object.entries(s.dst).map(([k, v]) => `${k}:${v}`).join(' ') : 'Unavailable'}</dd>
          {s.lineage && <><dt>Lineage</dt><dd className="mono">{s.lineage}</dd></>}{s.profiling_note && <><dt>Profiling</dt><dd style={{ fontSize: '.85rem' }}>{s.profiling_note}</dd></>}</dl>
        <div className="row"><RawLink kind="ena" k={s.run} label="View raw archive record" />{s.profiling === 'Done' && <RawLink kind="tbprofiler" k={s.run} label="View raw TB-Profiler JSON" />}</div>
        <div className="row" style={{ gap: 6 }}><Chip label={'Eligibility: ' + (s.eligibility || '—')} kind={s.eligibility || 'none'} /><Chip label={'Quality Control: ' + (s.qc || '—')} kind={s.qc || 'none'} /></div>
        {s.findings.length > 0 && <div className="box"><h3>Findings</h3>{s.findings.map(f => <div key={f.fid} style={{ fontSize: '.88rem', display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div className="row between"><span><span className="mono">{f.gene} {f.change}</span> · {f.drug}</span><Chip label={f.review} kind={f.review === 'Not required' ? 'none' : f.review.split(' ')[0]} /></div>
          {f.interpretation && <p className="muted"><span className="eyebrow">Evidence Analyst note · AI draft</span><br />{f.interpretation}</p>}</div>)}</div>}
        {mine.map(p => <div className="box gate" key={p.id}><h3>Pending override · {p.from} → {p.to}</h3><p style={{ fontSize: '.88rem' }}>Requested by {ROLE_LABEL[p.role]} ({p.person || 'unnamed'}): {p.rationale}</p>
          <div className="row"><button className="btn small primary" onClick={() => act(() => api.cosign({ ...who, override_id: p.id }), 'Override co-signed')}>Co-sign as {who.person || ROLE_LABEL[who.role]}</button>
            <RawLink kind="ena" k={run} /></div></div>)}
        <div className="box"><h3>Override a status</h3><p className="muted" style={{ fontSize: '.84rem' }}>More cautious changes apply at once. Relaxing a safeguard needs a second, different named person.</p>
          <div className="row"><select value={field} onChange={e => setField(e.target.value)} aria-label="Field"><option value="eligibility">Eligibility</option><option value="qc">Quality Control</option></select>
            <select value={to} onChange={e => setTo(e.target.value)} aria-label="New status">{(field === 'eligibility' ? ['Verified', 'Hold', 'Excluded'] : ['Pass', 'Escalated', 'Excluded']).map(o => <option key={o}>{o}</option>)}</select></div>
          <textarea value={why} onChange={e => setWhy(e.target.value)} placeholder="Rationale (required)" />
          <div className="row"><button className="btn small primary" onClick={() => act(() => api.override({ ...who, run, field, to, rationale: why }), 'Override recorded')}>Submit override</button>
            <RawLink kind="ena" k={run} /></div></div>
        <div className="box"><h3>Decision history</h3>{hist.length ? hist.map(d => <div className="fi" key={d.id}><span><Chip label={d.outcome} /></span>
          <div><div className="who">{fmtTime(d.ts)} · {actorLabel(d.actor)} · <span className="mono">{d.rule_version}</span></div><div>{d.rationale}</div>{d.evidence && <div className="muted" style={{ fontSize: '.8rem' }}>Evidence: {d.evidence}</div>}</div></div>) : <p className="muted">No decisions yet.</p>}</div>
      </aside>
    </>
  )
}
