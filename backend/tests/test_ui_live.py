"""UI tests that cross into LIVE ENA data. Opt-in only:

    pytest -m live

Requires network access to the ENA Portal API. These prove the end-to-end claim behind the mode
switch: toggling to LIVE and running Discovery really does return real SRR* accessions, not demo
DEMO-R* records. If you're offline (or ENA is down) this will fail — that's expected; the fast
`ui` suite covers the toggle behaviour without touching the network.
"""
import json
import time
import urllib.request

import pytest

pytestmark = [pytest.mark.ui, pytest.mark.live]


def _state(url: str) -> dict:
    with urllib.request.urlopen(f"{url}/api/state", timeout=10) as r:
        return json.load(r)["state"]


def _mode(url: str) -> str:
    with urllib.request.urlopen(f"{url}/api/state", timeout=10) as r:
        return json.load(r)["mode"]["data"]


def _wait(cond, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def test_toggle_to_live_then_discovery_returns_real_ENA_accessions(page, live_server, reset_demo):
    """The full receipt of the mode switch: flip to LIVE, define a Peru-scoped question, run the
    Scope Guardian, approve, run Discovery, and prove the samples that come back are real SRR*
    accessions (not DEMO-prefixed). If this ever regresses to demo-looking data, the switch is
    broken even though the aria-checked flag flips."""
    page.on("dialog", lambda d: d.accept())
    page.goto(f"{live_server}/", wait_until="networkidle")

    page.locator('button[role="switch"]').click()
    assert _wait(lambda: _mode(live_server) == "live"), "backend never switched to live"

    # After the reset+toggle the auto-advance pushes view 0 → 1, so the scope editor uses
    # #scope-country (not #start-country). Match either.
    page.locator('textarea[aria-label="Research question"]').fill(
        "What patterns of drug resistance can we identify in Mycobacterium tuberculosis genomes?"
    )
    page.locator('#start-country, #scope-country').first.fill("Peru")
    page.get_by_role("button", name="Save scope").click()
    assert _wait(lambda: _state(live_server)["country"] == "Peru"), "scope never saved"

    page.get_by_role("button", name="Run agents").click()
    assert _wait(lambda: _state(live_server)["stage_status"]["1"] in ("wait", "done")), "stage 1 never finished"

    page.get_by_role("button", name="Approve scope", exact=True).click()
    assert _wait(lambda: _state(live_server)["gates"].get("scope")), "scope gate never approved"

    page.locator('button[aria-label*="Stage 2"]').first.click()
    page.get_by_role("button", name="Run agents").click()
    assert _wait(lambda: _state(live_server)["stage_status"]["2"] in ("wait", "done") and _state(live_server)["samples"], timeout=180), \
        "stage 2 discovery never finished or returned no samples"

    samples = _state(live_server)["samples"]
    demo_prefixed = [s["run"] for s in samples if s["run"].startswith("DEMO") or s["run"].startswith("PRJDEMO")]
    live_prefixed = [s["run"] for s in samples if not (s["run"].startswith("DEMO") or s["run"].startswith("PRJDEMO"))]
    assert live_prefixed, f"LIVE mode returned no SRR-style accessions; got: {[s['run'] for s in samples[:5]]}"
    assert not demo_prefixed, f"LIVE mode leaked demo accessions: {demo_prefixed[:5]}"
