"""Sign-in, sessions, and admin-managed user permissions.

Off by default so the offline demo keeps its "Acting as" switcher. Turn it on with TBAMR_AUTH=on:
then every /api call needs a signed-in session, the person on every decision is the signed-in user
(never a name typed into a request), and a user can only act in the roles an admin assigned them.

- Users live in their own JSON file (TBAMR_USERS_FILE, default backend/tbamr-users.json) so a
  pipeline reset can't wipe them. Passwords are stored as scrypt hashes, never in clear.
- A session is an HMAC-signed, HttpOnly cookie carrying the user name, an expiry, and the user's
  session epoch. Changing a password, disabling an account or signing out everywhere bumps the
  epoch, which invalidates every cookie issued before. The signing key comes from TBAMR_SECRET or
  is generated once into TBAMR_SECRET_FILE (default backend/tbamr-secret.key).
- Admin is an account flag, separate from the four pipeline roles. Admins create users, reset
  passwords, assign roles and disable accounts. Every change is kept in an audit history.
- Repeated wrong passwords lock that account name out for a while.

Bootstrap the first admin from the command line:  python -m tbamr.users create-admin <name>
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from .models import ROLES

log = logging.getLogger("tbamr.auth")

COOKIE = "tbamr_session"
SESSION_TTL = int(os.environ.get("TBAMR_SESSION_HOURS", "12")) * 3600
MIN_PASSWORD = 10
MAX_FAILS, LOCKOUT_S = 5, 300
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._'-]{0,47}$")

_lock = threading.RLock()
_fails: dict[str, list[float]] = {}  # lower-case name -> recent failure times (in memory)


class AuthError(Exception):
    """Not signed in, or the session is no longer valid (HTTP 401)."""


class Forbidden(Exception):
    """Signed in, but not allowed to do this (HTTP 403)."""


class UserError(ValueError):
    """Invalid user-management input (HTTP 400)."""


def enabled() -> bool:
    return os.environ.get("TBAMR_AUTH", "off").strip().lower() in ("1", "on", "true", "yes")


# ------------------------------------------------------------------ storage
def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _path() -> Path:
    return Path(os.environ.get("TBAMR_USERS_FILE") or _backend_dir() / "tbamr-users.json")


def _read() -> dict[str, Any]:
    p = _path()
    if not p.exists():
        return {"users": {}, "history": []}
    d = json.loads(p.read_text())  # a corrupt users file must fail loudly, not silently open the door
    d.setdefault("users", {}); d.setdefault("history", [])
    return d


def _write(d: dict[str, Any]) -> None:
    p = _path()
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(d, indent=1))
    tmp.replace(p)


def _secret() -> bytes:
    env = os.environ.get("TBAMR_SECRET")
    if env:
        return env.encode()
    p = Path(os.environ.get("TBAMR_SECRET_FILE") or _backend_dir() / "tbamr-secret.key")
    with _lock:
        if not p.exists():
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_hex(32))
        return p.read_text().strip().encode()


# ------------------------------------------------------------------ passwords
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def _check_password(pw: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(s), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password(secrets.token_hex(8))  # so unknown names cost the same time as wrong passwords


def _validate_password(pw: str) -> None:
    if len(pw or "") < MIN_PASSWORD:
        raise UserError(f"Passwords need at least {MIN_PASSWORD} characters.")


# ------------------------------------------------------------------ users
def _key(name: str) -> str:
    return (name or "").strip().lower()


def public(u: dict[str, Any]) -> dict[str, Any]:
    return {"name": u["name"], "roles": list(u.get("roles", [])), "admin": bool(u.get("admin")),
            "disabled": bool(u.get("disabled")), "created": u.get("created")}


def get_user(name: str) -> dict[str, Any] | None:
    with _lock:
        u = _read()["users"].get(_key(name))
        return copy.deepcopy(u) if u else None


def list_users() -> list[dict[str, Any]]:
    with _lock:
        return [public(u) for _, u in sorted(_read()["users"].items())]


def history(limit: int = 100) -> list[dict[str, Any]]:
    with _lock:
        return _read()["history"][-limit:][::-1]


def _clean_roles(roles: list[str] | None) -> list[str]:
    roles = list(dict.fromkeys(roles or []))
    bad = [r for r in roles if r not in ROLES]
    if bad:
        raise UserError(f"Unknown role(s): {', '.join(bad)}. Choose from {', '.join(ROLES)}.")
    return roles


def _audit(d: dict[str, Any], by: str, action: str, target: str, detail: dict[str, Any]) -> None:
    entry = {"ts": time.time(), "by": by, "action": action, "user": target, "detail": detail}
    d["history"].append(entry)
    log.info("user admin: %s %s %s %s", by, action, target, detail)


def create_user(name: str, password: str, roles: list[str] | None = None, admin: bool = False, by: str = "cli") -> dict[str, Any]:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise UserError("Names are 1-48 characters: letters, digits, spaces and . _ ' -")
    _validate_password(password)
    roles = _clean_roles(roles)
    with _lock:
        d = _read()
        if _key(name) in d["users"]:
            raise UserError(f"A user named {name!r} already exists.")
        d["users"][_key(name)] = {"name": name, "pw": hash_password(password), "roles": roles, "admin": bool(admin),
                                  "disabled": False, "epoch": 0, "created": time.time()}
        _audit(d, by, "create", name, {"roles": roles, "admin": bool(admin)})
        _write(d)
        return public(d["users"][_key(name)])


def _active_admins(d: dict[str, Any]) -> list[str]:
    return [k for k, u in d["users"].items() if u.get("admin") and not u.get("disabled")]


def update_user(name: str, by: str, roles: list[str] | None = None, admin: bool | None = None,
                disabled: bool | None = None) -> dict[str, Any]:
    with _lock:
        d = _read()
        u = d["users"].get(_key(name))
        if not u:
            raise UserError(f"No user named {name!r}.")
        detail: dict[str, Any] = {}
        if roles is not None:
            roles = _clean_roles(roles)
            if roles != u.get("roles", []):
                detail["roles"] = {"from": u.get("roles", []), "to": roles}
                u["roles"] = roles
        if admin is not None and bool(admin) != bool(u.get("admin")):
            detail["admin"] = {"from": bool(u.get("admin")), "to": bool(admin)}
            u["admin"] = bool(admin)
        if disabled is not None and bool(disabled) != bool(u.get("disabled")):
            detail["disabled"] = {"from": bool(u.get("disabled")), "to": bool(disabled)}
            u["disabled"] = bool(disabled)
            if disabled:
                u["epoch"] = u.get("epoch", 0) + 1  # sign them out everywhere
        if not detail:
            raise UserError("Nothing changed.")
        if not _active_admins(d):
            raise UserError("At least one active admin must remain, or nobody could manage users.")
        _audit(d, by, "update", u["name"], detail)
        _write(d)
        return public(u)


def set_password(name: str, password: str, by: str) -> None:
    _validate_password(password)
    with _lock:
        d = _read()
        u = d["users"].get(_key(name))
        if not u:
            raise UserError(f"No user named {name!r}.")
        u["pw"] = hash_password(password)
        u["epoch"] = u.get("epoch", 0) + 1  # old sessions stop working
        _audit(d, by, "password" if _key(by) == _key(name) else "password-reset", u["name"], {})
        _write(d)


def sign_out_everywhere(name: str) -> None:
    with _lock:
        d = _read()
        u = d["users"].get(_key(name))
        if u:
            u["epoch"] = u.get("epoch", 0) + 1
            _write(d)


# ------------------------------------------------------------------ sign-in and sessions
def authenticate(name: str, password: str) -> dict[str, Any]:
    k = _key(name)
    now = time.time()
    with _lock:
        recent = [t for t in _fails.get(k, []) if now - t < LOCKOUT_S]
        _fails[k] = recent
        if len(recent) >= MAX_FAILS:
            raise AuthError(f"Too many failed sign-ins for this name. Try again in {int(LOCKOUT_S - (now - recent[0])) + 1} s.")
    u = get_user(name)
    ok = _check_password(password or "", u["pw"] if u else _DUMMY_HASH) and bool(u)
    if not ok or u.get("disabled"):
        with _lock:
            _fails.setdefault(k, []).append(now)
        log.warning("failed sign-in for %r", name)
        raise AuthError("Wrong name or password, or the account is disabled.")
    with _lock:
        _fails.pop(k, None)
    log.info("sign-in: %s", u["name"])
    return u


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def issue_token(u: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"n": _key(u["name"]), "e": u.get("epoch", 0),
                                                "x": int(time.time()) + SESSION_TTL}).encode()).decode()
    return body + "." + _sign(body)


def user_from_token(token: str | None) -> dict[str, Any]:
    """The current user for a session cookie, or AuthError. Re-reads the users file every call, so a
    role change applies at once and a disabled account or reset password ends its sessions."""
    if not token or "." not in token:
        raise AuthError("Sign in to continue.")
    body, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(body)):
        raise AuthError("Your session is not valid. Sign in again.")
    try:
        p = json.loads(base64.urlsafe_b64decode(body.encode()))
    except ValueError:
        raise AuthError("Your session is not valid. Sign in again.")
    if p.get("x", 0) < time.time():
        raise AuthError("Your session has expired. Sign in again.")
    u = get_user(p.get("n", ""))
    if not u or u.get("disabled") or u.get("epoch", 0) != p.get("e"):
        raise AuthError("Your session has ended. Sign in again.")
    return u


def act_as(u: dict[str, Any], role: str) -> tuple[str, str]:
    """(role, person) for a signed-in user acting in `role`. The person is always the account name."""
    if role not in u.get("roles", []):
        held = ", ".join(ROLES[r] for r in u.get("roles", [])) or "no roles yet; ask an admin"
        raise Forbidden(f"{u['name']} is not assigned the {ROLES.get(role, role)} role (assigned: {held}).")
    return role, u["name"]
