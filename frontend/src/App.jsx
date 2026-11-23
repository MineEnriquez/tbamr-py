import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { ROLE_LABEL, traceKind, traceDetail } from './components/common.jsx'
import Team from './components/Team.jsx'
import Pipeline from './components/Pipeline.jsx'
import Samples, { Drawer } from './components/Samples.jsx'
import Review from './components/Review.jsx'
import Admin from './components/Admin.jsx'
import Report from './components/Report.jsx'
import Insights from './components/Insights.jsx'
import Logs from './components/Logs.jsx'
import About from './components/About.jsx'
import { RawCtx, RawViewer } from './components/Raw.jsx'
import Flow from './components/Flow.jsx'

const load = k => { try { return localStorage.getItem(k) || '' } catch { return '' } }
const save = (k, v) => { try { localStorage.setItem(k, v) } catch { /* storage unavailable */ } }

export default function App() {
  const [snap, setSnap] = useState(null)
  const [team, setTeam] = useState([])
  const [decisions, setDecisions] = useState([])
  const [metrics, setMetrics] = useState(null)
  const [tab, setTab] = useState('pipeline')
  const [view, setView] = useState(0)  // view 0 = Start hero; 1-6 = pipeline stages
  const [role, setRole] = useState(load('tbamr.role') || 'pi')
  const [person, setPerson] = useState(load('tbamr.person'))
  const [sel, setSel] = useState(null)
  const [toast, setToast] = useState(null)
  const [error, setError] = useState(null)
  const [version, setVersion] = useState(0)
  const [receipts, setReceipts] = useState({})
  const [rawReq, setRawReq] = useState(null)
  const [theme, setTheme] = useState(load('tbamr.theme') || 'light')
  const [liveTraces, setLiveTraces] = useState([])
  const [auth, setAuth] = useState(null)  // { enabled, user } from /api/auth/status
  const timer = useRef(null)
  const traceTimer = useRef(null)
  const topRef = useRef(null)
  useEffect(() => { // publish the sticky header's height so the Pipeline side column can fit the visible area below it
    const el = topRef.current
    if (!el) return
    const set = () => document.documentElement.style.setProperty('--top-h', el.offsetHeight + 'px')
    set()
    const ro = new ResizeObserver(set); ro.observe(el)
    return () => ro.disconnect()
  }, [snap === null])

  const refresh = useCallback(async () => {
    try {
      const [s, t, d, m] = await Promise.all([api.state(), api.team(), api.decisions(), api.metrics()])
      setSnap(s); setTeam(t); setDecisions(d); setMetrics(m); setError(null); setVersion(v => v + 1)
      return s
    } catch (e) { setError('Cannot reach the backend. Start it with: uvicorn tbamr.api:app --port 8000'); return null }
  }, [])

  useEffect(() => { // sign-in status first: with TBAMR_AUTH=on nothing else loads until someone signs in
    api.authStatus().then(setAuth).catch(() => setAuth({ enabled: false, user: null }))
    const out = () => setAuth(a => a && { ...a, user: null })
    window.addEventListener('tbamr:signin', out)
    return () => window.removeEventListener('tbamr:signin', out)
  }, [])
  const signedIn = !!auth && (!auth.enabled || !!auth.user)
  const myRoles = auth?.enabled ? (auth.user?.roles || []) : Object.keys(ROLE_LABEL)
  useEffect(() => { // with sign-in on you can only act in roles an admin gave you
    if (auth?.enabled && auth.user && !myRoles.includes(role)) setRole(myRoles[0] || '')
  }, [auth, role]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (signedIn) refresh() }, [refresh, signedIn])
  const loadReceipts = useCallback(() => !signedIn || !role ? Promise.resolve() : api.receipts({ role, person })
    .then(rs => setReceipts(Object.fromEntries(rs.map(r => [r.kind + '/' + r.key, r.ts])))).catch(() => {}), [role, person, signedIn])
  useEffect(() => { loadReceipts() }, [loadReceipts, version])
  const raw = { seen: (kind, key) => receipts[kind + '/' + key] || null, open: (kind, key) => setRawReq({ kind, key: String(key) }) }
  useEffect(() => { // poll while the backend is busy (e.g. TB-Profiler running)
    clearInterval(timer.current)
    if (snap?.busy) timer.current = setInterval(refresh, 1500)
    return () => clearInterval(timer.current)
  }, [snap?.busy, refresh])
  useEffect(() => { // stream the latest agent-trace entries while busy
    clearInterval(traceTimer.current)
    if (!snap?.busy) { setLiveTraces([]); return }
    const pull = () => api.trace().then(ts => setLiveTraces(ts.slice(0, 40))).catch(() => {})
    pull()
    traceTimer.current = setInterval(pull, 1200)
    return () => clearInterval(traceTimer.current)
  }, [snap?.busy])
  useEffect(() => { const k = e => e.key === 'Escape' && !rawReq && setSel(null); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [rawReq])
  useEffect(() => { save('tbamr.role', role) }, [role])
  useEffect(() => { save('tbamr.person', person) }, [person])
  useEffect(() => { // 'auto' follows the computer's light/dark setting
    if (theme === 'auto') document.documentElement.removeAttribute('data-theme')
    else document.documentElement.setAttribute('data-theme', theme)
    save('tbamr.theme', theme)
  }, [theme])
  useEffect(() => { // flag work-in-progress in the browser tab title
    document.title = snap?.busy ? `⏳ ${snap.busy} — TB-AMR Agent Team` : 'TB-AMR Agent Team'
  }, [snap?.busy])

  const flash = (text, err) => { setToast({ text, err }); setTimeout(() => setToast(null), err ? 6000 : 2500) }
  const act = async (fn, ok) => {
    // Poll aggressively WHILE the request is in-flight so the UI picks up busy=... as soon as the backend sets it,
    // not only after the slow /stages/N/run call returns.
    const p = fn()
    let polling = true
    ;(async () => { while (polling) { await refresh(); await new Promise(r => setTimeout(r, 700)) } })()
    try { await p; flash(ok) } catch (e) { flash(e.message, true) }
    polling = false
    const s = await refresh()
    if (s) { // follow the pipeline to the first stage that needs attention
      const next = Object.entries(s.state.stage_status).find(([, v]) => v === 'wait' || v === 'ready')
      if (next && Number(next[0]) > view) setView(Number(next[0]))
    }
  }
  const who = { role, person: auth?.enabled ? (auth.user?.name || '') : person }
  const signOut = () => api.logout().catch(() => {}).then(() => { setAuth(a => ({ ...a, user: null })); setSnap(null) })

  if (!auth) return <div className="wrap"><p className="muted">Loading…</p></div>
  if (!signedIn) return <SignIn onDone={user => setAuth({ enabled: true, user })} />
  if (error && !snap) return <div className="wrap"><h1>TB-AMR Agent Team</h1><div className="box esc"><p>{error}</p></div></div>
  if (!snap) return <div className="wrap"><p className="muted">Loading…</p></div>
  const st = snap.state
  const pending = st.samples.flatMap(s => s.findings).filter(f => f.review === 'Pending').length
  const tabs = [['pipeline', 'Pipeline'], ['review', 'Review queue'], ['samples', 'Samples'], ['report', 'Report'], ['team', 'Agent team'], ['insights', 'Decisions & metrics'], ['logs', 'Logs'], ['admin', 'Admin'], ['about', 'About']]

  return (
    <RawCtx.Provider value={raw}>
    {/* On the Pipeline tab the progress log sits in the side column; elsewhere a slim one-line bar */}
    {snap.busy && tab !== 'pipeline' && <BusyBar busy={snap.busy} traces={liveTraces} />}
    <div className={'wrap' + (snap.mode.data === 'demo' ? ' demo-mode' : '') + (snap.mode.brain === 'replay' ? ' replay-mode' : '')}>
      <div className="top" ref={topRef}>
        <div><h1>TB-AMR Agent Team</h1>
          <p className="muted" style={{ fontSize: '.85rem' }}>
            <a href="#about" onClick={e => { e.preventDefault(); setTab('about') }}>What is this?</a>
          </p></div>
        <div className="controls">
          <div className="ctl"><label htmlFor="role">Acting as</label>
            {myRoles.length
              ? <select id="role" value={role} onChange={e => setRole(e.target.value)}>{myRoles.map(k => <option key={k} value={k}>{ROLE_LABEL[k]}</option>)}</select>
              : <span className="muted" id="role" style={{ fontSize: '.85rem' }}>No roles yet: ask an admin</span>}</div>
          {auth.enabled
            ? <div className="ctl"><span className="lbl">Signed in</span><span className="row" style={{ gap: 6 }}><b>{auth.user.name}</b>{auth.user.admin && <span className="tag">admin</span>}<button className="btn small ghost" onClick={signOut}>Sign out</button></span></div>
            : <div className="ctl"><label htmlFor="person">Your name</label><input id="person" value={person} onChange={e => setPerson(e.target.value)} placeholder="e.g. Minnie" /></div>}
          <div className="ctl"><span className="lbl" id="theme-l">Colors</span>
            <div className="seg theme" role="radiogroup" aria-labelledby="theme-l">{[['light', '☀ Light'], ['dark', '☾ Dark'], ['auto', 'Auto']].map(([k, l]) =>
              <button key={k} role="radio" aria-checked={theme === k} aria-selected={theme === k} title={k === 'auto' ? "Follow this computer's setting" : undefined} onClick={() => setTheme(k)}>{l}</button>)}</div></div>
          <button className="btn ghost" onClick={() => act(() => api.reset(snap.mode.data), 'Pipeline reset')}>Reset</button>
        </div>
      </div>
      <div className="banner">
        <ModeSwitch mode={snap.mode.data} busy={!!snap.busy} onSwitch={next => {
          if (confirm(`Switch data mode to ${next.toUpperCase()}? This resets the pipeline (previous decisions stay in the log).`)) {
            act(() => api.reset(next), `Switched to ${next} mode`)
          }
        }} />
        {!auth.enabled && <span className="tag unverified" title="Anyone can pick any role and type any name. Start the backend with TBAMR_AUTH=on to require sign-in.">Sign-in off · identities are not verified</span>}
        <span className={'tag ' + snap.mode.brain}>{snap.mode.brain === 'claude' ? 'Claude agents (live reasoning)' : 'Replay agents (scripted, no API key)'}</span>
      </div>
      <Flow snap={snap} team={team} view={tab === 'pipeline' ? view : null} pending={pending} onPick={n => { setView(n); setTab(n === 5 && pending ? 'review' : 'pipeline') }} onReport={() => setTab('report')} />
      <nav className="tabs" role="tablist">{tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}{k === 'review' && pending ? <span className="count">{pending}</span> : null}</button>)}</nav>
      <main>
        {tab === 'team' && <Team team={team} version={version} />}
        {tab === 'pipeline' && <Pipeline snap={snap} decisions={decisions} traces={liveTraces} view={view} setView={setView} act={act} who={who} busy={snap.busy} openSample={setSel} />}
        {tab === 'samples' && <Samples st={st} openSample={setSel} />}
        {tab === 'review' && <Review st={st} act={act} who={who} openSample={setSel} />}
        {tab === 'report' && <Report st={st} act={act} brain={snap.mode.brain} who={who} />}
        {tab === 'insights' && <Insights m={metrics} decisions={decisions} />}
        {tab === 'logs' && <Logs version={version} />}
        {tab === 'admin' && <Admin who={who} auth={auth} />}
        {tab === 'about' && <About />}
      </main>
      {sel && <Drawer run={sel} st={st} pending={snap.pending_overrides} act={act} who={who} close={() => setSel(null)} version={version} />}
      {rawReq && <RawViewer key={rawReq.kind + rawReq.key} req={rawReq} who={who} onClose={() => setRawReq(null)} onViewed={loadReceipts} />}
      {toast && <div className={'toast' + (toast.err ? ' err' : '')} role="status">{toast.text}</div>}
      <footer>{snap.mode.data === 'demo' ? 'Demo data: every accession starting DEMO/PRJDEMO is simulated.' : 'Live data from the ENA Portal API.'} <a href="#about" onClick={e => { e.preventDefault(); setTab('about') }}>About</a></footer>
    </div>
    </RawCtx.Provider>
  )
}

