import React from 'react'
import { Bars, Chip, OUT_COLOR, actorLabel, fmtTime } from './common.jsx'

const fmtS = s => s == null ? '—' : s < 60 ? `${Math.round(s)} s` : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`

export default function Insights({ m, decisions }) {
  if (!m) return null
  const tiles = [
    [m.agreement_pct == null ? '—' : m.agreement_pct + '%', 'Agent–human agreement', 'approvals vs overrides'],
    [m.escalation_rate_pct + '%', 'Escalation rate', `of ${m.agent_decisions} agent decisions`],
    [fmtS(m.median_resolution_s), 'Median time to resolve an escalation', `${m.escalations_resolved} resolved · ${m.escalations_open} open`],
    [m.overrides, 'Human overrides', ''],
    [Object.values(m.tool_calls).reduce((a, b) => a + b, 0), 'Agent tool calls', Object.entries(m.tool_calls).map(([k, v]) => `${k} ${v}`).join(' · ')],
    [m.completeness_pct + '%', 'Critical fields logged', 'gate: 100%'],
  ]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="row between"><h2>Trust signals · Track phase</h2><span className="muted" style={{ fontSize: '.82rem' }}>Computed live from the decision log and agent traces</span></div>
      <div className="metrics">{tiles.map(([v, l, s]) => <div className="metric" key={l}><span className="v">{v}</span><span className="l">{l}{s && <><br /><span className="muted">{s}</span></>}</span></div>)}</div>
      <div className="grid2" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))' }}>
        <div className="box"><h3>Decisions by outcome</h3><Bars rows={Object.entries(m.by_outcome)} color={k => OUT_COLOR[k] || 'var(--blue)'} /></div>
        <div className="box"><h3>Decisions by team member</h3><Bars rows={Object.entries(m.by_agent).map(([k, v]) => [k.replace(/_/g, ' '), v])} /></div>
      </div>
      <div className="tw"><table><thead><tr><th>Time</th><th>Run</th><th>Actor</th><th>Decision</th><th>Rule</th><th>Rationale</th></tr></thead><tbody>
        {decisions.map(d => <tr key={d.id}><td className="mono">{fmtTime(d.ts)}</td><td className="mono">{d.sample_id}</td><td style={{ whiteSpace: 'nowrap' }}>{actorLabel(d.actor)}</td><td><Chip label={d.outcome} /></td><td className="mono">{d.rule_version}</td><td style={{ minWidth: 260 }}>{d.rationale}</td></tr>)}
      </tbody></table></div>
    </div>
  )
}
