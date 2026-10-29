"""Shared pytest fixtures.

Two kinds of tests live in this suite:
- Fast unit/integration tests use TestClient directly against FastAPI (no server, no browser).
  These are the default `pytest` run.
- UI tests (@pytest.mark.ui) need a running uvicorn + a built frontend/dist, served from one port
  so Playwright can navigate to it. The `live_server` fixture below spins uvicorn up on a free
  port in a background thread per test session, pointing it at an isolated temp SQLite file
  (demo + replay mode so no network, no API key, no cross-test leakage).
"""
import os
import socket
import tempfile
import threading
import time
import urllib.request
from contextlib import closing

import pytest

os.environ.setdefault("TBAMR_NO_APP", "1")


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(url: str, timeout: float = 15.0) -> None:
    end = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1).read()
            return
        except Exception as e:
            last_err = e
            time.sleep(0.2)
    raise RuntimeError(f"server at {url} never became ready: {last_err}")


@pytest.fixture(scope="session")
def live_server():
    """Start uvicorn against a fresh demo-mode orchestrator in a background thread; yield the
    base URL. Shuts down on session teardown. Isolated TBAMR_DB so this never touches the user's
    tbamr-demo.db / tbamr-harness.db files on disk."""
    import uvicorn

    from tbamr.api import build_orchestrator, create_app

    tmp = tempfile.NamedTemporaryFile(prefix="tbamr-uitest-", suffix=".db", delete=False)
    tmp.close()
    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    app = create_app(build_orchestrator("demo", "replay", tmp.name))
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, name="tbamr-uitest-uvicorn", daemon=True)
    thread.start()
    try:
        _wait_ready(f"{url}/api/state")
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@pytest.fixture
def reset_demo(live_server):
    """Reset the live_server's orchestrator back to a clean demo-mode state before each UI test."""
    import json

    req = urllib.request.Request(f"{live_server}/api/reset?data=demo", method="POST")
    urllib.request.urlopen(req, timeout=5).read()
    # Sanity-check: fresh demo, nothing seeded.
    with urllib.request.urlopen(f"{live_server}/api/state", timeout=5) as r:
        snap = json.load(r)
    assert snap["mode"]["data"] == "demo"
    assert snap["state"]["stage_status"]["1"] == "ready"
    return snap
