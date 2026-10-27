import React, { useRef, useState } from 'react'
import { api } from '../api.js'
import { Chip, Rationale, actorLabel, ROLE_LABEL } from './common.jsx'
import { RawLink } from './Raw.jsx'

const STATUS = { locked: 'Locked', ready: 'Ready to run', wait: 'Waiting for human', done: 'Done' }

export default function Pipeline({ snap, decisions, view, setView, act, who, busy, openSample }) {
  const st = snap.state
  return (
    <>
      <div className="grid2">
        <Stage n={view} snap={snap} act={act} who={who} busy={busy} openSample={openSample} />
        <Feed decisions={decisions} />
      </div>
    </>
  )
}

function Feed({ decisions }) {
  return (
    <section className="panel">
      <h3>Live decisions</h3>
      {!decisions.length ? <p className="muted">Agent and human decisions appear here as each stage runs.</p> :
        <div className="feed">{decisions.slice(0, 18).map(d => (
          <div className="fi" key={d.id}><span><Chip label={d.outcome} /></span>
            <div style={{ minWidth: 0 }}><div className="who">{actorLabel(d.actor)} · <span className="mono">{d.sample_id}</span></div><div>{d.rationale}</div></div></div>))}</div>}
    </section>
  )
}

function Stage({ n, snap, act, who, busy, openSample }) {
  const st = snap.state, meta = snap.stages[n - 1], status = st.stage_status[String(n)]
  const agents = meta.agents
  const runBtn = <button className="btn primary" disabled={status !== 'ready' || !!busy} onClick={() => act(() => api.run(n), `Stage ${n} finished`)}>{status === 'ready' ? 'Run agents' : 'Ran'}</button>
  return (
    <section className="panel">
      <div className="row between"><div><span className="eyebrow">Stage {n} · owner: {ROLE_LABEL[meta.owner]}</span><h2>{meta.name}</h2></div>{runBtn}</div>
      <div className="tools">{agents.map(a => <span className="tool" key={a}>{a.replace(/_/g, ' ')}</span>)}</div>
      {busy && <div className="working" role="status" aria-live="polite"><span className="spinner" aria-hidden="true" /><span>Working on <b>{busy}</b>… agents are reasoning and calling tools; watch the Agent team tab for live traces.</span></div>}
      {status === 'locked' && <div className="box note"><p className="muted">This stage unlocks when the previous stage's human gate is passed.</p></div>}
      {n === 1 && <S1 st={st} status={status} act={act} who={who} />}
      {n === 2 && status !== 'locked' && status !== 'ready' && <S2 st={st} status={status} act={act} who={who} openSample={openSample} />}
      {n === 3 && ['wait', 'done'].includes(status) && <S3 st={st} status={status} act={act} who={who} openSample={openSample} />}
      {n === 4 && ['wait', 'done'].includes(status) && <S4 snap={snap} status={status} act={act} who={who} openSample={openSample} />}
      {n === 5 && status === 'done' && <S5 st={st} act={act} />}
      {n === 6 && ['wait', 'done'].includes(status) && <S6 st={st} act={act} who={who} />}
    </section>
  )
}

function S1({ st, status, act, who }) {
  const [q, setQ] = useState(st.question)
  const [country, setCountry] = useState(st.country || '')
  const [target, setTarget] = useState(st.cohort_target ?? 8)
  const sc = st.scope || {}
  if (status === 'ready') return (
    <div className="box"><span className="eyebrow">Research question</span>
      <textarea value={q} onChange={e => setQ(e.target.value)} aria-label="Research question" />
      <div className="row" style={{ gap: 14, alignItems: 'flex-end' }}>
        <div className="ctl"><label htmlFor="scope-country">Country (optional)</label>
          <input id="scope-country" value={country} onChange={e => setCountry(e.target.value)} placeholder="e.g. Indonesia · leave blank for worldwide" style={{ minWidth: 280 }} /></div>
        <div className="ctl"><label htmlFor="scope-target">Cohort target</label>
          <input id="scope-target" type="number" min="1" value={target} onChange={e => setTarget(Number(e.target.value) || 1)} style={{ width: 80 }} /></div>
      </div>
      <div className="row"><button className="btn small" onClick={() => act(() => api.setScope({ question: q, country, target_drugs: st.target_drugs, cohort_target: target }), 'Scope saved')}>Save scope</button>
        <span className="muted" style={{ fontSize: '.82rem' }}>Save, then click Run agents. The Scope Guardian reviews it.</span></div></div>)
  return (
    <>
      <div className="box"><span className="eyebrow">Research question</span><p>{st.question}</p>
        <p className="muted" style={{ fontSize: '.82rem' }}>Scope: {st.country ? <>country <b>{st.country}</b></> : <>worldwide</>} · cohort target {st.cohort_target} · drugs {st.target_drugs.join(', ')}</p></div>
      {sc.blocking?.length > 0 && <div className="box esc"><h3>Blocking gaps</h3><ul className="clean">{sc.blocking.map(b => <li key={b}>{b}</li>)}</ul></div>}
      <div className="box esc"><h3>Gaps the Guardian found, with proposed definitions</h3>
        <ul className="clean">{(sc.gaps || []).map(g => <li key={g.gap}>{g.gap} <i>Proposed:</i> {g.proposal}{g.added_by === 'guardrail' && <span className="muted"> (added by guardrail)</span>}</li>)}</ul>
        {sc.warnings?.length > 0 && <><h3>Warnings</h3><ul className="clean">{sc.warnings.map(w => <li key={w}>{w}</li>)}</ul></>}</div>
      {status === 'wait' && <div className="box gate"><h3>Gate · Researcher approval</h3><p>Approving accepts the proposed definitions.</p>
        <div className="row"><button className="btn primary" onClick={() => act(() => api.gate('scope', who), 'Scope approved')}>Approve scope</button>
          <RawLink kind="scope" k="guardian" /></div></div>}
      {status === 'done' && <p className="okmsg">Scope approved by {st.gates.scope?.person || ROLE_LABEL[st.gates.scope?.role] || 'researcher'}</p>}
    </>
  )
}

function S2({ st, status, act, who, openSample }) {
  const v = st.samples.filter(s => s.eligibility === 'Verified'), h = st.samples.filter(s => s.eligibility === 'Hold'), x = st.samples.filter(s => s.eligibility === 'Excluded')
  const [bulk, setBulk] = useState(() => new Set())
  const [bulkWhy, setBulkWhy] = useState('')
  const bulkToggle = (r) => setBulk(prev => { const s = new Set(prev); s.has(r) ? s.delete(r) : s.add(r); return s })
  const bulkRuns = h.map(s => s.run).filter(r => bulk.has(r))
  const bulkResolve = (decision) => act(async () => {
    if (!bulkWhy.trim()) throw new Error('A rationale is required.')
    const results = await Promise.allSettled(bulkRuns.map(run => api.resolveHold({ ...who, run, decision, rationale: bulkWhy })))
    const failed = results.filter(r => r.status === 'rejected').length
    if (failed) throw new Error(`${results.length - failed} applied, ${failed} failed`)
    setBulk(new Set()); setBulkWhy('')
  }, `${bulkRuns.length} hold(s) resolved as ${decision}`)
  const SHOW_BULK = h.length >= 10
  return (
    <>
      <div className="metrics">
        <div className="metric"><span className="v">{st.samples.length}</span><span className="l">Candidates found</span></div>
        <div className="metric"><span className="v" style={{ color: 'var(--ok)' }}>{v.length}</span><span className="l">Verified (target ≥{st.cohort_target})</span></div>
        <div className="metric"><span className="v" style={{ color: 'var(--hold)' }}>{h.length}</span><span className="l">On hold</span></div>
        <div className="metric"><span className="v" style={{ color: 'var(--ex)' }}>{x.length}</span><span className="l">Excluded</span></div>
      </div>
      {st.cohort_checks.length > 0 && <div className={'box ' + (st.cohort_checks.some(c => c.outcome === 'Escalate') ? 'esc' : 'note')}>
        <h3>Cohort checks{st.replans ? ` · Orchestrator re-planned ${st.replans}×` : ''}</h3>
        <ul className="clean" style={{ listStyle: 'none', padding: 0 }}>{st.cohort_checks.map(c => <li key={c.text}><Chip label={c.outcome === 'Proceed' ? 'Note' : c.outcome} kind={c.outcome === 'Proceed' ? 'none' : c.outcome} /> {c.text}</li>)}</ul></div>}
      {SHOW_BULK && <div className="box gate" style={{ gap: 6 }}>
        <div className="row between"><h3>Bulk resolve · {h.length} holds</h3>
          <div className="row" style={{ gap: 6 }}>
            <button className="btn small" onClick={() => setBulk(new Set(h.map(s => s.run)))}>Select all</button>
            <button className="btn small ghost" onClick={() => setBulk(new Set())}>Clear</button>
          </div></div>
        <textarea value={bulkWhy} onChange={e => setBulkWhy(e.target.value)} placeholder="Shared rationale (applied to every selected hold)" aria-label="Bulk rationale" />
        <div className="row"><span className="muted" style={{ fontSize: '.82rem' }}>{bulkRuns.length} selected</span>
          <button className="btn small primary" disabled={!bulkRuns.length} onClick={() => bulkResolve('verify')}>Verify selected</button>
          <button className="btn small" disabled={!bulkRuns.length} onClick={() => bulkResolve('exclude')}>Exclude selected</button>
          <button className="btn small" disabled={!bulkRuns.length} onClick={() => bulkResolve('hold')}>Keep on hold</button>
        </div></div>}
      {h.map(s => <div className="box esc" key={s.run}>
        <div className="row between">
          <div className="row" style={{ gap: 8 }}>
            {SHOW_BULK && <input type="checkbox" checked={bulk.has(s.run)} onChange={() => bulkToggle(s.run)} aria-label={`Select ${s.run} for bulk`} />}
            <button className="btn small ghost mono" onClick={() => openSample(s.run)}>{s.run}</button>
          </div>
          <Chip label="Escalate" /></div>
        <p>{s.eligibility_note}</p>
        <Rationale id={'h-' + s.run} placeholder="e.g. Origin confirmed in the study's methods" buttons={[['verify', 'Verify', true], ['exclude', 'Exclude'], ['hold', 'Keep on hold']]}
          extra={<RawLink kind="ena" k={s.run} />}
          onSubmit={(d, r) => act(() => api.resolveHold({ ...who, run: s.run, decision: d, rationale: r }), 'Decision recorded')} /></div>)}
      {status === 'wait' && <div className="box gate"><h3>Gate · Cohort approval</h3><p>{v.length} verified runs enter the primary cohort; approving accepts the cohort checks as limitations.</p>
        <div className="row"><button className="btn primary" onClick={() => act(() => api.gate('cohort', who), 'Cohort approved')}>Approve cohort ({v.length})</button>
          <RawLink kind="cohort" k="all" /></div></div>}
    </>
  )
}

function S3({ st, status, act, who, openSample }) {
  const c = st.samples.filter(s => s.in_cohort)
  return (
    <>
      <div className="tw"><table><thead><tr><th>Run</th><th className="num">Est. coverage</th><th>Checksum</th><th>QC</th></tr></thead><tbody>
        {c.map(s => <tr className="click" key={s.run} onClick={() => openSample(s.run)}><td className="mono">{s.run}</td><td className="num">{s.coverage ?? '—'}×</td><td>{s.md5 ? 'MD5 listed' : '—'}</td><td><Chip label={s.qc || '—'} /></td></tr>)}
      </tbody></table></div>
      {c.filter(s => s.qc === 'Escalated').map(s => <div className="box esc" key={s.run}><div className="row between"><span className="mono">{s.run}</span><Chip label="Escalate" /></div><p>{s.qc_note}</p>
        <Rationale id={'q-' + s.run} placeholder="e.g. Coverage at target regions >40× in BAM" buttons={[['proceed', 'Proceed with justification', true], ['exclude', 'Exclude']]}
          extra={<RawLink kind="ena" k={s.run} />}
          onSubmit={(d, r) => act(() => api.resolveQc({ ...who, run: s.run, decision: d, rationale: r }), 'QC decision recorded')} /></div>)}
      {status === 'wait' && <div className="box gate"><h3>Gate · Confirm QC decisions</h3>
        <div className="row"><button className="btn primary" onClick={() => act(() => api.gate('qc', who), 'QC confirmed')}>Confirm and advance</button>
          <RawLink kind="qc" k="all" /></div></div>}
    </>
  )
}

function S4({ snap, status, act, who, openSample }) {
  const st = snap.state, q = st.samples.filter(s => s.qc === 'Pass'), done = q.filter(s => s.profiling === 'Done')
  const [over, setOver] = useState(false)
  const input = useRef(null)
  const upload = files => act(() => api.importFiles(who, files).then(r => { if (r.skipped.length) throw new Error(`Imported ${r.imported.length}; skipped: ${r.skipped.join('; ')}`) }), 'Results imported')
  const tools = snap.mode.tbprofiler
  const canRun = tools['tb-profiler'] && tools['fasterq-dump']
  const waiting = q.filter(s => s.profiling !== 'Done').map(s => s.run)
  const [selected, setSelected] = useState(() => new Set())
  const [n, setN] = useState(5)
  const toggle = (r) => setSelected(prev => { const s = new Set(prev); s.has(r) ? s.delete(r) : s.add(r); return s })
  const chosen = waiting.filter(r => selected.has(r))  // keep selection in waiting-order and drop stale ones
  return (
    <>
      <div className="metrics"><div className="metric"><span className="v">{q.length}</span><span className="l">QC-passed runs</span></div>
        <div className="metric"><span className="v" style={{ color: 'var(--ok)' }}>{done.length}</span><span className="l">TB-Profiler results</span></div>
        <div className="metric"><span className="v" style={{ color: 'var(--hold)' }}>{q.length - done.length}</span><span className="l">Awaiting results</span></div></div>
      <div className="box"><h3>Run TB-Profiler</h3>
        {canRun ? <>
          <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
            <span className="muted" style={{ fontSize: '.82rem' }}>Pick which runs to profile — one sample can take 15–30 min.</span>
          </div>
          <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
            <button className="btn small" onClick={() => setSelected(new Set(waiting.slice(0, Math.max(1, n))))}>Select first</button>
            <input type="number" min="1" max={waiting.length || 1} value={n} onChange={e => setN(Math.max(1, Number(e.target.value) || 1))} style={{ width: 70 }} aria-label="How many" />
            <button className="btn small" onClick={() => setSelected(new Set(waiting))}>Select all ({waiting.length})</button>
            <button className="btn small ghost" onClick={() => setSelected(new Set())}>Clear</button>
          </div>
          {waiting.length > 0 && <div className="tw" style={{ maxHeight: 220, overflow: 'auto' }}>
            <table><tbody>
              {waiting.map(r => (
                <tr key={r} className="click" onClick={() => toggle(r)}>
                  <td style={{ width: 32 }}><input type="checkbox" checked={selected.has(r)} onChange={() => toggle(r)} onClick={e => e.stopPropagation()} aria-label={`Select ${r}`} /></td>
                  <td className="mono">{r}</td>
                </tr>
              ))}
            </tbody></table>
          </div>}
          <div className="row"><button className="btn primary" disabled={!chosen.length} onClick={() => act(() => api.runProfiler({ ...who, runs: chosen }), `TB-Profiler started on ${chosen.length} run(s)`)}>Run TB-Profiler on {chosen.length} selected</button>
            <span className="muted" style={{ fontSize: '.82rem' }}>Runs on this computer, up to {snap.profiler_concurrency || '?'} at a time (set TBAMR_PROFILER_CONCURRENCY to tune).</span></div>
        </>
          : <p className="muted" style={{ fontSize: '.88rem' }}>TB-Profiler isn't installed where the backend runs ({Object.entries(tools).map(([k, v]) => `${k}: ${v ? 'yes' : 'no'}`).join(', ')}). Run it yourself and import the <span className="mono">results/&lt;RUN&gt;.results.json</span> files below.</p>}
      </div>
      <div className={'drop' + (over ? ' over' : '')} tabIndex={0} onClick={() => input.current.click()} onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && input.current.click()}
        onDragOver={e => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)} onDrop={e => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files) }}>
        <p><b>Drop TB-Profiler result files here</b> (.results.json) or click to choose</p></div>
      <input ref={input} type="file" accept=".json" multiple hidden onChange={e => { upload(e.target.files); e.target.value = '' }} />
      {done.length > 0 && <div className="tw"><table><thead><tr><th>Run</th><th>Lineage</th><th>TB-Profiler type</th><th>Source</th><th></th></tr></thead><tbody>
        {done.map(s => <tr className="click" key={s.run} onClick={() => openSample(s.run)}><td className="mono">{s.run}</td><td className="mono">{s.lineage || '—'}</td><td>{s.drtype || '—'}</td><td className="muted" style={{ fontSize: '.82rem' }}>{s.profiling_note}</td><td><RawLink kind="tbprofiler" k={s.run} label="Raw JSON" /></td></tr>)}</tbody></table></div>}
      {status === 'wait' && <div className="box gate"><h3>Gate · Close profiling batch</h3><p>Results imported later are evaluated automatically.</p>
        <div className="row"><button className="btn primary" disabled={!done.length} onClick={() => act(() => api.gate('profiling', who), 'Batch closed')}>Close batch ({done.length})</button>
          {done.length > 0 && <RawLink kind="profiling" k="all" />}</div></div>}
    </>
  )
}

