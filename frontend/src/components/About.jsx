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

/* Package versions below are kept in lockstep with backend/requirements.txt, backend/pyproject.toml,
 * backend/requirements-dev.txt and frontend/package.json. When any of those change, update here too
 * so the About page doesn't drift from what the app actually ships. */
const BACKEND_PKGS = [
  ['fastapi', '0.115.6', 'HTTP + typed request/response layer'],
  ['uvicorn[standard]', '0.32.1', 'ASGI server'],
  ['httpx', '0.28.1', 'HTTP client (ENA, Europe PMC)'],
  ['python-multipart', '0.0.20', 'multipart/form-data for TB-Profiler imports'],
  ['anthropic', '0.49.0', 'Claude Messages API SDK'],
  ['pytest', '8.3.4', 'test runner'],
]

const DEV_PKGS = [
  ['playwright', '1.48.0', 'headless-browser automation'],
  ['pytest-playwright', '0.5.2', 'pytest integration + `page` fixture'],
]

const FRONTEND_PKGS = [
  ['react', '18.3.1', 'runtime'],
  ['react-dom', '18.3.1', 'DOM renderer'],
  ['marked', '^18.1.2', 'markdown parser for the drafted summary'],
  ['vite', '5.4.11', 'dev server + production bundler (devDep)'],
  ['@vitejs/plugin-react', '4.3.4', 'React fast-refresh plugin (devDep)'],
]

const EXTERNAL = [
  ['SQLite', 'stdlib (via Python sqlite3)', 'decision log, agent trace, raw cache, executions, runs'],
  ['TB-Profiler', 'optional, subprocess', 'resistance profiling for live isolates; parser handles v4.x–v6.x JSON'],
  ['fasterq-dump (sra-tools)', 'optional, subprocess', 'FASTQ retrieval before TB-Profiler'],
  ['ENA Portal API', 'ebi.ac.uk/ena/portal/api', 'run + study metadata (TBAMR_DATA=live)'],
  ['Europe PMC API', 'europepmc.org/RestfulWebService', 'linked publications (TBAMR_DATA=live)'],
  ['Claude API', 'api.anthropic.com', 'live agent reasoning (TBAMR_BRAIN=claude)'],
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

      <h3>Technical reference</h3>
      <p className="muted" style={{ marginTop: 0 }}>Pinned to the versions this build ships against. Full lockfiles live in <span className="mono">backend/requirements.txt</span>, <span className="mono">backend/pyproject.toml</span>, <span className="mono">backend/requirements-dev.txt</span> and <span className="mono">frontend/package.json</span>.</p>
      <dl className="kv box">
        <dt>App version</dt><dd className="mono">0.2.0</dd>
        <dt>Python</dt><dd className="mono">≥ 3.10 (built with 3.12)</dd>
        <dt>Node / build</dt><dd>Vite 5 → ES modules; the built bundle in <span className="mono">frontend/dist</span> is served by FastAPI's StaticFiles.</dd>
        <dt>Storage</dt><dd>SQLite file at <span className="mono">tbamr-&lt;mode&gt;.db</span>. Tables: <span className="mono">decisions · trace · raw · views · executions · runs · kv</span>.</dd>
      </dl>

      <h4 style={{ marginTop: 10 }}>Backend runtime (<span className="mono">backend/requirements.txt</span>)</h4>
      <div className="tw"><table>
        <thead><tr><th>Package</th><th>Version</th><th>Purpose</th></tr></thead>
        <tbody>{BACKEND_PKGS.map(([p, v, w]) => <tr key={p}><td className="mono">{p}</td><td className="mono">{v}</td><td>{w}</td></tr>)}</tbody>
      </table></div>

      <h4>Developer-only (<span className="mono">backend/requirements-dev.txt</span>)</h4>
      <p className="muted" style={{ fontSize: '.85rem', marginTop: 0 }}>Needed to run <span className="mono">pytest -m ui</span>. After <span className="mono">pip install -r requirements-dev.txt</span>, run <span className="mono">playwright install chromium</span> once (~100 MB browser binary).</p>
      <div className="tw"><table>
        <thead><tr><th>Package</th><th>Version</th><th>Purpose</th></tr></thead>
        <tbody>{DEV_PKGS.map(([p, v, w]) => <tr key={p}><td className="mono">{p}</td><td className="mono">{v}</td><td>{w}</td></tr>)}</tbody>
      </table></div>

      <h4>Frontend (<span className="mono">frontend/package.json</span>)</h4>
      <div className="tw"><table>
        <thead><tr><th>Package</th><th>Version</th><th>Purpose</th></tr></thead>
        <tbody>{FRONTEND_PKGS.map(([p, v, w]) => <tr key={p}><td className="mono">{p}</td><td className="mono">{v}</td><td>{w}</td></tr>)}</tbody>
      </table></div>

      <h4>External services and tools</h4>
      <div className="tw"><table>
        <thead><tr><th>Dependency</th><th>Where</th><th>Used for</th></tr></thead>
        <tbody>{EXTERNAL.map(([p, w, u]) => <tr key={p}><td>{p}</td><td className="mono" style={{ fontSize: '.85rem' }}>{w}</td><td>{u}</td></tr>)}</tbody>
      </table></div>

      <h4>Test suite</h4>
      <ul className="clean">
        <li><span className="mono">pytest</span> — 23 default tests (TestClient, no browser, no network)</li>
        <li><span className="mono">pytest -m ui</span> — 4 Playwright tests driving the built UI headlessly</li>
        <li><span className="mono">pytest -m live</span> — 1 opt-in test hitting the real ENA Portal API</li>
      </ul>

      <h3>Acknowledgements</h3>
      <p>
        Drug-resistance predictions in this pipeline are produced by <b>TB-Profiler</b> —
        an open-source profiling tool for <i>Mycobacterium tuberculosis</i> maintained by Jody Phelan
        and collaborators. If you use this pipeline in work that leads to a publication, please cite
        the TB-Profiler paper:
      </p>
      <blockquote className="box note" style={{ margin: '8px 0', fontSize: '.9rem' }}>
        Phelan, J.E., O'Sullivan, D.M., Machado, D. <i>et al.</i> Integrating informatics tools and
        portable sequencing technology for rapid detection of resistance to anti-tuberculous drugs.
        <i> Genome Medicine</i> 11, 41 (2019). <span className="mono">doi:10.1186/s13073-019-0650-x</span>
      </blockquote>
      <p className="muted" style={{ fontSize: '.9rem' }}>
        Source and database: <span className="mono">github.com/jodyphelan/TBProfiler</span>.
        This project parses TB-Profiler JSON (v4.x – v6.x) via <span className="mono">backend/tbamr/tools/tbprofiler.py</span>;
        the tool itself is invoked as a subprocess when <span className="mono">tb-profiler</span> and <span className="mono">fasterq-dump</span> are on the PATH.
      </p>
      <p className="muted" style={{ fontSize: '.9rem' }}>
        Sample metadata and sequencing runs come from the <b>European Nucleotide Archive (ENA)</b> at EMBL-EBI,
        with linked literature from <b>Europe PMC</b>. Reasoning agents are powered by <b>Anthropic Claude</b>.
      </p>

      <p className="muted" style={{ marginTop: '2rem', fontSize: '.85rem' }}>
        Full source and setup instructions: see the project README.
      </p>
    </section>
  )
}
