"""Command-line user management (for the first admin, or when nobody can sign in).

  python -m tbamr.users create-admin <name>            create an admin (prompts for a password)
  python -m tbamr.users create <name> --roles pi,analyst
  python -m tbamr.users set-password <name>
  python -m tbamr.users list

Everything else (roles, disabling, resets) can also be done by an admin on the Admin page.
Uses TBAMR_USERS_FILE if set, otherwise backend/tbamr-users.json.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from .core import auth
from .core.models import ROLES


def _password() -> str:
    pw = getpass.getpass("Password: ")
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    return pw


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m tbamr.users", description="Manage TB-AMR sign-in accounts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("create-admin", "create"):
        p = sub.add_parser(cmd)
        p.add_argument("name")
        p.add_argument("--roles", default="", help=f"comma-separated, from: {', '.join(ROLES)}")
    sub.add_parser("set-password").add_argument("name")
    sub.add_parser("list")
    a = ap.parse_args(argv)
    try:
        if a.cmd in ("create-admin", "create"):
            roles = [r.strip() for r in a.roles.split(",") if r.strip()]
            u = auth.create_user(a.name, _password(), roles, admin=a.cmd == "create-admin", by="cli")
            print(f"Created {u['name']} (admin: {u['admin']}, roles: {', '.join(u['roles']) or 'none'}).")
        elif a.cmd == "set-password":
            if not auth.get_user(a.name):
                sys.exit(f"No user named {a.name!r}.")
            auth.set_password(a.name, _password(), by="cli")
            print("Password changed; existing sessions for this user are signed out.")
        else:
            for u in auth.list_users():
                flags = (" [admin]" if u["admin"] else "") + (" [disabled]" if u["disabled"] else "")
                print(f"{u['name']}{flags}: {', '.join(u['roles']) or 'no roles'}")
    except auth.UserError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
