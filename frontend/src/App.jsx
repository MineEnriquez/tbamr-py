import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { ROLE_LABEL } from './components/common.jsx'
import Team from './components/Team.jsx'
import Pipeline from './components/Pipeline.jsx'
import Samples, { Drawer } from './components/Samples.jsx'
import Review from './components/Review.jsx'
import Report from './components/Report.jsx'
import Insights from './components/Insights.jsx'
import { RawCtx, RawViewer } from './components/Raw.jsx'

const load = k => { try { return localStorage.getItem(k) || '' } catch { return '' } }
const save = (k, v) => { try { localStorage.setItem(k, v) } catch { /* storage unavailable */ } }

export default function App() {
  const [snap, setSnap] = useState(null)
  const [team, setTeam] = useState([])
  const [decisions, setDecisions] = useState([])
  const [metrics, setMetrics] = useState(null)
  const [tab, setTab] = useState('team')
  const [view, setView] = useState(1)
  const [role, setRole] = useState(load('tbamr.role') || 'pi')
  const [person, setPerson] = useState(load('tbamr.person'))
  const [sel, setSel] = useState(null)
  const [toast, setToast] = useState(null)
  const [error, setError] = useState(null)
  const [version, setVersion] = useState(0)
  const [receipts, setReceipts] = useState({})
  const [rawReq, setRawReq] = useState(null)
  const timer = useRef(null)

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
  useEffect(() => { const k = e => e.key === 'Escape' && !rawReq && setSel(null); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k) }, [rawReq])
  useEffect(() => { save('tbamr.role', role) }, [role])
  useEffect(() => { save('tbamr.person', person) }, [person])

  const flash = (text, err) => { setToast({ text, err }); setTimeout(() => setToast(null), err ? 6000 : 2500) }
  const act = async (fn, ok) => {
    try { await fn(); flash(ok) } catch (e) { flash(e.message, true) }
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
  const tabs = [['team', 'Agent team'], ['pipeline', 'Pipeline'], ['samples', 'Samples'], ['review', 'Review queue'], ['report', 'Report'], ['insights', 'Decisions & metrics']]

  return (
    <RawCtx.Provider value={raw}>
    <div className="wrap">
      <div className="top">
        <div><span className="eyebrow">A.G.E.N.T. Playbook · Python agents v0.2</span><h1>TB-AMR Agent Team</h1>
          <p className="muted">Hybrid agentic workflow for <i>M. tuberculosis</i> drug-resistance evidence: Claude agents with tools, rule agents for reproducible steps, human gates throughout.</p></div>
        <div className="controls">
          <div className="ctl"><label htmlFor="role">Acting as</label><select id="role" value={role} onChange={e => setRole(e.target.value)}>{Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
          <div className="ctl"><label htmlFor="person">Your name</label><input id="person" value={person} onChange={e => setPerson(e.target.value)} placeholder="e.g. Minnie" /></div>
          <button className="btn ghost" onClick={() => act(() => api.reset(snap.mode.data), 'Pipeline reset')}>Reset</button>
        </div>
      </div>
      <div className="banner">
        <span className={'tag ' + snap.mode.data}>{snap.mode.data === 'demo' ? 'DEMO DATA (simulated)' : 'LIVE DATA · ENA'}</span>
        <span className={'tag ' + snap.mode.brain}>{snap.mode.brain === 'claude' ? 'Claude agents (live reasoning)' : 'Replay agents (scripted, no API key)'}</span>
        <span className="muted">Names are recorded with every human decision; the two-person rule needs two different names. Before any decision you must open its raw data: the receipt is saved with your decision.</span>
      </div>
      <nav className="tabs" role="tablist">{tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}{k === 'review' && pending ? <span className="count">{pending}</span> : null}</button>)}</nav>
      <main>
        {tab === 'team' && <Team team={team} version={version} />}
        {tab === 'pipeline' && <Pipeline snap={snap} decisions={decisions} view={view} setView={setView} act={act} who={who} busy={snap.busy} openSample={setSel} />}
        {tab === 'samples' && <Samples st={st} openSample={setSel} />}
        {tab === 'review' && <Review st={st} act={act} who={who} openSample={setSel} />}
        {tab === 'report' && <Report st={st} act={act} brain={snap.mode.brain} />}
        {tab === 'insights' && <Insights m={metrics} decisions={decisions} />}
      </main>
      {sel && <Drawer run={sel} st={st} pending={snap.pending_overrides} act={act} who={who} close={() => setSel(null)} version={version} />}
      {rawReq && <RawViewer key={rawReq.kind + rawReq.key} req={rawReq} who={who} onClose={() => setRawReq(null)} onViewed={loadReceipts} />}
      {toast && <div className={'toast' + (toast.err ? ' err' : '')} role="status">{toast.text}</div>}
      <footer>{snap.mode.data === 'demo' ? 'Demo data: every accession starting DEMO/PRJDEMO is simulated. ' : 'Live data from the ENA Portal API. '}Genomic predictions are not laboratory-confirmed susceptibility and cannot estimate national prevalence.</footer>
    </div>
    </RawCtx.Provider>
  )
}
