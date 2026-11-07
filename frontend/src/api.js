async function call(method, path, body, params) {
  const url = '/api' + path + (params ? '?' + new URLSearchParams(params) : '')
  const opts = { method, headers: {} }
  if (body instanceof FormData) opts.body = body
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json' }
  const r = await fetch(url, opts)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail || `Request failed (${r.status})`)
  return data
}
export const api = {
  state: () => call('GET', '/state'),
  team: () => call('GET', '/team'),
  decisions: (sample) => call('GET', '/decisions', undefined, sample ? { sample } : undefined),
  trace: (agent) => call('GET', '/trace', undefined, agent ? { agent, limit: 200 } : { limit: 200 }),
  metrics: () => call('GET', '/metrics'),
  raw: (kind, key, who) => call('GET', `/raw/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`, undefined, who),
  receipts: (who) => call('GET', '/raw/receipts', undefined, who),
  setScope: (s) => call('POST', '/scope', s),
  geoCountries: () => call('GET', '/geo/countries'),
  geoRegions: (country) => call('GET', '/geo/regions', undefined, { country }),
  scopeTarget: (question, country, region) => call('GET', '/scope/target', undefined, { question, country, region }),
  reopenScope: () => call('POST', '/scope/reopen'),
  run: (n) => call('POST', `/stages/${n}/run`),
  gate: (name, who) => call('POST', `/gates/${name}`, who),
  resolveHold: (b) => call('POST', '/holds/resolve', b),
  resolveQc: (b) => call('POST', '/qc/resolve', b),
  review: (b) => call('POST', '/review', b),
  override: (b) => call('POST', '/overrides', b),
  cosign: (b) => call('POST', '/overrides/cosign', b),
  release: (b) => call('POST', '/release', b),
  summary: () => call('POST', '/report/summary'),
  saveSummary: (text) => call('PUT', '/report/summary', { text }),
  executions: (limit = 100, runId) => call('GET', '/executions', undefined,
    runId != null ? { limit, run_id: runId } : { limit }),
  execution: (id) => call('GET', '/executions/' + id),
  runs: () => call('GET', '/runs'),
  importFiles: (who, files) => { const fd = new FormData(); [...files].forEach(f => fd.append('files', f)); return call('POST', '/profiling/import', fd, who) },
  runProfiler: (b) => call('POST', '/profiling/run', b),
  reset: (data) => call('POST', '/reset', undefined, { data }),
  // Admin: Mongo health, cache per-namespace toggle/clear, pipeline-result archive.
  adminMongo: () => call('GET', '/admin/mongo'),
  adminMongoReconnect: () => call('POST', '/admin/mongo/reconnect'),
  adminCache: () => call('GET', '/admin/cache'),
  adminCacheToggle: (ns, enabled) => call('POST', `/admin/cache/${ns}/toggle`, { enabled }),
  adminCacheClear: (ns) => call('POST', `/admin/cache/${ns}/clear`),
  adminCacheClearAll: () => call('POST', '/admin/cache/clear-all'),
  adminResults: (limit = 50) => call('GET', '/admin/results', undefined, { limit }),
  adminResult: (id) => call('GET', '/admin/results/' + id),
}
