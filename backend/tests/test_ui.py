"""UI (Playwright) tests. Run only when the `ui` marker is selected:

    pytest -m ui                 # just the UI tests
    pytest -m 'ui or not ui'     # the full suite (default `pytest` skips ui tests)

Prerequisites once:
    pip install -r requirements-dev.txt
    playwright install chromium

The `live_server` session fixture (conftest.py) boots uvicorn against a fresh demo-mode
orchestrator in a temp DB. The `reset_demo` fixture clears the pipeline between tests. All tests
run offline: demo data + replay client — no ENA calls, no ANTHROPIC_API_KEY needed.
"""
import json
import urllib.request

import pytest

pytestmark = pytest.mark.ui


def _backend_mode(base_url: str) -> str:
    with urllib.request.urlopen(f"{base_url}/api/state", timeout=5) as r:
        return json.load(r)["mode"]["data"]


def _backend_state(base_url: str) -> dict:
    with urllib.request.urlopen(f"{base_url}/api/state", timeout=5) as r:
        return json.load(r)["state"]


def test_landing_defaults_to_the_start_hero(page, live_server, reset_demo):
    """On a fresh load the user lands on the Start hero (view=0), which shows a prominent
    research-question textarea and the toggle-able 'start' chip in the Flow diagram."""
    page.goto(f"{live_server}/", wait_until="networkidle")
    # The Start hero exposes a large textarea labelled "Research question" and a #start-country input.
    assert page.locator('textarea[aria-label="Research question"]').is_visible()
    assert page.locator('#start-country').is_visible()
    # The Flow's 'start' chip is now a real button and marked current (cur) when view=0.
    start_chip = page.locator('button.fnode.cap.clickable').first
    assert start_chip.is_visible()
    assert 'cur' in (start_chip.get_attribute('class') or '')


def test_mode_switch_toggles_demo_to_live_and_back(page, live_server, reset_demo):
    """Clicking the data-mode toggle in the banner must flip the backend mode AND the UI label.
    This is the exact UX the user reported as 'not working'; failing here would prove the symptom."""
    page.on("dialog", lambda d: d.accept())  # auto-accept the "This resets the pipeline" confirm
    page.goto(f"{live_server}/", wait_until="networkidle")
    switch = page.locator('button[role="switch"]')
    assert switch.count() == 1, "mode switch should be rendered exactly once in the banner"
    assert switch.get_attribute("aria-checked") == "false"
    assert "DEMO" in switch.inner_text()

    switch.click()
    page.wait_for_function("document.querySelector('button[role=switch]').getAttribute('aria-checked') === 'true'", timeout=5000)
    assert _backend_mode(live_server) == "live"
    assert "LIVE" in switch.inner_text()

    switch.click()
    page.wait_for_function("document.querySelector('button[role=switch]').getAttribute('aria-checked') === 'false'", timeout=5000)
    assert _backend_mode(live_server) == "demo"
    assert "DEMO" in switch.inner_text()


def test_scope_conflict_blocks_save_and_run(page, live_server, reset_demo):
    """When the question mentions one country but the Country field is set to another, the UI
    must surface a resolver banner and keep Save disabled. The 'use the field' button is a
    one-click fix that unblocks Save by stripping the alias out of the question."""
    page.goto(f"{live_server}/", wait_until="networkidle")
    page.locator('textarea[aria-label="Research question"]').fill(
        "Resistance patterns in Mycobacterium tuberculosis genomes from Indonesia."
    )
    page.locator('#start-country').fill("Kenya")
    # Wait for the memoised conflict to materialise.
    page.wait_for_selector('text="Country/question conflict — pick one"', timeout=3000)
    save_btn = page.get_by_role("button", name="Save scope")
    assert save_btn.is_disabled(), "Save must stay disabled while the conflict is unresolved"

    # Use the one-click 'strip from question' resolver (keeps Country=Kenya).
    page.locator('button:has-text(\'remove "indonesia"\')').click()
    page.wait_for_selector('text="Country/question conflict — pick one"', state="detached", timeout=3000)
    assert "Indonesia" not in page.locator('textarea[aria-label="Research question"]').input_value()
    assert save_btn.is_enabled()


def test_flow_start_chip_navigates_back_to_the_start_view(page, live_server, reset_demo):
    """Click Stage 1 chip to leave the Start hero, then click the Start chip to return. The
    hero's textarea must come back into the DOM; the chip must regain its 'cur' class."""
    page.goto(f"{live_server}/", wait_until="networkidle")
    assert page.locator('textarea[aria-label="Research question"]').is_visible()

    # Jump to Stage 1 via the Flow chip. The scope editor renders in Stage 1 with #scope-country,
    # not the hero's #start-country, so this proves we actually left the hero.
    page.locator('button[aria-label*="Stage 1"]').first.click()
    page.wait_for_selector('#scope-country', timeout=3000)
    assert page.locator('#start-country').count() == 0

    # Click the Start chip (the dashed cap at the left of the flow) to return.
    page.locator('button.fnode.cap.clickable').first.click()
    page.wait_for_selector('#start-country', timeout=3000)
    assert page.locator('textarea[aria-label="Research question"]').is_visible()
