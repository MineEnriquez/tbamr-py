import React from 'react'
import { ROLE_LABEL } from './common.jsx'

/* Workflow canvas: nodes connected by sockets, in the spirit of n8n / make.com.
   Each stage is a node with a tinted icon tile, title, agent chips and the human
   gate; status shows as a corner dot and a left-border accent. */

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
const ICONS = { 1: '🎯', 2: '🔍', 3: '🧫', 4: '🧬', 5: '⚖️', 6: '📄' }
const TINT = { 1: 'violet', 2: 'blue', 3: 'amber', 4: 'teal', 5: 'rose', 6: 'slate' }

function Socket() { return <span className="fsock" aria-hidden="true" /> }
function Line() { return <span className="fline" aria-hidden="true"><Socket /><i /><Socket /></span> }

export default function Flow({ snap, team, view, onPick, pending }) {
  const st = snap.state
  const byName = Object.fromEntries(team.map(a => [a.name, a]))
  return (
    <section className="flow" aria-label="Workflow diagram">
      <div className="flowrow">
        <div className="fnode start"><span className="fic">?</span><span>Research question</span></div>
        <Line />
        {snap.stages.map((s, i) => {
          const status = st.stage_status[String(s.n)]
          const [gate, role] = GATE[s.n]
          const busy = snap.busy && status === 'ready'
          return (
            <React.Fragment key={s.n}>
              <button className={`fstage t-${TINT[s.n]} s-${status}${view === s.n ? ' cur' : ''}${busy ? ' busy' : ''}`} onClick={() => onPick(s.n)}
                aria-label={`Stage ${s.n}: ${s.name}, ${STATUS[status]}`}>
                <span className={`fsdot s-${status}`} title={STATUS[status]} />
                <span className="fhead">
                  <span className="fitile" aria-hidden="true">{ICONS[s.n]}</span>
                  <span className="ftitle">
                    <span className="fnum">Stage {s.n} · Owner: <span className="fown">{ROLE_LABEL[role]}</span></span>
                    <span className="fname">{s.name}</span>
                  </span>
                </span>
                <span className="fagents">{s.agents.map(a => {
                  const m = byName[a]
                  return <span key={a} className={'fagent ' + (m?.kind || 'rule')} title={m ? m.title : a}>{m?.kind === 'llm' ? '✦' : '⚙'} {SHORT[a] || a}</span>
                })}</span>
                <span className={'fgate' + (status === 'wait' ? ' now' : '')} title={`Human gate: ${gate} (${ROLE_LABEL[role]})`}>
                  <span className="fgic">👤</span>{gate}{s.n === 5 && pending ? <b className="count">{pending}</b> : null}
                </span>
                <span className="fsL" aria-hidden="true" /><span className="fsR" aria-hidden="true" />
              </button>
              {i < snap.stages.length - 1 && <Line />}
            </React.Fragment>
          )
        })}
        <Line />
        <div className={'fnode end' + (st.gates?.release ? ' done' : '')}><span className="fic">📄</span><span>Evidence report</span></div>
      </div>
      <div className="flegend">
        <span><span className="fagent llm">✦</span> Claude agent (chooses its own tool calls)</span>
        <span><span className="fagent rule">⚙</span> Rule agent (fixed, reproducible rules)</span>
        <span><span className="fgate inline">👤</span> Human gate: you decide, after viewing the raw data</span>
        <span className="sw"><i className="s-done" />Done <i className="s-wait" />Needs you <i className="s-ready" />Ready <i className="s-locked" />Locked</span>
      </div>
    </section>
  )
}