/* Sign-in screen, shown only when the backend runs with TBAMR_AUTH=on and there is no session. */
function SignIn({ onDone }) {
  const [name, setName] = useState('')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async e => {
    e.preventDefault(); setBusy(true); setErr('')
    try { onDone((await api.login(name, pw)).user) } catch (x) { setErr(x.message); setPw('') }
    setBusy(false)
  }
  return (
    <div className="wrap"><form className="panel signin" onSubmit={submit} aria-labelledby="signin-h">
      <h1 id="signin-h">TB-AMR Agent Team</h1>
      <p className="muted">Sign in. Every decision you make is recorded under your name, in the roles an admin has assigned you.</p>
      <div className="ctl"><label htmlFor="si-name">Name</label><input id="si-name" autoComplete="username" value={name} onChange={e => setName(e.target.value)} autoFocus required /></div>
      <div className="ctl"><label htmlFor="si-pw">Password</label><input id="si-pw" type="password" autoComplete="current-password" value={pw} onChange={e => setPw(e.target.value)} required /></div>
      {err && <div className="box esc" role="alert">{err}</div>}
      <button className="btn primary" disabled={busy || !name || !pw}>{busy ? 'Signing in…' : 'Sign in'}</button>
      <p className="muted" style={{ fontSize: '.8rem' }}>No account? An admin creates them on the Admin page, or from the server: <code>python -m tbamr.users create-admin &lt;name&gt;</code></p>
    </form></div>
  )
}

