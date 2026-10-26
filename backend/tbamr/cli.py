"""Command-line walkthrough: runs the whole pipeline, acting as each human in turn.

    python -m tbamr.cli               # offline demo data + replay agents
    python -m tbamr.cli --live        # real ENA data (needs internet)
    python -m tbamr.cli --live --brain claude   # Claude-powered agents (needs ANTHROPIC_API_KEY)
"""
from __future__ import annotations

import argparse
import os
import tempfile

from .api import build_orchestrator


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="use real ENA data instead of the offline demo")
    ap.add_argument("--brain", choices=["replay", "claude"], default=None)
    ap.add_argument("--question", default=None)
    a = ap.parse_args()
    db = os.path.join(tempfile.mkdtemp(), "walkthrough.db")
    o = build_orchestrator("live" if a.live else "demo", a.brain, db)
    if a.question:
        o.state.question = a.question
    p = lambda *x: print(*x, flush=True)
    p(f"Mode: data={'live' if a.live else 'demo'} brain={o.client.mode}\n")
    p("Stage 1 · Scope Guardian"); s = o.run_stage(1); p(f"  {len(s['gaps'])} definitions proposed, warnings: {s['warnings']}")
    o.approve_scope("pi", "Researcher"); p("  ✓ scope approved by PI")
    p("Stage 2 · Discovery + Verification"); r = o.run_stage(2)
    st = o.state
    p(f"  candidates {r['candidates']} · verified {sum(x.eligibility=='Verified' for x in st.samples)} · held {sum(x.eligibility=='Hold' for x in st.samples)} · excluded {sum(x.eligibility=='Excluded' for x in st.samples)}")
    for c in r["checks"]:
        p(f"  cohort check [{c['outcome']}] {c['text']}")
    o.approve_cohort("pi", "Researcher"); p("  ✓ cohort approved")
    p("Stage 3 · QC"); p("  ", o.run_stage(3)); o.confirm_qc("analyst", "Analyst")
    p("Stage 4 · Profiling"); p("  ", o.run_stage(4))
    if sum(x.profiling == "Done" for x in st.samples):
        o.close_profiling("analyst", "Analyst")
        p("Stage 5 · Evidence"); p("  ", o.run_stage(5))
        p("Stage 6 · Report"); rep = o.run_stage(6)
        for d in rep["drugs"]:
            p(f"  {d['name']}: {d['predicted_resistant']}/{d['n']} predicted resistant, {d['uncertain_or_pending']} uncertain/pending")
        p(f"  unresolved findings: {len(rep['unresolved'])}")
    else:
        p("  No TB-Profiler results yet: run TB-Profiler and import the JSON files to continue.")
    m = o.metrics()
    p(f"\nTrust signals: {m['decisions']} decisions · escalation rate {m['escalation_rate_pct']}% · tool calls {m['tool_calls']}")


if __name__ == "__main__":
    main()
