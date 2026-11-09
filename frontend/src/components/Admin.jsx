import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { Chip } from './common.jsx'

/* Admin page — Mongo health, cache per-namespace toggles + stats + clear, and the pipeline-result
 * archive. Everything degrades gracefully: if Mongo is down the page still renders with a clear
 * banner, the toggles stay interactive (persist in memory + attempt to re-write on reconnect), and
 * the archive table shows "no releases archived yet". */

const NS_LABEL = {
  ena: 'ENA Portal API',
  pmc: 'Europe PMC',
  tbprofiler: 'TB-Profiler results',
  claude: 'Claude agent responses',
}

const NS_HINT = {
  ena: 'Discovery + verification + file-report calls. Keyed by (method, country, query, limit).',
  pmc: 'Linked-publication lookups. Keyed by (query, limit).',
  tbprofiler: 'Per-run profiler outputs. Keyed by run accession. Only successful runs are cached.',
  claude: 'Agent reasoning + plain-language summaries. Keyed by (model, system, messages, tools). Turn off for fresh runs.',
}

export default function Admin({ who }) {
  const [mongo, setMongo] = useState(null)
  const [caches, setCaches] = useState([])
  const [releases, setReleases] = useState([])
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const [cv, rl] = await Promise.all([api.adminCache(), api.adminResults(50)])
      setMongo(cv.mongo); setCaches(cv.caches); setReleases(rl)
    } catch (e) { setMsg({ err: true, text: e.message }) }
  }, [])
  useEffect(() => { refresh() }, [refresh])

  const flash = (text, err) => { setMsg({ err: !!err, text }); setTimeout(() => setMsg(null), 2500) }
  const guard = async (label, fn) => {
    setBusy(label)
    try { await fn(); flash(`${label} done`) } catch (e) { flash(e.message, true) }
    setBusy('')
    refresh()
  }

  return (<>
    <RulesAdmin who={who} />
    <section className="panel">
      <div className="row between"><div><span className="eyebrow">Admin</span><h2>Storage & cache</h2></div>
        <button className="btn ghost" disabled={!!busy} onClick={() => guard('Refresh', refresh)}>↻ Refresh</button>
      </div>

      {mongo == null ? (
        <div className="box note"><p className="muted">Loading Mongo status…</p></div>
      ) : (
        <div className={'box ' + (mongo.connected ? 'note' : 'esc')}>
          <div className="row between" style={{ alignItems: 'baseline' }}>
            <div>
              <h3>MongoDB · {mongo.connected ? <Chip label="Connected" kind="Proceed" /> : <Chip label="Not reachable" kind="Escalate" />}</h3>
              <p className="muted" style={{ margin: 0, fontSize: '.86rem' }}>
                <span className="mono">{mongo.url || 'mongodb://localhost:27017'}</span> · database <span className="mono">{mongo.db || 'tbamr'}</span>
              </p>
            </div>
            <button className="btn small" disabled={!!busy} onClick={() => guard('Reconnect', () => api.adminMongoReconnect().then(setMongo))}>Reconnect</button>
          </div>
          {!mongo.connected && (
            <p style={{ fontSize: '.86rem', margin: '8px 0 0' }}>
              Start it with <span className="mono">docker compose up -d mongo</span>. Everything below still works
              with Mongo down — caches become no-ops and the pipeline-result archive is skipped.
            </p>
          )}
          {mongo.last_error && !mongo.connected && <pre className="mono box" style={{ fontSize: '.78rem', padding: 8, margin: '8px 0 0', whiteSpace: 'pre-wrap' }}>{mongo.last_error}</pre>}
        </div>
      )}

      <div><div className="row between"><h3>Caches</h3>
        <button className="btn small ghost" disabled={!!busy} onClick={() => guard('Clear all caches', () => api.adminCacheClearAll())}>Clear ALL caches</button>
      </div>
      <div className="tw"><table>
        <thead><tr><th>Source</th><th>Enabled</th><th className="num">Entries</th><th className="num">Hits</th><th className="num">Misses</th><th className="num">Hit rate</th><th>Action</th></tr></thead>
        <tbody>{caches.map(c => {
          const total = c.hits + c.misses
          const rate = total ? Math.round(100 * c.hits / total) + '%' : '—'
          return (
            <tr key={c.namespace}>
              <td><b>{NS_LABEL[c.namespace] || c.namespace}</b><div className="muted" style={{ fontSize: '.78rem', marginTop: 2 }}>{NS_HINT[c.namespace]}</div></td>
              <td><label className="switch-small"><input type="checkbox" checked={!!c.enabled} disabled={!!busy}
                onChange={e => guard(`Toggle ${c.namespace}`, () => api.adminCacheToggle(c.namespace, e.target.checked))} />
                <span>{c.enabled ? 'On' : 'Off'}</span></label></td>
              <td className="num mono">{c.entries == null ? '—' : c.entries}</td>
              <td className="num mono">{c.hits}</td>
              <td className="num mono">{c.misses}</td>
              <td className="num mono">{rate}</td>
              <td><button className="btn small ghost" disabled={!!busy} onClick={() => guard(`Clear ${c.namespace}`, () => api.adminCacheClear(c.namespace))}>Clear</button></td>
            </tr>
          )
        })}</tbody>
      </table></div></div>

      <div><h3>Pipeline result archive</h3>
        <p className="muted" style={{ marginTop: 0, fontSize: '.86rem' }}>Every release (final or draft) is archived here as a document. The SQLite decision log remains the authoritative audit trail; this is a cross-run, query-friendly mirror of the final report.</p>
        {!releases.length && <p className="muted">No releases archived yet{mongo?.connected ? '.' : ' (Mongo not reachable).'}</p>}
        {releases.length > 0 && <div className="tw"><table>
          <thead><tr><th>Released</th><th>Version</th><th>Kind</th><th>By</th><th>Country</th><th className="num">Analysed</th><th>Drugs</th></tr></thead>
          <tbody>{releases.map(r => (
            <tr key={r._id}>
              <td style={{ fontSize: '.82rem' }}>{new Date((r.released_at || 0) * 1000).toLocaleString()}</td>
              <td className="mono">v{r.version}</td>
              <td><Chip label={r.kind || 'draft'} kind={r.kind === 'final' ? 'Proceed' : 'Pending'} /></td>
              <td>{r.released_by?.person || r.released_by?.role || '—'}</td>
              <td>{r.country || '—'}</td>
              <td className="num mono">{r.report?.counts?.analysed ?? '—'}</td>
              <td style={{ fontSize: '.82rem' }}>{(r.target_drugs || []).join(', ')}</td>
            </tr>
          ))}</tbody>
        </table></div>}
      </div>

      {msg && <div className={'toast' + (msg.err ? ' err' : '')} role="status">{msg.text}</div>}
    </section>
  </>)
}

