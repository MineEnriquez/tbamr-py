import React from 'react'

/* The About tab is pure reference material: what the team is, how decisions are logged, which
 * modes exist, and what has / has not been verified. Nothing here reads from the backend — it's
 * static context, moved off the landing page so the landing page can focus on the work itself. */

const TEAM = [
  ['Orchestrator', 'coordinator', 'hand-off, re-plan (max 1)', 'skip a human gate'],
  ['Scope Guardian', 'Claude agent', '— (reasons over the scope)', 'drop one of the 4 required playbook definitions'],
  ['Discovery Assistant', 'Claude agent', 'ena_search_runs (paged), ena_study, find_publications', 'return an accession no tool returned'],
  ['Verification Tasker', 'rules + Claude agent', 'ena_study, find_publications', 'verify a run whose ENA country field is missing'],
  ['QC Analyst', 'rules', 'coverage estimate, checksum', 'change thresholds'],
  ['Profiling Tasker', 'tool runner', 'TB-Profiler (subprocess) or JSON import', 'interpret results'],
  ['Evidence Analyst', 'rules + Claude agent', '— (reads findings)', 'clear a finding from review, or confirm resistance'],
  ['Reporting Orchestrator', 'rules + Claude draft', '— (reads findings)', 'release the report'],
]

const RAW_ROWS = [
  ['Approve scope', 'What the Scope Guardian received and returned'],
  ['Resolve a hold, resolve a QC escalation, override, co-sign', "The run's archive record, the agent's evidence and tool outputs, and how coverage was derived"],
  ['Approve cohort', "Every candidate run's archive record, as a table (click a run to drill in)"],
  ['Confirm QC', 'Base counts, genome size, estimated coverage and checksums'],
  ['Close profiling batch', 'Every TB-Profiler result (click a run for its full JSON)'],
  ['Review a finding', "The run's full TB-Profiler JSON"],
  ['Release / share draft', 'Every number in that report version'],
]

const MODES = [
  ['TBAMR_DATA', 'demo (simulated records, offline) · live (real ENA + Europe PMC)', 'demo'],
  ['TBAMR_BRAIN', 'replay (scripted agents, no key) · claude (live reasoning)', 'claude if ANTHROPIC_API_KEY is set, else replay'],
  ['ANTHROPIC_API_KEY', 'your key from console.anthropic.com', '—'],
  ['CLAUDE_MODEL', 'any Messages API model id', 'claude-sonnet-4-5'],
  ['TBAMR_DB', 'path of the SQLite decision log', 'tbamr-<data>.db'],
]

export default function About() {
  return (
    <section className="panel about">
      <span className="eyebrow">A.G.E.N.T. Playbook · Python agents v0.2</span>
      <h2>About the TB-AMR Agent Team</h2>
      <p>
        A <b>hybrid agentic workflow</b> for <i>Mycobacterium tuberculosis</i> drug-resistance
        genomic evidence, built for the A.G.E.N.T. Playbook capstone
        (<i>TB Antimicrobial Resistance in Indonesia</i>).
      </p>
      <p>
        Each member of the team is its own Python class. <b>Claude agents</b> are given a goal and
        tools and decide which tools to call and when to stop. <b>Rule agents</b> do the steps that
        must be reproducible. The <b>Orchestrator</b> hands work between them, re-plans when an
        agent escalates, and stops at every human gate.
      </p>
      <div className="box note">
        <p><b>Scope.</b> v0.2 · offline demo works out of the box. Live ENA data and Claude
        reasoning are built in and switched on by environment variables (see Modes below).
        Genomic predictions are not laboratory-confirmed susceptibility and cannot estimate
        national prevalence.</p>
      </div>

      <h3>The team</h3>
      <div className="tw"><table>
        <thead><tr><th>Member</th><th>Type</th><th>Tools</th><th>Guardrail (what it can never do)</th></tr></thead>
        <tbody>{TEAM.map(([m, t, tools, g]) => (
          <tr key={m}><td><b>{m}</b></td><td>{t}</td><td className="mono" style={{ fontSize: '.86rem' }}>{tools}</td><td>{g}</td></tr>
        ))}</tbody>
      </table></div>

      <h3>Shared decision contract</h3>
      <ul className="clean">
        <li>Five outcomes: <b>Proceed · Hold · Exclude · Retry · Escalate</b>.</li>
        <li>Every decision logged with sample, rule version, rationale and time.</li>
        <li>Humans-only outcomes: <b>Approve</b>, <b>Override</b>.</li>
        <li>Overrides never erase history.</li>
        <li>Relaxing a safeguard needs <b>two different named people</b> (two-person rule).</li>
        <li>Every agent step (task, reasoning, tool call, submission, guardrail rejection) is stored in an <b>agent trace</b> you can read in the UI.</li>
      </ul>

      <h3>Raw data alongside every decision</h3>
      <p>
        Every decision box offers a <b>"View raw data"</b> button for the source behind that
        decision. Opening it records a receipt (who, what, when), which is saved with the decision
        — for example: <i>Raw data (ena/DEMO-R15) viewed by Minnie at 2026-10-26 12:20:45</i>. If
        the person decides without opening the raw data, the evidence line says so instead; the
        decision is not blocked. Each person's receipts are tracked separately, so the audit trail
        shows exactly who looked at what.
      </p>
      <div className="tw"><table>
        <thead><tr><th>Decision</th><th>Raw data available</th></tr></thead>
        <tbody>{RAW_ROWS.map(([d, r]) => <tr key={d}><td>{d}</td><td>{r}</td></tr>)}</tbody>
      </table></div>

      <h3>Modes</h3>
      <div className="tw"><table>
        <thead><tr><th>Variable</th><th>Values</th><th>Default</th></tr></thead>
        <tbody>{MODES.map(([v, vals, d]) => (
          <tr key={v}><td className="mono">{v}</td><td>{vals}</td><td className="mono">{d}</td></tr>
        ))}</tbody>
      </table></div>

      <p className="muted" style={{ marginTop: '2rem', fontSize: '.85rem' }}>
        Full source and setup instructions: see the project README.
      </p>
    </section>
  )
}
