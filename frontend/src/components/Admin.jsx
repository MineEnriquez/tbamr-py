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

export default function Admin() {
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

  return (
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
  )
}
