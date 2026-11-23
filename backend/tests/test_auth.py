"""Sign-in and admin-managed permissions (issue #47). Runs the API with TBAMR_AUTH=on against a temp users file."""
import pytest
from fastapi.testclient import TestClient

from tbamr.api import build_orchestrator, create_app
from tbamr.core import auth

PW = "correct-horse-1"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("TBAMR_AUTH", "on")
    monkeypatch.setenv("TBAMR_USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("TBAMR_SECRET_FILE", str(tmp_path / "secret.key"))
    monkeypatch.setenv("TBAMR_DB", str(tmp_path / "a.db"))
    auth._fails.clear()
    auth.create_user("Root", PW, [], admin=True)
    auth.create_user("Ana", PW, ["pi"])
    auth.create_user("Citra", PW, ["deputy", "tbexpert"])
    auth.create_user("Budi", PW, ["analyst"])
    o = build_orchestrator("demo", "replay", str(tmp_path / "a.db"))
    o.state.country = "Indonesia"
    return create_app(o)


def client(app, name=None):
    c = TestClient(app)
    if name:
        r = c.post("/api/auth/login", json={"name": name, "password": PW})
        assert r.status_code == 200, r.text
    return c


def test_everything_needs_a_session(app):
    c = client(app)
    assert c.get("/api/auth/status").json() == {"enabled": True, "user": None}
    for method, path in [("get", "/api/state"), ("post", "/api/stages/1/run"), ("post", "/api/reset"),
                         ("post", "/api/admin/cache/clear-all"), ("get", "/api/admin/users")]:
        assert getattr(c, method)(path).status_code == 401, path


def test_wrong_password_and_lockout(app):
    c = client(app)
    for _ in range(auth.MAX_FAILS):
        assert c.post("/api/auth/login", json={"name": "Ana", "password": "nope-nope-nope"}).status_code == 401
    r = c.post("/api/auth/login", json={"name": "Ana", "password": PW})
    assert r.status_code == 401 and "Too many" in r.json()["detail"]


def test_session_cookie_is_httponly_strict(app):
    r = TestClient(app).post("/api/auth/login", json={"name": "Ana", "password": PW})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_tampered_cookie_rejected(app):
    c = client(app, "Budi")
    tok = c.cookies.get(auth.COOKIE)
    body, sig = tok.rsplit(".", 1)
    forged = auth.issue_token({"name": "Root", "epoch": 0}).rsplit(".", 1)[0] + "." + sig  # someone else's payload, Budi's signature
    c.cookies.set(auth.COOKIE, forged)
    assert c.get("/api/state").status_code == 401


def test_cannot_claim_unassigned_role(app):
    c = client(app, "Budi")  # analyst only
    c.post("/api/stages/1/run")
    r = c.post("/api/gates/scope", json={"role": "pi", "person": "Ana"})
    assert r.status_code == 403 and "not assigned" in r.json()["detail"]
    assert client(app, "Budi").post("/api/admin/rules", json={"role": "pi", "changes": {"min_cov": 25}, "rationale": "x"}).status_code == 403


def test_person_comes_from_session_not_request(app):
    c = client(app, "Ana")
    c.post("/api/stages/1/run")
    c.get("/api/raw/scope/guardian", params={"role": "pi"})
    for i, _ in enumerate(c.get("/api/state").json()["state"]["scope"].get("warnings", [])):
        c.post(f"/api/scope/warnings/{i}", json={"role": "pi", "person": "Somebody Else", "decision": "accept"})
    assert c.post("/api/gates/scope", json={"role": "pi", "person": "Somebody Else"}).status_code == 200
    humans = [d for d in c.get("/api/decisions").json() if d["actor"].startswith("human:")]
    assert humans and all(d["actor"] == "human:pi:Ana" for d in humans)


def _pending_override(app):
    ana = client(app, "Ana")
    ana.post("/api/stages/1/run")
    for i, _ in enumerate(ana.get("/api/state").json()["state"]["scope"].get("warnings", [])):
        ana.post(f"/api/scope/warnings/{i}", json={"role": "pi", "decision": "accept"})
    assert ana.post("/api/gates/scope", json={"role": "pi"}).status_code == 200
    assert ana.post("/api/stages/2/run").status_code == 200
    r = ana.post("/api/overrides", json={"role": "pi", "run": "DEMO-R15", "field": "eligibility", "to": "Verified", "rationale": "Origin confirmed"})
    assert r.status_code == 200 and r.json()["applied"] is False, r.text
    return ana, r.json()["pending"]["id"]


def test_cosign_needs_a_different_signed_in_person(app):
    ana, oid = _pending_override(app)
    assert ana.post("/api/overrides/cosign", json={"role": "pi", "person": "Citra", "override_id": oid}).status_code == 403
    budi = client(app, "Budi")  # different person, but analysts don't own eligibility overrides
    assert budi.post("/api/overrides/cosign", json={"role": "analyst", "override_id": oid}).status_code == 403
    citra = client(app, "Citra")
    assert citra.post("/api/overrides/cosign", json={"role": "deputy", "override_id": oid}).status_code == 200


def test_admin_manages_users_and_changes_apply_immediately(app):
    root, budi = client(app, "Root"), client(app, "Budi")
    assert budi.get("/api/admin/users").status_code == 403
    assert root.post("/api/admin/users", json={"name": "Dewi", "password": "short", "roles": ["pi"]}).status_code == 400
    assert root.post("/api/admin/users", json={"name": "Dewi", "password": PW, "roles": ["wizard"]}).status_code == 400
    assert root.post("/api/admin/users", json={"name": "Dewi", "password": PW, "roles": ["tbexpert"]}).status_code == 200
    # give Budi the PI role: his existing session can use it at once
    assert root.patch("/api/admin/users/Budi", json={"roles": ["analyst", "pi"]}).status_code == 200
    budi.post("/api/stages/1/run")
    assert budi.get("/api/raw/receipts", params={"role": "pi"}).status_code == 200
    # disabling ends his session
    assert root.patch("/api/admin/users/budi", json={"disabled": True}).status_code == 200
    assert budi.get("/api/state").status_code == 401
    h = root.get("/api/admin/users").json()["history"]
    assert [e["action"] for e in h[:3]] == ["update", "update", "create"] and h[0]["by"] == "Root"


def test_last_admin_cannot_be_removed(app):
    root = client(app, "Root")
    r = root.patch("/api/admin/users/Root", json={"admin": False})
    assert r.status_code == 400 and "admin must remain" in r.json()["detail"]


def test_password_reset_signs_out_old_sessions(app):
    ana, root = client(app, "Ana"), client(app, "Root")
    assert root.post("/api/admin/users/Ana/password", json={"password": "a-brand-new-pw"}).status_code == 200
    assert ana.get("/api/state").status_code == 401
    assert TestClient(app).post("/api/auth/login", json={"name": "ana", "password": "a-brand-new-pw"}).status_code == 200


def test_admin_only_operations(app):
    ana = client(app, "Ana")  # PI, not admin
    assert ana.post("/api/admin/cache/clear-all").status_code == 403
    assert ana.get("/api/admin/mongo").status_code == 403
    assert ana.post("/api/reset").status_code == 200  # PI may reset
    assert client(app, "Citra").post("/api/reset").status_code == 403


def test_summary_edit_needs_release_role(app):
    c = client(app, "Budi")
    assert c.put("/api/report/summary", json={"text": "x", "role": "analyst"}).status_code == 403


def test_auth_off_keeps_demo_behaviour(tmp_path, monkeypatch):
    monkeypatch.setenv("TBAMR_AUTH", "off")
    c = TestClient(create_app(build_orchestrator("demo", "replay", str(tmp_path / "b.db"))))
    assert c.get("/api/auth/status").json() == {"enabled": False, "user": None}
    assert c.get("/api/state").json()["auth"] == {"enabled": False}
    # regression: the summary editor's body used to be read as a query param (always 422)
    assert c.put("/api/report/summary", json={"text": "x"}).status_code == 409  # 409 = no report yet, i.e. the body parsed
