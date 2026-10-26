import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtTime } from './common.jsx'

const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`
const initials = t => t.split(/[\s&]+/).filter(w => /^[A-Z]/.test(w)).slice(0, 2).map(w => w[0]).join('')

export default function Team({ team, version }) {
  const [sel, setSel] = useState('discovery')
  const [trace, setTrace] = useState([])
  useEffect(() => { api.trace(sel).then(setTrace).catch(() => setTrace([])) }, [sel, version])
  const agent = team.find(a => a.name === sel)
  return (
    <div className="grid2">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <p className="muted">Each member of the team is its own Python class. <b>Claude agents</b> choose their own tool calls to reach a goal; <b>rule agents</b> apply fixed, reproducible rules; the <b>Orchestrator</b> hands work between them and stops at human gates. Click a member to see what it did and why.</p>
        <div className="team">
          {team.map(a => (
            <button key={a.name} className="member" aria-pressed={sel === a.name} onClick={() => setSel(a.name)}>
              <div className="row" style={{ flexWrap: 'nowrap' }}>
                <span className={'avatar ' + a.kind}>{initials(a.title) || a.title[0]}</span>
                <div style={{ minWidth: 0 }}><div className="kind">{a.kind === 'llm' ? 'Claude agent' : a.kind === 'rule' ? 'Rule agent' : 'Coordinator'}</div><h3>{a.title}</h3></div>
              </div>
              <p style={{ fontSize: '.86rem' }}>{a.description}</p>
              {a.tools.length > 0 && <div className="tools">{a.tools.map(t => <span key={t} className="tool">{t}</span>)}</div>}
              <div className="row muted" style={{ fontSize: '.78rem' }}>
                <span>{plural(a.decisions, 'decision')}</span>{a.kind === 'llm' && <><span>· {plural(a.activity.tool_calls, 'tool call')}</span><span>· {plural(a.activity.submissions, 'submission')}</span></>}
              </div>
            </button>
          ))}
        </div>
      </div>
      <section className="panel">
        <div><span className="eyebrow">Agent trace</span><h2>{agent ? agent.title : sel}</h2></div>
        {!trace.length && <p className="muted">No activity yet. Run the stages in the Pipeline tab and come back.</p>}
        <div className="trace">
          {trace.map(t => (
            <div key={t.id} className={'tr ' + t.kind}>
              <div className="who">{fmtTime(t.ts)} · {label(t.kind)}{t.payload && t.payload.mode === 'replay' ? ' · replay' : ''}</div>
              <Body t={t} />
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

const label = k => ({ task: 'Task received', thought: 'Reasoning', tool_call: 'Tool call', submit: 'Submitted result (passed guardrails)', guardrail: 'Guardrail rejected submission', stopped: 'Stopped', handoff: 'Hand-off' }[k] || k)

function Body({ t }) {
  const p = t.payload || {}
  if (t.kind === 'thought') return <p>{p.text}</p>
  if (t.kind === 'task') return <p>{p.task}</p>
  if (t.kind === 'handoff') return <p>{p.text}</p>
  if (t.kind === 'tool_call') return <><p><span className="mono">{p.tool}</span>({Object.entries(p.input || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ')})</p><pre>{JSON.stringify(p.output_preview, null, 1)}</pre></>
  return <pre>{JSON.stringify(p, null, 1).slice(0, 1500)}</pre>
}