function S5({ st, act }) {
  const f = st.samples.flatMap(s => s.findings)
  return <><div className="metrics"><div className="metric"><span className="v">{f.filter(x => x.cls !== 'other').length}</span><span className="l">Resistance findings</span></div>
    <div className="metric"><span className="v" style={{ color: 'var(--pend)' }}>{f.filter(x => x.review === 'Pending').length}</span><span className="l">Pending review</span></div>
    <div className="metric"><span className="v" style={{ color: 'var(--ok)' }}>{f.filter(x => x.review === 'Reviewed').length}</span><span className="l">Reviewed</span></div></div>
    <div className="row"><button className="btn small" onClick={() => act(() => api.run(5), 'New results evaluated')}>Evaluate newly imported results</button></div></>
}

function S6({ st, act, who }) {
  const r = st.report
  if (!r) return null
  const pending = r.unresolved.length
  return <div className="box gate"><h3>Gate · Release</h3>
    {st.gates.release && <p className="okmsg">{st.gates.release.kind === 'final' ? 'Final release' : 'Exploratory draft shared'} · v{st.gates.release.version} · {st.gates.release.person || ROLE_LABEL[st.gates.release.role]}</p>}
    {r.superseded && <p className="msg">Report superseded — click Regenerate before release.</p>}
    <p>{pending ? `${pending} finding(s) pending review: final release is blocked.` : 'No pending findings.'}</p>
    <div className="row"><button className="btn primary" disabled={!!pending || r.superseded} onClick={() => act(() => api.release({ ...who, kind: 'final' }), 'Released')}>Approve final release</button>
      <button className="btn" disabled={r.superseded} onClick={() => act(() => api.release({ ...who, kind: 'draft' }), 'Draft shared')}>Share exploratory draft</button>
      <button className="btn" onClick={() => act(() => api.run(6), 'Report regenerated')}>Regenerate report</button>
      {!r.superseded && <RawLink kind="report" k={String(r.version)} />}</div></div>
}