/* Data-mode picker: both options are always visible, the active one is highlighted.
 * Choosing the other option resets the pipeline.
 * Live mode talks to the real ENA Portal API; demo mode runs offline against simulated
 * DEMO/PRJDEMO accessions. */
const DATA_MODES = [
  ['demo', 'Demo', 'Simulated DEMO/PRJDEMO accessions, works offline'],
  ['live', 'Live · ENA', 'Real data from the ENA Portal API (needs internet)'],
]
function ModeSwitch({ mode, busy, onSwitch }) {
  return (
    <div className="mode-pick">
      <span className="lbl" id="data-l">Data</span>
      <div className={'seg data ' + mode} role="radiogroup" aria-labelledby="data-l">{DATA_MODES.map(([k, l, d]) =>
        <button key={k} type="button" role="radio" aria-checked={mode === k} aria-selected={mode === k} disabled={busy}
          title={mode === k ? `${d} (current)` : `${d}. Switching resets the pipeline.`}
          onClick={() => mode !== k && onSwitch(k)}>{l}</button>)}</div>
    </div>
  )
}

function BusyBar({ busy, traces }) {
  const latest = traces[0]
  return (
    <div className="running" role="status" aria-live="polite" aria-label={`Working: ${busy}`}>
      <span className="runbar" aria-hidden="true" />
      <div className="runrow">
        <span className="rundot" aria-hidden="true" />
        <span>Working on <b>{busy}</b>…</span>
        {latest && <span className="runsub">· {latest.agent?.replace(/_/g, ' ')} <code>{traceKind(latest)}</code> {traceDetail(latest)}</span>}
      </div>
    </div>
  )
}
