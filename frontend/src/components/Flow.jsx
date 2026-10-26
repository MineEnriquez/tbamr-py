import React from 'react'
import { ROLE_LABEL } from './common.jsx'

/* The workflow at a glance: six stages, the agents that work in each, and the human gate
   after each one. Colours show live status; clicking a stage opens it in the Pipeline tab. */

const GATE = {
  1: ['Approve scope', 'pi'],
  2: ['Approve cohort', 'pi'],
  3: ['Confirm QC', 'analyst'],
  4: ['Close batch', 'analyst'],
  5: ['Review findings', 'tbexpert'],
  6: ['Release report', 'pi'],
}
const STATUS = { locked: 'Locked', ready: 'Ready to run', wait: 'Needs you', done: 'Done' }
const SHORT = { scope_guardian: 'Scope Guardian', discovery: 'Discovery', verification: 'Verification', qc: 'QC Analyst', profiling: 'Profiling', evidence: 'Evidence Analyst', reporting: 'Reporting' }

export default function Flow({ snap, team, view, onPick, pending }) {
  const st = snap.state
  const byName = Object.fromEntries(team.map(a => [a.name, a]))
  return (
    <section className="flow" aria-label="Workflow diagram">
      <div className="flowrow">
        <div className="fnode start"><span className="fic">?</span><span>Research question</span></div>
        {snap.stages.map(s => {
          const status = st.stage_status[String(s.n)]
          const [gate, role] = GATE[s.n]
          const busy = snap.busy && status === 'ready'
          return (
            <React.Fragment key={s.n}>
              <span className="farrow" aria-hidden="true">→</span>
              <button className={'fstage ' + status + (view === s.n ? ' cur' : '') + (busy ? ' busy' : '')} onClick={() => onPick(s.n)}
                aria-label={`Stage ${s.n}: ${s.name}, ${STATUS[status]}`}>
                <span className="fhead"><span className="fn">{s.n}</span><span className="fst">{busy ? 'Working…' : STATUS[status]}</span></span>
                <span className="fname">{s.name}</span>
                <span className="fagents">{s.agents.map(a => {
                  const m = byName[a]
                  return <span key={a} className={'fagent ' + (m?.kind || 'rule')} title={m ? m.title : a}>{m?.kind === 'llm' ? '✦' : '⚙'} {SHORT[a] || a}</span>
                })}</span>
                <span className={'fgate' + (status === 'wait' ? ' now' : '')} title={`Human gate: ${gate} (${ROLE_LABEL[role]})`}>
                  <span className="fic">👤</span>{gate}{s.n === 5 && pending ? <b className="count">{pending}</b> : null}
                </span>
              </button>
            </React.Fragment>
          )
        })}
        <span className="farrow" aria-hidden="true">→</span>
        <div className={'fnode end' + (st.gates?.release ? ' done' : '')}><span className="fic">📄</span><span>Evidence report</span></div>
      </div>
      <div className="flegend">
        <span><span className="fagent llm">✦</span> Claude agent (chooses its own tool calls)</span>
        <span><span className="fagent rule">⚙</span> Rule agent (fixed, reproducible rules)</span>
        <span><span className="fgate">👤</span> Human gate: you decide, after viewing the raw data</span>
        <span className="sw"><i className="s-done" />Done <i className="s-wait" />Needs you <i className="s-ready" />Ready <i className="s-locked" />Locked</span>
      </div>
    </section>
  )
}
