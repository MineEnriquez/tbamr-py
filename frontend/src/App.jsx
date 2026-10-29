import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { ROLE_LABEL } from './components/common.jsx'
import Team from './components/Team.jsx'
import Pipeline from './components/Pipeline.jsx'
import Samples, { Drawer } from './components/Samples.jsx'
import Review from './components/Review.jsx'
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
  const [view, setView] = useState(1)
  const [role, setRole] = useState(load('tbamr.role') || 'pi')
  const [person, setPerson] = useState(load('tbamr.person'))
  const [sel, setSel] = useState(null)
  const [toast, setToast] = useState(null)
  const [error, setError] = useState(null)
  const [version, setVersion] = useState(0)
  const [receipts, setReceipts] = useState({})
  const [rawReq, setRawReq] = useState(null)
  const [theme, setTheme] = useState(load('tbamr.theme') || 'auto')
  const [liveTraces, setLiveTraces] = useState([])
  const timer = useRef(null)
  const traceTimer = useRef(null)

  const refresh = useCallback(async () => {
    try {
      const [s, t, d, m] = await Promise.all([api.state(), api.team(), api.decisions(), api.metrics()])
      setSnap(s); setTeam(t); setDecisions(d); setMetrics(m); setError(null); setVersion(v => v + 1)
      return s
    } catch (e) { setError('Cannot reach the backend. Start it with: uvicorn tbamr.api:app --port 8000'); return null }
  }, [])

  useEffect(() => { refresh() }, [refresh])
  const loadReceipts = useCallback(() => api.receipts({ role, person })
    .then(rs => setReceipts(Object.fromEntries(rs.map(r => [r.kind + '/' + r.key, r.ts])))).catch(() => {}), [role, person])
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
    const pull = () => api.trace().then(ts => setLiveTraces(ts.slice(0, 8))).catch(() => {})
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
  const who = { role, person }

  if (error && !snap) return <div className="wrap"><h1>TB-AMR Agent Team</h1><div className="box esc"><p>{error}</p></div></div>
  if (!snap) return <div className="wrap"><p className="muted">Loading…</p></div>
  const st = snap.state
  const pending = st.samples.flatMap(s => s.findings).filter(f => f.review === 'Pending').length
  const tabs = [['pipeline', 'Pipeline'], ['review', 'Review queue'], ['samples', 'Samples'], ['report', 'Report'], ['team', 'Agent team'], ['insights', 'Decisions & metrics'], ['logs', 'Logs'], ['about', 'About']]

  return (
    <RawCtx.Provider value={raw}>
    {snap.busy && <BusyBar busy={snap.busy} traces={liveTraces} />}
    <div className="wrap">
      <div className="top">
        <div><h1>TB-AMR Agent Team</h1>
          <p className="muted" style={{ fontSize: '.85rem' }}>
            <a href="#about" onClick={e => { e.preventDefault(); setTab('about') }}>What is this?</a>
          </p></div>
        <div className="controls">
          <div className="ctl"><label htmlFor="role">Acting as</label><select id="role" value={role} onChange={e => setRole(e.target.value)}>{Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
          <div className="ctl"><label htmlFor="person">Your name</label><input id="person" value={person} onChange={e => setPerson(e.target.value)} placeholder="e.g. Minnie" /></div>
          <div className="ctl"><span className="lbl" id="theme-l">Colors</span>
            <div className="seg theme" role="radiogroup" aria-labelledby="theme-l">{[['light', '☀ Light'], ['dark', '☾ Dark'], ['auto', 'Auto']].map(([k, l]) =>
              <button key={k} role="radio" aria-checked={theme === k} aria-selected={theme === k} title={k === 'auto' ? "Follow this computer's setting" : undefined} onClick={() => setTheme(k)}>{l}</button>)}</div></div>
          <button className="btn ghost" onClick={() => act(() => api.reset(snap.mode.data), 'Pipeline reset')}>Reset</button>
        </div>
      </div>
      <div className="banner">
        <span className={'tag ' + snap.mode.data}>{snap.mode.data === 'demo' ? 'DEMO DATA (simulated)' : 'LIVE DATA · ENA'}</span>
        <span className={'tag ' + snap.mode.brain}>{snap.mode.brain === 'claude' ? 'Claude agents (live reasoning)' : 'Replay agents (scripted, no API key)'}</span>
      </div>
      <Flow snap={snap} team={team} view={tab === 'pipeline' ? view : null} pending={pending} onPick={n => { setView(n); setTab(n === 5 && pending ? 'review' : 'pipeline') }} />
      <nav className="tabs" role="tablist">{tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}{k === 'review' && pending ? <span className="count">{pending}</span> : null}</button>)}</nav>
      <main>
        {tab === 'team' && <Team team={team} version={version} />}
        {tab === 'pipeline' && <Pipeline snap={snap} decisions={decisions} view={view} setView={setView} act={act} who={who} busy={snap.busy} openSample={setSel} />}
        {tab === 'samples' && <Samples st={st} openSample={setSel} />}
        {tab === 'review' && <Review st={st} act={act} who={who} openSample={setSel} />}
        {tab === 'report' && <Report st={st} act={act} brain={snap.mode.brain} />}
        {tab === 'insights' && <Insights m={metrics} decisions={decisions} />}
        {tab === 'logs' && <Logs version={version} />}
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

function BusyBar({ busy, traces }) {
  const kindLabel = { tool_call: 'tool', thought: 'thought', submit: 'submit', handoff: 'handoff', guardrail: 'guardrail' }
  const kindDetail = (t) => {
    const p = t.payload || {}
    if (t.kind === 'tool_call') return `${p.tool || p.name || '?'}(${Object.keys(p.input || {}).join(', ')})`
    if (t.kind === 'thought') return String(p.text || '').slice(0, 160)
    if (t.kind === 'submit') return `${Object.keys(p).slice(0, 4).join(', ')}`
    if (t.kind === 'handoff') return String(p.text || '').slice(0, 160)
    if (t.kind === 'guardrail') return String(p.text || p.reason || '').slice(0, 160)
    return ''
  }
  const latest = traces[0]
  return (
    <div className="running" role="status" aria-live="polite" aria-label={`Working: ${busy}`}>
      <span className="runbar" aria-hidden="true" />
      <div className="runrow">
        <span className="rundot" aria-hidden="true" />
        <span>Working on <b>{busy}</b>…</span>
        {latest && <span className="runsub">· {latest.agent?.replace(/_/g, ' ')} <code>{kindLabel[latest.kind] || latest.kind}</code> {kindDetail(latest)}</span>}
      </div>
      {traces.length > 1 && <ul className="runlog">
        {traces.slice(0, 5).map(t => (
          <li key={t.id} className={'rl-' + t.kind}>
            <span className="rltime">{new Date(t.ts * 1000).toLocaleTimeString(undefined, { hour12: false })}</span>
            <span className="rlagent">{t.agent?.replace(/_/g, ' ')}</span>
            <span className="rlkind">{kindLabel[t.kind] || t.kind}</span>
            <span className="rldetail">{kindDetail(t)}</span>
          </li>
        ))}
      </ul>}
    </div>
  )
}
