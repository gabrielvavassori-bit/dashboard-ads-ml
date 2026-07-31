import argparse
import json

import db


def _row_to_dict(row):
    if not row:
        return None
    return {key: row[key] for key in row.keys()}


def _normalize_link(email: str, client_id: str, ml_user_id: str, nickname: str, official_store: str,
                    advertiser_id: str, seller_id: str, site_id: str, status: str = "active"):
    user = db.get_user_by_email(email)
    if not user:
        raise SystemExit(f"Usuario nao encontrado: {email}")
    conn = db.get_conn()
    try:
        ts = db.now()
        rows = conn.execute(
            "SELECT id FROM user_ml_links WHERE user_id=? ORDER BY id ASC",
            (user["id"],),
        ).fetchall()
        if rows:
            keep_id = rows[0]["id"]
            conn.execute(
                """UPDATE user_ml_links
                   SET client_id=?,
                       ml_user_id=?,
                       nickname=?,
                       official_store=?,
                       advertiser_id=?,
                       seller_id=?,
                       site_id=?,
                       status=?,
                       updated_at=?,
                       last_verified_at=?
                   WHERE id=?""",
                (
                    client_id,
                    ml_user_id,
                    nickname,
                    official_store,
                    advertiser_id,
                    seller_id,
                    site_id,
                    status,
                    ts,
                    ts,
                    keep_id,
                ),
            )
            extra_ids = [row["id"] for row in rows[1:]]
            if extra_ids:
                placeholders = ",".join("?" for _ in extra_ids)
                conn.execute(
                    f"DELETE FROM user_ml_links WHERE id IN ({placeholders})",
                    tuple(extra_ids),
                )
        else:
            conn.execute(
                """INSERT INTO user_ml_links
                   (user_id, client_id, ml_user_id, nickname, official_store,
                    advertiser_id, seller_id, site_id, status, created_at, updated_at, last_verified_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user["id"],
                    client_id,
                    ml_user_id,
                    nickname,
                    official_store,
                    advertiser_id,
                    seller_id,
                    site_id,
                    status,
                    ts,
                    ts,
                    ts,
                ),
            )
        db.log_audit(user["id"], f"ops_force_ml_link.normalize:{client_id}", advertiser_id or ml_user_id)
    finally:
        conn.close()
    return user


def inspect(email: str):
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


def force_bind(email: str, client_id: str, ml_user_id: str, nickname: str, official_store: str,
               advertiser_id: str, seller_id: str, site_id: str):
    _normalize_link(
        email=email,
        client_id=client_id,
        ml_user_id=ml_user_id,
        nickname=nickname,
        official_store=official_store,
        advertiser_id=advertiser_id,
        seller_id=seller_id,
        site_id=site_id,
    )
    inspect(email)


def verify(email: str, client_id: str, ml_user_id: str, advertiser_id: str):
    user = db.get_user_by_email(email)
    if not user:
        raise SystemExit(f"Usuario nao encontrado: {email}")
    link = db.get_active_ml_link_for_user(user["id"])
    if not link:
        raise SystemExit(f"Vinculo ML nao encontrado para: {email}")
    if client_id and (link["client_id"] or "") != client_id:
        raise SystemExit(f"client_id divergente: esperado={client_id} atual={link['client_id']}")
    if ml_user_id and str(link["ml_user_id"] or "") != str(ml_user_id):
        raise SystemExit(f"ml_user_id divergente: esperado={ml_user_id} atual={link['ml_user_id']}")
    if advertiser_id and str(link["advertiser_id"] or "") != str(advertiser_id):
        raise SystemExit(f"advertiser_id divergente: esperado={advertiser_id} atual={link['advertiser_id']}")
    inspect(email)


def main():
    db.init_db()
    parser = argparse.ArgumentParser(description="Normaliza ou verifica o vínculo ML de um usuário em produção.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--email", required=True)

    bind_parser = subparsers.add_parser("force-bind")
    bind_parser.add_argument("--email", required=True)
    bind_parser.add_argument("--client-id", required=True)
    bind_parser.add_argument("--ml-user-id", default="")
    bind_parser.add_argument("--nickname", default="")
    bind_parser.add_argument("--official-store", default="")
    bind_parser.add_argument("--advertiser-id", default="")
    bind_parser.add_argument("--seller-id", default="")
    bind_parser.add_argument("--site-id", default="MLB")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--email", required=True)
    verify_parser.add_argument("--client-id", default="")
    verify_parser.add_argument("--ml-user-id", default="")
    verify_parser.add_argument("--advertiser-id", default="")

    args = parser.parse_args()
    email = args.email.strip().lower()
    if args.command == "inspect":
        inspect(email)
        return
    if args.command == "verify":
        verify(
            email=email,
            client_id=(args.client_id or "").strip(),
            ml_user_id=(args.ml_user_id or "").strip(),
            advertiser_id=(args.advertiser_id or "").strip(),
        )
        return
    force_bind(
        email=email,
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
