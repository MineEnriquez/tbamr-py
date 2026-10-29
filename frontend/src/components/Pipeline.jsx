import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { Chip, Rationale, RoleBadge, actorLabel, ROLE_LABEL } from './common.jsx'
import { RawLink } from './Raw.jsx'

const STATUS = { locked: 'Locked', ready: 'Ready to run', wait: 'Waiting for human', done: 'Done' }

/* Scope-conflict detector: if the research question text names a specific country that disagrees
 * with the Country input field, the Scope Guardian (backend) will silently use the field and ignore
 * the question. We detect it client-side so the user is forced to reconcile the two before Run.
 *
 * Deliberately small list — common countries + a handful of demonyms. Not exhaustive, but it
 * catches the realistic mistake of "the Indonesian / Kenyan picture" vs the Country field. */
const COUNTRY_ALIASES = [
  ['Indonesia', ['indonesia', 'indonesian']],
  ['Kenya', ['kenya', 'kenyan']],
  ['India', ['india', 'indian']],
  ['Nigeria', ['nigeria', 'nigerian']],
  ['South Africa', ['south africa', 'south african']],
  ['Philippines', ['philippines', 'philippine', 'filipino']],
  ['Vietnam', ['vietnam', 'vietnamese']],
  ['Pakistan', ['pakistan', 'pakistani']],
  ['Bangladesh', ['bangladesh', 'bangladeshi']],
  ['China', ['china', 'chinese']],
  ['Myanmar', ['myanmar', 'burma', 'burmese']],
  ['Thailand', ['thailand', 'thai']],
  ['Peru', ['peru', 'peruvian']],
  ['Brazil', ['brazil', 'brazilian']],
  ['Mexico', ['mexico', 'mexican']],
  ['Ethiopia', ['ethiopia', 'ethiopian']],
  ['Tanzania', ['tanzania', 'tanzanian']],
  ['Uganda', ['uganda', 'ugandan']],
  ['Mozambique', ['mozambique', 'mozambican']],
  ['Russia', ['russia', 'russian']],
  ['Ukraine', ['ukraine', 'ukrainian']],
  ['Zambia', ['zambia', 'zambian']],
  ['Zimbabwe', ['zimbabwe', 'zimbabwean']],
]

function detectCountryInQuestion(question) {
  const q = ' ' + String(question || '').toLowerCase() + ' '
  for (const [canonical, aliases] of COUNTRY_ALIASES) {
    for (const a of aliases) {
      // word-boundary match: surround alias with non-letter chars in the padded string
      if (new RegExp('[^a-z]' + a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '[^a-z]').test(q)) {
        return { canonical, matched: a }
      }
    }
  }
  return null
}

/* Strip the specific alias we matched out of the question text (word-boundary), leaving the rest
 * of the sentence intact so the user can keep editing. */
