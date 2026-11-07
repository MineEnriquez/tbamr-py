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
    # The Start hero exposes a large textarea labelled "Research question" and a #start-country dropdown.
    assert page.locator('textarea[aria-label="Research question"]').is_visible()
    assert page.locator('#start-country').is_visible()
    # The Flow's 'start' chip is now a real button and marked current (cur) when view=0.
    start_chip = page.locator('button.fnode.cap.clickable').first
    assert start_chip.is_visible()
    assert 'cur' in (start_chip.get_attribute('class') or '')


def test_mode_switch_toggles_demo_to_live_and_back(page, live_server, reset_demo):
    """The Data picker in the banner shows Demo and Live side by side; choosing one must flip the backend mode
    and move the selection."""
    page.on("dialog", lambda d: d.accept())  # auto-accept the "This resets the pipeline" confirm
    page.goto(f"{live_server}/", wait_until="networkidle")
    group = page.locator('[role="radiogroup"][aria-labelledby="data-l"]')
    assert group.count() == 1, "data-mode picker should be rendered exactly once in the banner"
    demo, live = group.get_by_role("radio", name="Demo"), group.get_by_role("radio", name="Live · ENA")
    assert demo.get_attribute("aria-checked") == "true" and live.get_attribute("aria-checked") == "false"

    live.click()
    page.wait_for_function("document.querySelector('[aria-labelledby=data-l] [aria-checked=true]').textContent.startsWith('Live')", timeout=5000)
    assert _backend_mode(live_server) == "live"

    demo.click()
    page.wait_for_function("document.querySelector('[aria-labelledby=data-l] [aria-checked=true]').textContent === 'Demo'", timeout=5000)
    assert _backend_mode(live_server) == "demo"


def test_scope_conflict_blocks_save_and_run(page, live_server, reset_demo):
    """When the question mentions one country but the Country field is set to another, the UI
    must surface a resolver banner and keep Save disabled. The 'use the field' button is a
    one-click fix that unblocks Save by stripping the alias out of the question."""
    page.goto(f"{live_server}/", wait_until="networkidle")
    page.locator('textarea[aria-label="Research question"]').fill(
        "Resistance patterns in Mycobacterium tuberculosis genomes from Indonesia."
    )
    page.locator('#start-country').select_option("Kenya")
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


def test_country_and_region_dropdowns(page, live_server, reset_demo):
    """Countries are grouped with the WHO high-burden list first; choosing one loads its regions, and the
    chosen region shows up in the resolved target population."""
    page.goto(f"{live_server}/", wait_until="networkidle")
    country = page.locator('#start-country')
    assert country.locator('optgroup[label^="High TB burden"] option[value="Indonesia"]').count() == 1
    assert page.locator('#start-region').is_disabled()  # no country yet
    country.select_option("Indonesia")
    page.wait_for_selector('#start-region option[value="West Java"]', state="attached", timeout=3000)
    page.locator('#start-region').select_option("West Java")
    page.wait_for_selector('text=Target population: Indonesia · region West Java', timeout=3000)
    country.select_option("Kenya")  # changing country clears the region
    page.wait_for_selector('#start-region option[value="Nairobi City"]', state="attached", timeout=3000)
    assert page.locator('#start-region').input_value() == ""


def test_scope_warnings_must_be_answered_and_wording_can_be_adopted(page, live_server, reset_demo):
    """Approve stays disabled until each Guardian warning is answered; the suggested wording reopens the scope."""
    import json as _json
    post = lambda path, body=None: urllib.request.urlopen(urllib.request.Request(
        f"{live_server}{path}", data=_json.dumps(body or {}).encode(), headers={"Content-Type": "application/json"}, method="POST"), timeout=10).read()
    post("/api/scope", {"question": "Which mutations are associated with rifampicin resistance across regions?", "country": "Indonesia"})
    post("/api/stages/1/run")
    page.on("dialog", lambda d: d.accept())
    page.goto(f"{live_server}/", wait_until="networkidle")
    page.get_by_role("button", name="Go to Stage 1 →").click()
    approve = page.get_by_role("button", name="Approve scope", exact=True)
    assert approve.is_disabled()
    accept = page.locator(".warn-item").get_by_role("button", name="Accept", exact=True)
    for _ in range(10):  # each answer re-renders the list, so always click the first remaining button
        if accept.count() == 0:
            break
        n = accept.count()
        accept.first.click()
        page.wait_for_function(f"document.querySelectorAll('.warn-item .btn.primary').length < {n}", timeout=5000)
    page.wait_for_function("!document.querySelector('.gate .btn.primary').disabled", timeout=5000)
    assert page.locator(".warn-answer.accept").count() >= 1
    page.get_by_role("button", name="Use this wording and review again").click()
    page.wait_for_function("document.querySelector('textarea[aria-label=\"Research question\"]')?.value.includes('WHO-catalogued')", timeout=5000)
