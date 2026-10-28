import React from 'react'
import { ROLE_LABEL } from './common.jsx'

/* Workflow canvas: mermaid-style flowchart. Thin-outlined nodes, light type, airy spacing. */

const GATE = {
  1: ['Approve scope', 'pi'],
  2: ['Approve cohort', 'pi'],
  3: ['Confirm Quality Control', 'analyst'],
  4: ['Close batch', 'analyst'],
  5: ['Review findings', 'tbexpert'],
  6: ['Release report', 'pi'],
}
const STATUS = { locked: 'locked', ready: 'ready', wait: 'needs you', done: 'done' }
const ICONS = { 1: '🎯', 2: '🔍', 3: '🧫', 4: '🧬', 5: '⚖️', 6: '📄' }
const SHORT = { scope_guardian: 'Scope Guardian', discovery: 'Discovery', verification: 'Verification', qc: 'Quality Control', profiling: 'Profiling', evidence: 'Evidence Analyst', reporting: 'Reporting' }

function Arrow() {
  return <span className="farrow" aria-hidden="true"><i /><svg viewBox="0 0 10 10" width="10" height="10"><path d="M1 1l6 4-6 4" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
}

export default function Flow({ snap, team, view, onPick, pending }) {
  const st = snap.state
  const byName = Object.fromEntries(team.map(a => [a.name, a]))
  const released = !!st.gates?.release
  return (
    <section className="flow" aria-label="Workflow diagram">
      <div className="fchart">
        <div className="fnode cap">
          <span className="fcap">start</span>
          <span className="fnode-body">Research question</span>
        </div>
        <Arrow />
        {snap.stages.map((s, idx) => {
          const status = st.stage_status[String(s.n)]
          const [gate, role] = GATE[s.n]
          const busy = snap.busy && status === 'ready'
          const cur = view === s.n
          return (
            <React.Fragment key={s.n}>
              <button className={`fnode stage s-${status}${cur ? ' cur' : ''}${busy ? ' busy' : ''}`} onClick={() => onPick(s.n)}
                aria-label={`Stage ${s.n}: ${s.name}, ${STATUS[status]}, owner ${ROLE_LABEL[role]}`}>
                <span className="fcap">stage {s.n} <span className="fcap-dot" /> {STATUS[status]}</span>
                <span className="fnode-body"><span className="fnode-icon">{ICONS[s.n]}</span>{s.name}</span>
                <span className="fnode-meta">{ROLE_LABEL[role]} · {gate}{s.n === 5 && pending ? <b className="fnode-count"> {pending}</b> : null}</span>
                <div className="fbtip" role="tooltip">
                  <div className="fbtip-title">Agents in this stage</div>
                  <div className="fbtip-agents">{s.agents.map(a => {
                    const m = byName[a]
                    return <span key={a} className={'fbtip-ag ' + (m?.kind || 'rule')}>{m?.kind === 'llm' ? '✦' : '⚙'} {SHORT[a] || a}</span>
                  })}</div>
                </div>
              </button>
              {idx < snap.stages.length - 1 && <Arrow />}
            </React.Fragment>
          )
        })}
        <Arrow />
        <div className={'fnode cap' + (released ? ' done' : '')}>
          <span className="fcap">output</span>
          <span className="fnode-body">Evidence report</span>
        </div>
      </div>
      <div className="flegend">
        <span className="sw"><i className="s-done" /><span>done</span></span>
        <span className="sw"><i className="s-wait" /><span>needs you</span></span>
        <span className="sw"><i className="s-ready" /><span>ready</span></span>
        <span className="sw"><i className="s-locked" /><span>locked</span></span>
      </div>
    </section>
  )
}