function stripCountryFromQuestion(question, alias) {
  return String(question || '')
    .replace(new RegExp('\\b' + alias.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b', 'gi'), '')
    .replace(/\s+/g, ' ').trim()
}

export default function Pipeline({ snap, decisions, view, setView, act, who, busy, openSample }) {
  const st = snap.state
  // view===0 is the Start hero (research question gets full width + big typography); views 1-6 are
  // the regular stages, which share the panel with the Live decisions feed.
  if (view === 0) return <StartHero snap={snap} act={act} who={who} busy={busy} setView={setView} />
  return (
    <div className="grid2">
      <Stage n={view} snap={snap} act={act} who={who} busy={busy} openSample={openSample} />
      <Feed decisions={decisions} />
    </div>
  )
}

/* The landing / Start view: single big panel focused on the research question. When Stage 1 has
 * already run we show the saved scope prominently and point the user at Stage 1 for the Guardian's
 * findings. All behaviour (dirty gate, conflict detection, Save+Run) matches the S1 editor. */
function StartHero({ snap, act, who, busy, setView }) {
  const st = snap.state, status = st.stage_status['1']
  const [q, setQ] = useState(st.question)
  const [country, setCountry] = useState(st.country || '')
  const [target, setTarget] = useState(st.cohort_target ?? 8)
  const conflict = useMemo(() => {
    const inQ = detectCountryInQuestion(q)
    const field = country.trim()
    if (!inQ || !field) return null
    if (inQ.canonical.toLowerCase() === field.toLowerCase()) return null
    return { canonical: inQ.canonical, matched: inQ.matched, field }
  }, [q, country])
  const dirty = status === 'ready' && (q !== st.question || country !== (st.country || '') || target !== (st.cohort_target ?? 8))
  const save = () => act(() => api.setScope({ question: q, country, target_drugs: st.target_drugs, cohort_target: target }), 'Scope saved')
  const start = () => act(() => api.run(1), 'Stage 1 finished')
  const canRun = status === 'ready' && !busy && !dirty && !conflict
  if (status !== 'ready') return (
    <section className="panel start-hero">
      <span className="eyebrow">Start · Research question</span>
      <h1 className="start-q">{st.question || <span className="muted">No research question yet.</span>}</h1>
      <p className="start-sub">Scope: {st.country ? <>country <b>{st.country}</b></> : <>worldwide</>} · cohort target <b>{st.cohort_target}</b> · drugs <b>{st.target_drugs.join(', ')}</b></p>
      <div className="row" style={{ gap: 10, marginTop: 12 }}>
        <button className="btn primary" onClick={() => setView(1)}>Go to Stage 1 →</button>
        <button className="btn ghost" title="Reopen the scope form; clears downstream work (samples/report) but preserves decision history." onClick={() => { if (confirm('Reopen scope? This clears discovered samples and any report, but keeps the decision history.')) act(() => api.reopenScope(), 'Scope reopened') }}>✎ Edit scope</button>
      </div>
    </section>
  )
  return (
    <section className="panel start-hero">
      <span className="eyebrow">Start · Define the research question</span>
      <h2 className="start-h">What do you want the TB-AMR agents to investigate?</h2>
      <p className="start-sub muted">Nothing moves until you've written this. The Scope Guardian will check it for the four required definitions before any sample is pulled.</p>
      <textarea value={q} onChange={e => setQ(e.target.value)} aria-label="Research question" className="start-ta"
        placeholder="e.g. What patterns of drug resistance can we identify in Mycobacterium tuberculosis genomic samples from Indonesia, and which mutations are associated with resistance to rifampicin and isoniazid?" />
      <div className="row" style={{ gap: 14, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div className="ctl"><label htmlFor="start-country">Country <span className="muted" style={{ fontWeight: 400 }}>(or state it in the question)</span></label>
          <input id="start-country" value={country} onChange={e => setCountry(e.target.value)} placeholder='e.g. Indonesia · "Worldwide" for no filter · or leave blank if the question says so' style={{ minWidth: 320 }} /></div>
        <div className="ctl"><label htmlFor="start-target">Cohort target</label>
          <input id="start-target" type="number" min="1" value={target} onChange={e => setTarget(Number(e.target.value) || 1)} style={{ width: 80 }} /></div>
      </div>
      {conflict && <div className="box esc" style={{ marginTop: 10 }}>
        <h3>Country/question conflict — pick one</h3>
        <p>Your question mentions <b>{conflict.canonical}</b> but the Country field is set to <b>{conflict.field}</b>. The agents only read the Country field, so one of these will be silently ignored. Pick which one to keep before you can save or start.</p>
        <div className="row" style={{ gap: 6 }}>
          <button className="btn small primary" onClick={() => setCountry(conflict.canonical)}>Use <b>{conflict.canonical}</b> (set the field)</button>
          <button className="btn small" onClick={() => setQ(stripCountryFromQuestion(q, conflict.matched))}>Use <b>{conflict.field}</b> (remove "{conflict.matched}" from the question)</button>
        </div>
      </div>}
      <div className="row" style={{ gap: 8, marginTop: 14 }}>
        <button className="btn primary" disabled={!dirty || !!conflict} onClick={save}>{dirty ? 'Save scope' : '✓ Scope saved'}</button>
        <button className="btn primary" disabled={!canRun} title={!canRun ? (conflict ? 'Resolve the conflict first' : dirty ? 'Save the scope first' : busy ? 'A stage is running' : '') : 'Hand the scope to the Scope Guardian'} onClick={start}>Start the pipeline →</button>
        <span className="muted" style={{ fontSize: '.82rem' }}>{conflict ? 'Fix the conflict above.' : dirty ? 'Save, then Start.' : canRun ? 'Ready to start.' : ''}</span>
      </div>
    </section>
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
  // Stage 1 "Run agents" is only enabled when the current scope form is saved AND has no
  // country/question conflict (the Guardian would otherwise silently use the field and ignore the question).
  const [scopeDirty, setScopeDirty] = useState(false)
  const [scopeBlocked, setScopeBlocked] = useState(false)
  const disabled = n === 1 && status === 'ready' && (scopeDirty || scopeBlocked)
  const disabledReason = (n === 1 && status === 'ready')
    ? (scopeBlocked ? 'Resolve the country/question conflict first' : (scopeDirty ? 'Save the scope first' : ''))
    : (busy ? 'A stage is running' : '')
  const runBtn = <button className="btn primary" disabled={status !== 'ready' || !!busy || disabled} title={disabledReason || undefined}
                   onClick={() => act(() => api.run(n), `Stage ${n} finished`)}>{status === 'ready' ? 'Run agents' : 'Ran'}</button>
  return (
    <section className="panel">
      <div className="row between"><div><span className="eyebrow">Stage {n} · owner: {ROLE_LABEL[meta.owner]}</span><h2>{meta.name}</h2></div>{runBtn}</div>
      <div className="tools">{agents.map(a => <span className="tool" key={a}>{a.replace(/_/g, ' ')}</span>)}</div>
      {busy && <div className="working" role="status" aria-live="polite"><span className="spinner" aria-hidden="true" /><span>Working on <b>{busy}</b>… agents are reasoning and calling tools; watch the Agent team tab for live traces.</span></div>}
      {status === 'locked' && <div className="box note"><p className="muted">This stage unlocks when the previous stage's human gate is passed.</p></div>}
      {n === 1 && <S1 st={st} status={status} act={act} who={who} onDirtyChange={setScopeDirty} onBlockedChange={setScopeBlocked} />}
      {n === 2 && status !== 'locked' && status !== 'ready' && <S2 st={st} status={status} act={act} who={who} openSample={openSample} />}
      {n === 3 && ['wait', 'done'].includes(status) && <S3 st={st} status={status} act={act} who={who} openSample={openSample} />}
      {n === 4 && ['wait', 'done'].includes(status) && <S4 snap={snap} status={status} act={act} who={who} openSample={openSample} />}
      {n === 5 && status === 'done' && <S5 st={st} act={act} />}
      {n === 6 && ['wait', 'done'].includes(status) && <S6 st={st} act={act} who={who} />}
    </section>
  )
}

function S1({ st, status, act, who, onDirtyChange, onBlockedChange }) {
  const [q, setQ] = useState(st.question)
  const [country, setCountry] = useState(st.country || '')
  const [target, setTarget] = useState(st.cohort_target ?? 8)
  const sc = st.scope || {}
  // Detect a question/country-field conflict: if the question clearly names a country different
  // from the Country field, the Guardian will silently use the field. Force the user to reconcile.
  const conflict = useMemo(() => {
    const inQ = detectCountryInQuestion(q)
    const fieldTrim = country.trim()
    if (!inQ) return null
    if (!fieldTrim) return null  // only the question specifies a country — fine, let the Guardian use it
    if (inQ.canonical.toLowerCase() === fieldTrim.toLowerCase()) return null  // they agree
    return { canonical: inQ.canonical, matched: inQ.matched, field: fieldTrim }
  }, [q, country])
  // When the form drifts from what's in the backend, mark the whole stage dirty so the Run button disables.
  const dirty = status === 'ready' && (q !== st.question || country !== (st.country || '') || target !== (st.cohort_target ?? 8))
  useEffect(() => { onDirtyChange && onDirtyChange(dirty) }, [dirty, onDirtyChange])
  useEffect(() => { onBlockedChange && onBlockedChange(!!conflict) }, [conflict, onBlockedChange])
  if (status === 'ready') return (
    <div className="box"><span className="eyebrow">Research question</span>
      <textarea value={q} onChange={e => setQ(e.target.value)} aria-label="Research question" />
      <div className="row" style={{ gap: 14, alignItems: 'flex-end' }}>
        <div className="ctl"><label htmlFor="scope-country">Country <span className="muted" style={{ fontWeight: 400 }}>(or state it in the question)</span></label>
          <input id="scope-country" value={country} onChange={e => setCountry(e.target.value)} placeholder='e.g. Indonesia · "Worldwide" for no filter · or leave blank if the question says so' style={{ minWidth: 320 }} /></div>
        <div className="ctl"><label htmlFor="scope-target">Cohort target</label>
          <input id="scope-target" type="number" min="1" value={target} onChange={e => setTarget(Number(e.target.value) || 1)} style={{ width: 80 }} /></div>
      </div>
      {conflict && <div className="box esc" style={{ marginTop: 10 }}>
        <h3>Country/question conflict — pick one</h3>
        <p>Your question mentions <b>{conflict.canonical}</b> but the Country field is set to <b>{conflict.field}</b>. The agents only read the Country field, so one of these will be silently ignored. Pick which one to keep before you can save or run.</p>
        <div className="row" style={{ gap: 6 }}>
          <button className="btn small primary" onClick={() => setCountry(conflict.canonical)}>Use <b>{conflict.canonical}</b> (set the field)</button>
          <button className="btn small" onClick={() => setQ(stripCountryFromQuestion(q, conflict.matched))}>Use <b>{conflict.field}</b> (remove "{conflict.matched}" from the question)</button>
        </div>
      </div>}
      <div className="row"><button className="btn small primary" disabled={!dirty || !!conflict} onClick={() => act(() => api.setScope({ question: q, country, target_drugs: st.target_drugs, cohort_target: target }), 'Scope saved')}>{dirty ? 'Save scope' : '✓ Scope saved'}</button>
        <span className="muted" style={{ fontSize: '.82rem' }}>
          {conflict ? 'Resolve the conflict above before saving.' : (dirty ? 'Unsaved changes — Save scope before Run agents.' : 'Scope saved. Click Run agents to kick off the Scope Guardian.')}
        </span></div></div>)
  return (
    <>
      <div className="box">
        <div className="row between" style={{ alignItems: 'flex-start' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <span className="eyebrow">Research question</span><p>{st.question}</p>
            <p className="muted" style={{ fontSize: '.82rem' }}>Scope: {st.country ? <>country <b>{st.country}</b></> : <>worldwide (not set explicitly)</>} · cohort target {st.cohort_target} · drugs {st.target_drugs.join(', ')}</p>
          </div>
          <button className="btn small ghost" title="Reopen the scope form; clears downstream work (samples/report) but preserves decision history." onClick={() => { if (confirm('Reopen scope? This clears discovered samples and any report, but keeps the decision history.')) act(() => api.reopenScope(), 'Scope reopened') }}>✎ Edit scope</button>
        </div>
      </div>
      {sc.blocking?.length > 0 && <div className="box esc"><h3>Blocking gaps</h3><ul className="clean">{sc.blocking.map(b => <li key={b}>{b}</li>)}</ul></div>}
      <div className="box esc"><h3>Gaps the Guardian found, with proposed definitions</h3>
        <ul className="clean">{(sc.gaps || []).map(g => <li key={g.gap}>{g.gap} <i>Proposed:</i> {g.proposal}{g.added_by === 'guardrail' && <span className="muted"> (added by guardrail)</span>}</li>)}</ul>
        {sc.warnings?.length > 0 && <><h3>Warnings</h3><ul className="clean">{sc.warnings.map(w => <li key={w}>{w}</li>)}</ul></>}</div>
      {status === 'wait' && <div className="box gate"><h3>Gate · Researcher approval</h3>
        <p className="role-reqd">Only <RoleBadge role="pi" /> can approve the scope.</p>
        <p>Approving accepts the proposed definitions.</p>
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
      {status === 'wait' && <div className="box gate"><h3>Gate · Cohort approval</h3>
        <p className="role-reqd">Only <RoleBadge role="pi" /> can approve the cohort.</p>
        <p>{v.length} verified runs enter the primary cohort; approving accepts the cohort checks as limitations.</p>
        <div className="row"><button className="btn primary" onClick={() => act(() => api.gate('cohort', who), 'Cohort approved')}>Approve cohort ({v.length})</button>
          <RawLink kind="cohort" k="all" /></div></div>}
    </>
  )
}

function S3({ st, status, act, who, openSample }) {
  const c = st.samples.filter(s => s.in_cohort)
  return (
    <>
      <div className="tw"><table><thead><tr><th>Run</th><th className="num">Est. coverage</th><th>Checksum</th><th>Quality Control</th></tr></thead><tbody>
        {c.map(s => <tr className="click" key={s.run} onClick={() => openSample(s.run)}><td className="mono">{s.run}</td><td className="num">{s.coverage ?? '—'}×</td><td>{s.md5 ? 'MD5 listed' : '—'}</td><td><Chip label={s.qc || '—'} /></td></tr>)}
      </tbody></table></div>
      {c.filter(s => s.qc === 'Escalated').map(s => <div className="box esc" key={s.run}><div className="row between"><span className="mono">{s.run}</span><Chip label="Escalate" /></div><p>{s.qc_note}</p>
        <Rationale id={'q-' + s.run} placeholder="e.g. Coverage at target regions >40× in BAM" buttons={[['proceed', 'Proceed with justification', true], ['exclude', 'Exclude']]}
          extra={<RawLink kind="ena" k={s.run} />}
          onSubmit={(d, r) => act(() => api.resolveQc({ ...who, run: s.run, decision: d, rationale: r }), 'Quality Control decision recorded')} /></div>)}
      {status === 'wait' && <div className="box gate"><h3>Gate · Confirm Quality Control decisions</h3>
        <p className="role-reqd">Only <RoleBadge role="analyst" /> can confirm Quality Control.</p>
        <div className="row"><button className="btn primary" onClick={() => act(() => api.gate('qc', who), 'Quality Control confirmed')}>Confirm and advance</button>
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
      <div className="metrics"><div className="metric"><span className="v">{q.length}</span><span className="l">Quality Control-passed runs</span></div>
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
      {status === 'wait' && <div className="box gate"><h3>Gate · Close profiling batch</h3>
        <p className="role-reqd">Only <RoleBadge role="analyst" /> can close the batch.</p>
        <p>Results imported later are evaluated automatically.</p>
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
    <p className="role-reqd">Only <RoleBadge role="pi" /> can release the report.</p>
    {st.gates.release && <p className="okmsg">{st.gates.release.kind === 'final' ? 'Final release' : 'Exploratory draft shared'} · v{st.gates.release.version} · {st.gates.release.person || ROLE_LABEL[st.gates.release.role]}</p>}
    {r.superseded && <p className="msg">Report superseded — click Regenerate before release.</p>}
    <p>{pending ? `${pending} finding(s) pending review: final release is blocked.` : 'No pending findings.'}</p>
    <div className="row"><button className="btn primary" disabled={!!pending || r.superseded} onClick={() => act(() => api.release({ ...who, kind: 'final' }), 'Released')}>Approve final release</button>
      <button className="btn" disabled={r.superseded} onClick={() => act(() => api.release({ ...who, kind: 'draft' }), 'Draft shared')}>Share exploratory draft</button>
      <button className="btn" onClick={() => act(() => api.run(6), 'Report regenerated')}>Regenerate report</button>
      {!r.superseded && <RawLink kind="report" k={String(r.version)} />}</div></div>
}
