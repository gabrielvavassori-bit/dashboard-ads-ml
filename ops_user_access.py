import argparse
import json
import time

import db


def _row_to_dict(row):
    if not row:
        return None
    return {key: row[key] for key in row.keys()}


def inspect_user(email: str):
    user = db.get_user_by_email(email)
    print(
        json.dumps(
            {
                "ok": True,
                "email": email,
                "user": _row_to_dict(user),
            },
            ensure_ascii=False,
        )
    )


def activate_user(email: str, days: int | None):
    user = db.get_user_by_email(email)
    if not user:
        raise SystemExit(f"Usuario nao encontrado: {email}")
    expires_at = None if not days else int(time.time()) + (days * 86400)
    db.set_user_access_window(user["id"], status="active", expires_at=expires_at)
    inspect_user(email)


def ensure_manual_user(email: str, name: str, plan: str, days: int):
    if days < 1:
        raise SystemExit("Dias devem ser maiores que zero.")
    expires_at = int(time.time()) + (days * 86400)
    db.upsert_manual_user(
        email=email,
        name=name,
        plan=plan or "cortesia",
        status="active",
        expires_at=expires_at,
    )
    inspect_user(email)


def main():
    db.init_db()
    parser = argparse.ArgumentParser(description="Inspeciona ou libera acesso de usuario por email.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--email", required=True)

    activate_parser = subparsers.add_parser("activate")
    activate_parser.add_argument("--email", required=True)
    activate_parser.add_argument("--days", type=int, default=0)

    ensure_parser = subparsers.add_parser("ensure-manual")
    ensure_parser.add_argument("--email", required=True)
    ensure_parser.add_argument("--name", default="")
    ensure_parser.add_argument("--plan", default="cortesia")
    ensure_parser.add_argument("--days", type=int, default=7)

    args = parser.parse_args()
    email = args.email.strip().lower()
    if args.command == "inspect":
        inspect_user(email)
        return
    if args.command == "ensure-manual":
        ensure_manual_user(
            email=email,
            name=(args.name or "").strip(),
            plan=(args.plan or "").strip(),
            days=args.days,
        )
        return
    activate_user(email, args.days)


if __name__ == "__main__":
    main()
