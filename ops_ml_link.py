import argparse
import json

import db


def _row_to_dict(row):
    if not row:
        return None
    return {key: row[key] for key in row.keys()}


def inspect_user(email: str):
    user = db.get_user_by_email(email)
    link = db.get_active_ml_link_for_user(user["id"]) if user else None
    print(
        json.dumps(
            {
                "ok": True,
                "email": email,
                "user": _row_to_dict(user),
                "active_ml_link": _row_to_dict(link),
            },
            ensure_ascii=False,
        )
    )


def bind_user(
    email: str,
    client_id: str,
    ml_user_id: str,
    nickname: str,
    official_store: str,
    advertiser_id: str,
    seller_id: str,
    site_id: str,
):
    user = db.get_user_by_email(email)
    if not user:
        raise SystemExit(f"Usuário não encontrado: {email}")

    db.upsert_user_ml_link(
        user["id"],
        client_id=client_id,
        ml_user_id=ml_user_id,
        nickname=nickname,
        official_store=official_store,
        advertiser_id=advertiser_id,
        seller_id=seller_id,
        site_id=site_id,
        status="active",
    )
    inspect_user(email)


def main():
    parser = argparse.ArgumentParser(description="Inspeciona ou vincula user_ml_links por email.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--email", required=True)

    bind_parser = subparsers.add_parser("bind")
    bind_parser.add_argument("--email", required=True)
    bind_parser.add_argument("--client-id", required=True)
    bind_parser.add_argument("--ml-user-id", default="")
    bind_parser.add_argument("--nickname", default="")
    bind_parser.add_argument("--official-store", default="")
    bind_parser.add_argument("--advertiser-id", default="")
    bind_parser.add_argument("--seller-id", default="")
    bind_parser.add_argument("--site-id", default="MLB")

    args = parser.parse_args()
    if args.command == "inspect":
        inspect_user(args.email.strip().lower())
        return
    bind_user(
        email=args.email.strip().lower(),
        client_id=args.client_id.strip(),
        ml_user_id=args.ml_user_id.strip(),
        nickname=args.nickname.strip(),
        official_store=args.official_store.strip(),
        advertiser_id=args.advertiser_id.strip(),
        seller_id=args.seller_id.strip(),
        site_id=args.site_id.strip(),
    )


if __name__ == "__main__":
    main()
