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
        raise SystemExit(f"Usuário não encontrado: {email}")
    expires_at = None if not days else int(time.time()) + (days * 86400)
    db.set_user_access_window(user["id"], status="active", expires_at=expires_at)
    inspect_user(email)


def main():
    db.init_db()
    parser = argparse.ArgumentParser(description="Inspeciona ou libera acesso de usuário por email.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--email", required=True)

    activate_parser = subparsers.add_parser("activate")
    activate_parser.add_argument("--email", required=True)
    activate_parser.add_argument("--days", type=int, default=0)

    args = parser.parse_args()
    email = args.email.strip().lower()
    if args.command == "inspect":
        inspect_user(email)
        return
    activate_user(email, args.days)


if __name__ == "__main__":
    main()
