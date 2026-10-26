import React, { createContext, useContext, useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtTime } from './common.jsx'

/* Raw data before every decision.
   - useRaw() gives every component: seen(kind, key) → timestamp | null, and open(kind, key).
   - <RawCheck> is the visual step "1. look at the raw data" shown above every decision button.
   - Decision buttons stay disabled until the current person has opened that raw data. */

export const RawCtx = createContext({ seen: () => null, open: () => {} })
export const useRaw = () => useContext(RawCtx)

export function RawCheck({ kind, k, what }) {
  const { seen, open } = useRaw()
  const ts = seen(kind, k)
  return ts
    ? <div className="rawcheck ok"><span>✓ Raw data reviewed at {fmtTime(ts)}</span><button className="btn small ghost" onClick={() => open(kind, k)}>View again</button></div>
    : <div className="rawcheck todo"><span><b>Step 1:</b> look at the raw data for {what}. The decision buttons unlock after you open it.</span>
      <button className="btn small primary" onClick={() => open(kind, k)}>View raw data</button></div>
}

export function RawLink({ kind, k, label = 'View raw data' }) {
  const { open } = useRaw()
  return <button className="btn small ghost" onClick={e => { e.stopPropagation(); open(kind, k) }}>{label}</button>
}

// Clicking a run in a raw table drills down to that run's own raw record
const DRILL = { cohort: 'ena', qc: 'ena', profiling: 'tbprofiler' }

export function RawViewer({ req, who, onClose, onViewed }) {
  const [stack, setStack] = useState([req])
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [mode, setMode] = useState('table')
  const cur = stack[stack.length - 1]
  useEffect(() => {
    let live = true
    setData(null); setErr(null)
    api.raw(cur.kind, cur.key, who).then(d => { if (!live) return; setData(d); setMode(d.table ? 'table' : 'json'); onViewed() })
      .catch(e => live && setErr(e.message))
    return () => { live = false }
  }, [cur.kind, cur.key])
  useEffect(() => { const k = e => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [onClose])

  const download = () => {
    const blob = new Blob([JSON.stringify(data.data, null, 2)], { type: 'application/json' })
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `raw-${cur.kind}-${cur.key}.json`; a.click(); URL.revokeObjectURL(a.href)
  }
  const drill = DRILL[cur.kind]
  return (
    <>
      <div className="scrim" style={{ zIndex: 30 }} onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-label="Raw data">
        <div className="row between">
          <div style={{ minWidth: 0 }}>
            {stack.length > 1 && <button className="btn small ghost" onClick={() => setStack(stack.slice(0, -1))}>← Back</button>}
            <span className="eyebrow">Raw data · {cur.kind}/{cur.key}</span><h2>{data?.title || 'Loading…'}</h2></div>
          <button className="btn small" onClick={onClose}>Close</button>
        </div>
        {err && <div className="box esc"><p>{err}</p></div>}
        {data && <>
          <dl className="kv"><dt>Source</dt><dd>{data.source}</dd><dt>What this is</dt><dd>{data.explanation}</dd>
            {data.viewed_at && <><dt>Your receipt</dt><dd>Viewed by <b>{data.viewer}</b> at {fmtTime(data.viewed_at)}; this is saved with your decision.</dd></>}</dl>
          <div className="row">
            {data.table && <div className="seg" role="tablist"><button aria-selected={mode === 'table'} onClick={() => setMode('table')}>Table</button><button aria-selected={mode === 'json'} onClick={() => setMode('json')}>Full JSON</button></div>}
            <button className="btn small" onClick={download}>Download JSON</button>
            {drill && mode === 'table' && <span className="muted" style={{ fontSize: '.82rem' }}>Click a run to open its own record.</span>}
          </div>
          {mode === 'table' && data.table
            ? <div className="tw rawtable"><table><thead><tr>{data.table.columns.map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>
              {data.table.rows.map((r, i) => <tr key={i} className={drill ? 'click' : ''} onClick={() => drill && r[0] && setStack([...stack, { kind: drill, key: r[0] }])}>
                {r.map((v, j) => <td key={j} className="mono">{v === null || v === undefined || v === '' ? '—' : String(v)}</td>)}</tr>)}
              {!data.table.rows.length && <tr><td colSpan={data.table.columns.length} className="muted">No rows.</td></tr>}</tbody></table></div>
            : <pre className="rawjson">{JSON.stringify(data.data, null, 2)}</pre>}
        </>}
      </div>
    </>
  )
}
