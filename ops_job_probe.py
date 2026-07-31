import argparse
import json
import os
import pathlib
import time
import traceback

import db


def _row_to_dict(row):
    if not row:
        return None
    return {key: row[key] for key in row.keys()}


def main():
    parser = argparse.ArgumentParser(description="Diagnostico minimo de jobs Render para Dash Ads.")
    parser.add_argument("--email", default="")
    parser.add_argument("--mode", choices=("inspect", "activate", "bind"), default="inspect")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--client-id", default="")
    parser.add_argument("--ml-user-id", default="")
    parser.add_argument("--nickname", default="")
    parser.add_argument("--official-store", default="")
    parser.add_argument("--advertiser-id", default="")
    parser.add_argument("--seller-id", default="")
    parser.add_argument("--site-id", default="MLB")
    parser.add_argument("--sleep", type=int, default=8)
    args = parser.parse_args()

    report = {
        "ok": True,
        "mode": args.mode,
        "email": (args.email or "").strip().lower(),
        "cwd": os.getcwd(),
        "data_dir_env": os.environ.get("DATA_DIR", ""),
        "db_candidates": [],
        "user_before": None,
        "user_after": None,
        "link_after": None,
        "error": None,
        "traceback": None,
    }

    for candidate in (
        pathlib.Path("dashboard_ads_ml.db"),
        pathlib.Path("./data/dashboard_ads_ml.db"),
        pathlib.Path(os.environ.get("DATA_DIR", "")) / "dashboard_ads_ml.db" if os.environ.get("DATA_DIR") else None,
    ):
        if candidate is None:
            continue
        report["db_candidates"].append(
            {
                "path": str(candidate),
                "exists": candidate.exists(),
            }
        )

    try:
        db.init_db()
        if report["email"]:
            user = db.get_user_by_email(report["email"])
            report["user_before"] = _row_to_dict(user)
            if args.mode == "activate":
                if not user:
                    raise RuntimeError(f"Usuario nao encontrado: {report['email']}")
                expires_at = int(time.time()) + (args.days * 86400)
                db.set_user_access_window(user["id"], status="active", expires_at=expires_at)
            elif args.mode == "bind":
                if not user:
                    raise RuntimeError(f"Usuario nao encontrado: {report['email']}")
                db.upsert_user_ml_link(
                    user["id"],
                    client_id=(args.client_id or "").strip(),
                    ml_user_id=(args.ml_user_id or "").strip(),
                    nickname=(args.nickname or "").strip(),
                    official_store=(args.official_store or "").strip(),
                    advertiser_id=(args.advertiser_id or "").strip(),
                    seller_id=(args.seller_id or "").strip(),
                    site_id=((args.site_id or "MLB").strip() or "MLB").upper(),
                    status="active",
                )
            user_after = db.get_user_by_email(report["email"])
            report["user_after"] = _row_to_dict(user_after)
            if user_after:
                report["link_after"] = _row_to_dict(db.get_active_ml_link_for_user(user_after["id"]))
    except Exception as exc:
        report["ok"] = False
        report["error"] = f"{exc.__class__.__name__}: {exc}"
        report["traceback"] = traceback.format_exc()

    print(json.dumps(report, ensure_ascii=False))
    time.sleep(max(args.sleep, 0))


if __name__ == "__main__":
    main()