/* Pipeline rules: the thresholds the deterministic agents apply. Only the PI can change them; each change
 * needs a rationale, bumps the rule-set version (e.g. QC-v1.0 -> QC-v1.1), is logged as a decision and marks
 * an existing report superseded. Each rule set also records whether it is provisional or validated. */
const RULE_NAME = { qc: 'QC coverage gate (Stage 3)', evid: 'Evidence classification (Stage 5)' }
function RulesAdmin({ who }) {
  const [cur, setCur] = useState(null)
  const [vals, setVals] = useState({})
  const [status, setStatus] = useState({})
  const [basis, setBasis] = useState({})
  const [why, setWhy] = useState('')
  const [msg, setMsg] = useState(null)
  const load = useCallback(() => api.adminRules().then(r => {
    setCur(r); setVals(Object.fromEntries(Object.keys(r.editable).map(k => [k, String(r.thresholds[k])])))
    setStatus(Object.fromEntries(Object.entries(r.meta).map(([k, m]) => [k, m.status])))
    setBasis(Object.fromEntries(Object.entries(r.meta).map(([k, m]) => [k, m.basis])))
  }).catch(e => setMsg({ err: true, text: e.message })), [])
  useEffect(() => { load() }, [load])
  if (!cur) return <div className="panel"><p className="muted">Loading pipeline rules…</p></div>
  const isPI = who?.role === 'pi'
  const changes = Object.fromEntries(Object.entries(vals).filter(([k, v]) => v !== '' && Number(v) !== cur.thresholds[k]).map(([k, v]) => [k, Number(v)]))
  const stChanges = Object.fromEntries(Object.entries(status).filter(([k, v]) => v !== cur.meta[k].status))
  const bChanges = Object.fromEntries(Object.entries(basis).filter(([k, v]) => v.trim() && v.trim() !== cur.meta[k].basis))
  const dirty = Object.keys(changes).length || Object.keys(stChanges).length || Object.keys(bChanges).length
  const save = () => api.adminRulesChange({ ...who, changes, rationale: why, status: stChanges, basis: bChanges })
    .then(r => { setMsg({ text: `Saved. ${Object.entries(r.versions).map(([k, v]) => `${k.toUpperCase()} ${v.from} → ${v.to}`).join(', ')}` }); setWhy(''); load() })
    .catch(e => setMsg({ err: true, text: e.message }))
  const byRule = Object.entries(cur.editable).reduce((m, [k, spec]) => { (m[spec.rule] = m[spec.rule] || []).push([k, spec]); return m }, {})
  return (
    <div className="panel rules-admin">
      <div className="row between"><div><span className="eyebrow">Admin</span><h2>Pipeline rules</h2></div></div>
      <p className="muted" style={{ fontSize: '.88rem', margin: 0 }}>The thresholds the deterministic agents apply. Changes take effect for stages run afterwards; stages already run keep the results and rule version they were decided with, and an existing report is marked superseded. {isPI ? '' : <b>Only the Principal Investigator can change these (you are acting as {who?.role}).</b>}</p>
      {Object.entries(byRule).map(([rule, items]) => (
        <div key={rule} className="box rule-set">
          <div className="row between" style={{ flexWrap: 'wrap', gap: 8 }}>
            <h3 style={{ margin: 0 }}>{RULE_NAME[rule] || rule} · <span className="mono">{cur.rules[rule]}</span></h3>
            <span className={'rule-status ' + cur.meta[rule].status}>{cur.meta[rule].status === 'validated' ? 'Validated' : 'Provisional: not benchmarked'}</span>
          </div>
          <table><thead><tr><th>Setting</th><th className="num">Current</th><th className="num">Default</th><th>New value</th></tr></thead><tbody>
            {items.map(([k, spec]) => <tr key={k}>
              <td>{spec.label}<div className="muted" style={{ fontSize: '.8rem' }}>{spec.help}</div></td>
              <td className="num mono">{cur.thresholds[k]} {spec.unit === '×' ? '×' : spec.unit === 'fraction' ? '' : spec.unit}</td>
              <td className="num mono muted">{cur.defaults[k]}</td>
              <td><input type="number" step={spec.type === 'int' ? 1 : spec.unit === 'fraction' ? 0.01 : 0.5} min={spec.min} max={spec.max} value={vals[k] ?? ''} disabled={!isPI}
                onChange={e => setVals(v => ({ ...v, [k]: e.target.value }))} aria-label={`New value for ${spec.label}`} style={{ width: 110 }} /></td></tr>)}
          </tbody></table>
          <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div className="ctl"><label htmlFor={`st-${rule}`}>Status</label>
              <select id={`st-${rule}`} value={status[rule]} disabled={!isPI} onChange={e => setStatus(s => ({ ...s, [rule]: e.target.value }))}>
                <option value="provisional">Provisional (not benchmarked)</option><option value="validated">Validated</option></select></div>
            <div className="ctl" style={{ flex: 1, minWidth: 320 }}><label htmlFor={`basis-${rule}`}>Basis (benchmark, data, date)</label>
              <input id={`basis-${rule}`} value={basis[rule] || ''} disabled={!isPI} onChange={e => setBasis(b => ({ ...b, [rule]: e.target.value }))} /></div>
          </div>
        </div>
      ))}
      <p className="muted" style={{ fontSize: '.82rem', margin: 0 }}>Read-only: genome length {cur.thresholds.genome_bp?.toLocaleString()} bp. {cur.read_only.genome_bp}</p>
      <div className="ctl"><label htmlFor="rules-why">Rationale (required; recorded with the new version)</label>
        <textarea id="rules-why" value={why} disabled={!isPI} onChange={e => setWhy(e.target.value)} placeholder="e.g. Aligning with the 2026 CRyPTIC benchmark: 25× retains 4% more isolates with unchanged concordance." /></div>
      <div className="row" style={{ gap: 8 }}><button className="btn primary" disabled={!isPI || !dirty || !why.trim()} onClick={save}>Save new rule version</button>
        {msg && <span className={msg.err ? 'msg' : 'okmsg'} role="status">{msg.text}</span>}</div>
      {cur.history.length > 0 && <div><h3>Change history</h3><ul className="clean rule-history">{cur.history.map((h, i) => <li key={i}>
        <span className="mono">{new Date(h.ts * 1000).toLocaleString()}</span> · <b>{h.person}</b> · {Object.entries(h.versions).map(([r, v]) => `${v.from} → ${v.to}`).join(', ')}
        {Object.keys(h.changes).length > 0 && <> · {Object.entries(h.changes).map(([k, v]) => `${k} ${v.from} → ${v.to}`).join(', ')}</>}
        {Object.keys(h.meta || {}).length > 0 && <> · {Object.entries(h.meta).map(([r, m]) => `${r}: ${Object.values(m).join(', ')}`).join('; ')}</>}
        <div className="muted">{h.rationale}</div></li>)}</ul></div>}
    </div>
  )
}
