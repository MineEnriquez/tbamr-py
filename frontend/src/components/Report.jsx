import React from 'react'
import { api } from '../api.js'
import { Chip } from './common.jsx'
import { RawLink } from './Raw.jsx'

export default function Report({ st, act, brain }) {
  const r = st.report
  if (!r) return <div className="panel"><p className="muted">The report is assembled in Stage 6. Every number is computed by rule from the decision records.</p></div>
  const c = r.counts, max = Math.max(1, c.candidates)
  const bar = (l, v, acc) => <div className="row" style={{ flexWrap: 'nowrap' }} key={l}><span style={{ width: 170 }}>{l}</span>
    <span style={{ flex: 1, background: 'var(--surface-2)', height: 14, borderRadius: 3, overflow: 'hidden' }}><span style={{ display: 'block', height: '100%', width: `${v / max * 100}%`, background: acc ? 'var(--accent)' : 'var(--blue)' }} /></span>
    <span className="mono" style={{ width: 36, textAlign: 'right' }}>{v}</span></div>
  const released = st.gates.release?.kind === 'final' && !r.superseded
  return (
    <section className="panel">
      <div className="row between"><div><span className="eyebrow">Report v{r.version} · {r.rule_version}</span><h2>Genomic resistance evidence</h2></div>
        <div className="row"><RawLink kind="report" k={String(r.version)} label="View underlying data" /><Chip label={released ? 'Released · final' : 'Exploratory · not scientifically approved'} kind={released ? 'Proceed' : 'Pending'} /></div></div>
      {r.superseded && <div className="box esc"><p><b>Superseded.</b> Something changed after this version; regenerate it in Stage 6.</p></div>}
      <div className="box note"><p>Computational predictions from public genomes: not laboratory-confirmed susceptibility, not a national prevalence estimate.</p></div>
      <div className="box"><div className="row between"><h3>Plain-language summary</h3><button className="btn small" onClick={() => act(() => api.summary(), 'Summary drafted')}>✦ Draft summary{brain === 'replay' ? ' (replay)' : ''}</button></div>
        {r.summary_draft ? <><span className="eyebrow">AI draft · not a decision</span><p>{r.summary_draft}</p></> : <p className="muted">Ask the Reporting agent for a draft summary.</p>}</div>
      <div><h3>Sample counts</h3>{bar('Total candidates', c.candidates)}{bar('Verified eligible', c.verified)}{bar('QC-passed', c.qc_passed)}{bar('Profiled & evaluated', c.analysed, true)}</div>
      <div><h3>Resistance evidence by drug <span className="muted" style={{ fontWeight: 400 }}>(n = {c.analysed})</span></h3>
        <div className="tw"><table><thead><tr><th>Drug</th><th className="num">Predicted resistant</th><th className="num">Uncertain / pending</th><th className="num">Reviewed</th><th className="num">Matched DST</th><th className="num">Concordance</th></tr></thead><tbody>
          {r.drugs.map(d => <tr key={d.drug}><td>{d.name}</td><td className="num">{d.predicted_resistant} / {d.n}</td><td className="num">{d.uncertain_or_pending}</td><td className="num">{d.reviewed}</td><td className="num">{d.dst_n} / {d.n}</td><td className="num">{d.dst_n ? `${d.concordant} / ${d.dst_n}` : 'n/a'}</td></tr>)}
        </tbody></table></div></div>
      <div className="grid2" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))' }}>
        <div className="box"><h3>Most frequent mutations</h3>{r.top_mutations.length ? <ul className="clean">{r.top_mutations.map(([k, v]) => <li key={k}><span className="mono">{k}</span> — {v}</li>)}</ul> : <p className="muted">None yet.</p>}</div>
        <div className="box"><h3>Lineages</h3>{r.lineages.length ? <ul className="clean">{r.lineages.map(([k, v]) => <li key={k}><span className="mono">{k}</span> — {v}</li>)}</ul> : <p className="muted">None yet.</p>}</div>
        <div className="box"><h3>Limitations</h3><ul className="clean">{r.limitations.map(l => <li key={l}>{l}</li>)}</ul></div>
      </div>
      <div><h3>Unresolved findings</h3>{r.unresolved.length ? <ul className="clean">{r.unresolved.map(u => <li key={u.run + u.variant}><span className="mono">{u.run}</span> · {u.variant} ({u.drug}) — {u.reason}</li>)}</ul> : <p className="muted">None.</p>}</div>
      <div><h3>Exclusions and holds</h3><div className="tw"><table><thead><tr><th>Run</th><th>Status</th><th>Reason</th></tr></thead><tbody>
        {r.exclusions.map(x => <tr key={x.run}><td className="mono">{x.run}</td><td><Chip label={x.status || '—'} /></td><td style={{ fontSize: '.86rem' }}>{x.reason}</td></tr>)}
        {!r.exclusions.length && <tr><td colSpan={3} className="muted">None</td></tr>}</tbody></table></div></div>
      <dl className="kv box"><dt>Tools</dt><dd>{r.provenance.tools.join(', ') || '—'}</dd><dt>Databases</dt><dd>{r.provenance.databases.join(', ') || '—'}</dd><dt>Rules</dt><dd className="mono">{Object.values(r.provenance.rules).join(' · ')}</dd></dl>
    </section>
  )
}
