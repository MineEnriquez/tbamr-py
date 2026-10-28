import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { fmtTime } from './common.jsx'

/* Embedded log viewer: one entry per discrete action triggered by the user (stage run, gate
   approval, hold resolution, TB-Profiler batch, ...). Each entry stores the stdout/stderr/log
   output captured while that action was running — scoped, not a continuous live tail.

   Executions are grouped by "pipeline run" — a cycle from fresh state through to the next Reset.
   The current run is live; previous runs are closed and remain selectable so you can look back
   at logs from before the last reset. */

const STATUS = { ok: 'OK', error: 'Error', running: 'Running…' }

function dur(a, b) {
  const d = Math.max(0, (b || Date.now() / 1000) - a)
  if (d < 1) return `${Math.round(d * 1000)}ms`
  if (d < 60) return `${d.toFixed(1)}s`
  const m = Math.floor(d / 60), s = Math.round(d % 60)
  return `${m}m ${s}s`
}

function runLabel(r) {
  if (!r) return ''
  const base = r.label && r.label.trim() ? r.label : (r.started_at ? fmtTime(r.started_at) : `Run #${r.id}`)
  return r.active ? `${base} · current` : base
}

function LogView({ text, errorsOnly }) {
  const lines = (text || '').split('\n')
  const shown = errorsOnly ? lines.filter(l => / ERROR | CRITICAL |^Traceback|^  File |^  \S/.test(l)) : lines
  return (
    <pre className="log-view">{shown.map((l, i) => {
      const m = l.match(/^(\d\d:\d\d:\d\d)\s+(\w+)\s+/)
      const lvl = m ? m[2] : ''
      const traceback = l.startsWith('Traceback') || l.startsWith('  File ') || /^\s+\^+$/.test(l)
      const cls = traceback ? 'll-trace' : (lvl ? 'll-' + lvl : '')
      return <div key={i} className={'ll ' + cls}>
        {m ? <><span className="ll-ts">{m[1]}</span> <span className="ll-lvl">{m[2]}</span> {l.slice(m[0].length)}</> : l || '\u00A0'}
      </div>
    })}</pre>
  )
}

export default function Logs({ version }) {
  const [items, setItems] = useState([])
  const [runs, setRuns] = useState([])
  const [runId, setRunId] = useState(null)  // null = active run
  const [sel, setSel] = useState(null)
  const [detail, setDetail] = useState(null)
  const [errorsOnly, setErrorsOnly] = useState(false)
  const [autoPick, setAutoPick] = useState(true)
  const activeRunId = useMemo(() => (runs.find(r => r.active) || {}).id ?? null, [runs])
  const effectiveRunId = runId ?? activeRunId
  const selectedRun = useMemo(() => runs.find(r => r.id === effectiveRunId) || null, [runs, effectiveRunId])
  const isActive = !selectedRun || selectedRun.active
  const pullRuns = useCallback(() => api.runs().then(setRuns).catch(() => {}), [])
  const pull = useCallback(() => api.executions(200, effectiveRunId == null ? undefined : effectiveRunId).then(d => {
    setItems(d)
    if (autoPick && d.length && (sel == null || !d.some(x => x.id === sel))) setSel(d[0].id)
  }).catch(() => {}), [autoPick, sel, effectiveRunId])
  useEffect(() => { pullRuns() }, [pullRuns, version])
  useEffect(() => { pull() }, [pull, version])
  useEffect(() => {
    if (sel == null) { setDetail(null); return }
    api.execution(sel).then(setDetail).catch(() => setDetail(null))
  }, [sel])
  // Live refresh while an execution is still running (only meaningful on the active run)
  useEffect(() => {
    if (!isActive) return
    const anyRunning = items.some(x => !x.end_ts)
    if (!anyRunning) return
    const t = setInterval(() => { pull(); pullRuns() }, 1500)
    return () => clearInterval(t)
  }, [items, pull, pullRuns, isActive])

  return (
    <div className="logs">
      <aside className="logs-list">
        <div className="row between" style={{ padding: '4px 10px' }}>
          <h3 style={{ fontSize: '.95rem' }}>Executions</h3>
          <button className="btn small ghost" onClick={() => { pullRuns(); pull() }}>Refresh</button>
        </div>
        {runs.length > 0 && (
          <div className="row" style={{ padding: '0 10px 6px', fontSize: '.8rem', gap: 6 }}>
            <label htmlFor="logs-run" className="muted">Pipeline run</label>
            <select id="logs-run" value={runId == null ? '' : String(runId)}
                    onChange={e => { setRunId(e.target.value ? Number(e.target.value) : null); setSel(null); setAutoPick(true) }}
                    style={{ flex: 1, minWidth: 0 }}>
              <option value="">Current run</option>
              {runs.filter(r => !r.active).map(r => (
                <option key={r.id} value={r.id}>{runLabel(r)}{r.n_executions ? ` · ${r.n_executions}` : ''}</option>
              ))}
            </select>
          </div>
        )}
        {selectedRun && !selectedRun.active && (
          <p className="muted" style={{ padding: '0 10px 6px', fontSize: '.75rem' }}>
            Closed {selectedRun.ended_at ? fmtTime(selectedRun.ended_at) : ''} · read-only snapshot of a previous pipeline run.
          </p>
        )}
        <div className="row" style={{ padding: '0 10px 8px', fontSize: '.78rem' }}>
          <label><input type="checkbox" checked={autoPick} onChange={e => setAutoPick(e.target.checked)} /> auto-select newest</label>
        </div>
        {!items.length && <p className="muted" style={{ padding: '0 10px' }}>Nothing recorded in this run yet. Trigger a stage run or any other action to see captured logs.</p>}
        <ul className="logs-items">
          {items.map(x => {
            const status = x.end_ts ? x.status : 'running'
            return (
              <li key={x.id} className={'logs-item st-' + status + (sel === x.id ? ' sel' : '')} onClick={() => { setSel(x.id); setAutoPick(false) }}>
                <div className="row between" style={{ gap: 6 }}>
                  <span className="logs-trigger">{x.trigger}</span>
                  <span className={'logs-status st-' + status}>{STATUS[status] || status}</span>
                </div>
                <div className="logs-meta">
                  <span>{x.start_ts ? fmtTime(x.start_ts) : '—'}</span>
                  <span>· {dur(x.start_ts, x.end_ts)}</span>
                  <span>· {x.log_bytes ? `${x.log_bytes.toLocaleString()} B` : '0 B'}</span>
                </div>
                {x.error && <div className="logs-err">{x.error}</div>}
              </li>
            )
          })}
        </ul>
      </aside>
      <section className="logs-detail">
        {!detail && <p className="muted">Pick an execution on the left.</p>}
        {detail && <>
          <div className="row between">
            <div><span className="eyebrow">Execution #{detail.id} · {detail.status.toUpperCase()}</span>
              <h3 style={{ fontSize: '1rem' }}>{detail.trigger}</h3>
              <p className="muted" style={{ fontSize: '.82rem' }}>Started {fmtTime(detail.start_ts)} · duration {dur(detail.start_ts, detail.end_ts)}{detail.error ? ` · ${detail.error}` : ''}</p>
            </div>
            <label style={{ fontSize: '.82rem' }}><input type="checkbox" checked={errorsOnly} onChange={e => setErrorsOnly(e.target.checked)} /> errors only</label>
          </div>
          <LogView text={detail.log_text} errorsOnly={errorsOnly} />
        </>}
      </section>
    </div>
  )
}
