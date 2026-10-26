import React, { useState } from 'react'

export const ROLE_LABEL = { pi: 'Principal Investigator', deputy: 'Deputy PI', analyst: 'Bioinformatics Analyst', tbexpert: 'TB Microbiologist' }

export function Chip({ label, kind }) {
  const k = kind || String(label || '').split(' ')[0]
  return <span className={`chip c-${k}`}>{label}</span>
}

export function actorLabel(actor) {
  if (!actor) return ''
  const [type, ...rest] = actor.split(':')
  if (type === 'agent') return 'Agent · ' + rest.join(':').replace(/_/g, ' ')
  if (actor.includes(' + ')) return 'Humans · ' + actor.replace(/^human:/, '')
  const [role, person] = rest
  return 'Human · ' + (ROLE_LABEL[role] || role) + (person && person !== 'unnamed' ? ` (${person})` : '')
}

export function Bars({ rows, color = () => 'var(--blue)' }) {
  const max = Math.max(1, ...rows.map(r => r[1]))
  const h = 22, w = 440, lw = 110
  return (
    <svg viewBox={`0 0 ${w} ${rows.length * h + 6}`} className="chart" role="img" aria-label="Bar chart">
      {rows.map(([k, v], i) => {
        const bw = Math.max(v ? 2 : 0, (w - lw - 44) * v / max)
        return <g key={k}><text x="0" y={i * h + 15}>{k}</text><rect x={lw} y={i * h + 4} width={bw} height="14" rx="2" fill={color(k)} /><text x={lw + bw + 6} y={i * h + 15} className="cv">{v}</text></g>
      })}
    </svg>
  )
}

export function Rationale({ id, placeholder, onSubmit, buttons, extra }) {
  const [text, setText] = useState('')
  return (
    <>
      <label className="muted" htmlFor={id} style={{ fontSize: '.8rem' }}>Rationale (recorded with your decision)</label>
      <textarea id={id} value={text} onChange={e => setText(e.target.value)} placeholder={placeholder} />
      <div className="row">{buttons.map(([value, label, primary]) =>
        <button key={value} className={'btn small' + (primary ? ' primary' : '')} onClick={() => onSubmit(value, text)}>{label}</button>)}{extra}</div>
    </>
  )
}

export const OUT_COLOR = { Proceed: 'var(--ok)', Hold: 'var(--hold)', Exclude: 'var(--ex)', Retry: 'var(--retry)', Escalate: 'var(--esc)', Override: 'var(--pend)', Approve: 'var(--blue)', Info: 'var(--line)' }
export const fmtTime = ts => new Date(ts * 1000).toLocaleTimeString()
