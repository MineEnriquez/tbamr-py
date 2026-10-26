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
  setScope: (s) => call('POST', '/scope', s),
  run: (n) => call('POST', `/stages/${n}/run`),
  gate: (name, who) => call('POST', `/gates/${name}`, who),
  resolveHold: (b) => call('POST', '/holds/resolve', b),
  resolveQc: (b) => call('POST', '/qc/resolve', b),
  review: (b) => call('POST', '/review', b),
  override: (b) => call('POST', '/overrides', b),
  cosign: (b) => call('POST', '/overrides/cosign', b),
  release: (b) => call('POST', '/release', b),
  summary: () => call('POST', '/report/summary'),
  importFiles: (who, files) => { const fd = new FormData(); [...files].forEach(f => fd.append('files', f)); return call('POST', '/profiling/import', fd, who) },
  runProfiler: (b) => call('POST', '/profiling/run', b),
  reset: (data) => call('POST', '/reset', undefined, { data }),
}
