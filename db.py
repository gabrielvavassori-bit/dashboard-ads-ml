"""
Camada de banco de dados (SQLite) para o app.

Tabelas:
- users          : clientes do Gabriel (vindos do webhook Eduzz)
- sessions       : sessões ativas (1 por usuário, evita compartilhamento)
- webhook_events : log idempotente de eventos da Eduzz
- admins         : credenciais do painel admin
- audit_log      : log de acessos relevantes (login, troca de senha, etc.)
"""
import os
import pathlib
import sqlite3
import threading
import time
import hashlib

# Em Render/Railway, monte um disco persistente apontando para /var/data.
# Localmente cai em ./data/app.db
_DEFAULT_DIR = pathlib.Path(os.environ.get("DATA_DIR", "./data"))
_DEFAULT_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = _DEFAULT_DIR / "app.db"

_lock = threading.Lock()


def get_conn():
    """Conexão nova por chamada. SQLite com WAL para concorrência saudável."""
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    email             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name              TEXT,
    eduzz_buyer_id    TEXT,
    eduzz_contract_id TEXT,
    access_origin     TEXT NOT NULL DEFAULT 'eduzz',
    plan              TEXT,
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending | active | suspended | refunded | expired
    expires_at        INTEGER,                          -- timestamp unix; NULL = sem expiração
    password_hash     TEXT,                             -- NULL ate o primeiro acesso
    created_at        INTEGER NOT NULL,
    updated_at        INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_email   ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_status  ON users(status);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    last_seen   INTEGER NOT NULL,
    ip          TEXT,
    user_agent  TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS webhook_events (
    event_id     TEXT PRIMARY KEY,
    event_name   TEXT NOT NULL,
    received_at  INTEGER NOT NULL,
    payload      TEXT NOT NULL,
    payload_hash TEXT,
    status       TEXT NOT NULL DEFAULT 'processed',
    processed_at INTEGER,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state_hash TEXT PRIMARY KEY,
    expires_at INTEGER NOT NULL,
    used_at    INTEGER
);

CREATE TABLE IF NOT EXISTS user_ml_links (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    client_id        TEXT NOT NULL,
    ml_user_id       TEXT,
    nickname         TEXT,
    official_store   TEXT,
    advertiser_id    TEXT,
    seller_id        TEXT,
    site_id          TEXT,
    status           TEXT NOT NULL DEFAULT 'active',
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL,
    last_verified_at INTEGER,
    UNIQUE(user_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_ml_links_client  ON user_ml_links(client_id);
CREATE INDEX IF NOT EXISTS idx_user_ml_links_status  ON user_ml_links(status);

CREATE TABLE IF NOT EXISTS ml_link_states (
    state_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    return_to   TEXT NOT NULL,
    expires_at  INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    attached_at INTEGER,
    used_at     INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS admins (
    email         TEXT PRIMARY KEY COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    action     TEXT NOT NULL,
    detail     TEXT,
    ip         TEXT,
    created_at INTEGER NOT NULL
);
"""


def init_db():
    """Cria as tabelas se ainda não existirem. Idempotente."""
    with _lock:
        conn = get_conn()
        try:
            conn.executescript(SCHEMA)
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(webhook_events)")
            }
            migrations = {
                "payload_hash": "ALTER TABLE webhook_events ADD COLUMN payload_hash TEXT",
                "status": (
                    "ALTER TABLE webhook_events ADD COLUMN status "
                    "TEXT NOT NULL DEFAULT 'processed'"
                ),
                "processed_at": "ALTER TABLE webhook_events ADD COLUMN processed_at INTEGER",
                "error": "ALTER TABLE webhook_events ADD COLUMN error TEXT",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    conn.execute(statement)
            conn.execute(
                """UPDATE webhook_events
                   SET status='processed',
                       processed_at=COALESCE(processed_at, received_at)
                   WHERE status IS NULL OR status=''"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_webhook_events_status
                   ON webhook_events(status)"""
            )
            user_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(users)")
            }
            if "access_origin" not in user_columns:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN access_origin TEXT NOT NULL DEFAULT 'eduzz'"
                )
                conn.execute(
                    """UPDATE users
                       SET access_origin=CASE
                         WHEN COALESCE(eduzz_buyer_id,'')<>'' OR COALESCE(eduzz_contract_id,'')<>'' THEN 'eduzz'
                         ELSE 'manual'
                       END"""
                )
        finally:
            conn.close()


def now() -> int:
    return int(time.time())


# ---------- USERS ----------

def upsert_user_from_webhook(
    email: str,
    name: str,
    buyer_id: str,
    contract_id: str,
    plan: str,
    status: str,
    expires_at,
):
    """Cria ou atualiza um usuário a partir de um evento da Eduzz."""
    email = (email or "").strip().lower()
    if not email:
        return None
    conn = get_conn()
    try:
        cur = conn.execute("SELECT id, access_origin FROM users WHERE email=?", (email,))
        row = cur.fetchone()
        ts = now()
        if row:
            access_origin = "manual_promoted_eduzz" if row["access_origin"] == "manual" else "eduzz"
            conn.execute(
                """UPDATE users
                   SET name=COALESCE(?, name),
                       eduzz_buyer_id=COALESCE(?, eduzz_buyer_id),
                       eduzz_contract_id=COALESCE(?, eduzz_contract_id),
                       access_origin=?,
                       plan=COALESCE(?, plan),
                       status=?,
                       expires_at=?,
                       updated_at=?
                   WHERE id=?""",
                (name, buyer_id, contract_id, access_origin, plan, status, expires_at, ts, row["id"]),
            )
            return row["id"]
        else:
            cur = conn.execute(
                """INSERT INTO users
                   (email, name, eduzz_buyer_id, eduzz_contract_id, access_origin, plan, status, expires_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (email, name, buyer_id, contract_id, "eduzz", plan, status, expires_at, ts, ts),
            )
            return cur.lastrowid
    finally:
        conn.close()


def upsert_manual_user(
    email: str,
    name: str = "",
    plan: str = "",
    status: str = "active",
    expires_at=None,
):
    """Cria ou atualiza um usuario manualmente pelo painel admin."""
    email = (email or "").strip().lower()
    if not email:
        return None
    name = (name or "").strip()
    plan = (plan or "").strip()
    conn = get_conn()
    try:
        cur = conn.execute("SELECT id FROM users WHERE email=?", (email,))
        row = cur.fetchone()
        ts = now()
        if row:
            conn.execute(
                """UPDATE users
                   SET name=?,
                       access_origin='manual',
                       plan=?,
                       status=?,
                       expires_at=?,
                       updated_at=?
                   WHERE id=?""",
                (name or None, plan or None, status, expires_at, ts, row["id"]),
            )
            return row["id"]
        cur = conn.execute(
            """INSERT INTO users
               (email, name, access_origin, plan, status, expires_at, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (email, name or None, "manual", plan or None, status, expires_at, ts, ts),
        )
        return cur.lastrowid
    finally:
        conn.close()


def _expire_overdue_active_users(conn, where_clause: str = "", params=()):
    """Normaliza usuarios ativos que ja passaram da data de expiracao."""
    sql = (
        "UPDATE users "
        "SET status='expired', updated_at=? "
        "WHERE status='active' "
        "AND expires_at IS NOT NULL "
        "AND expires_at > 0 "
        "AND expires_at < ?"
    )
    sql_params = [now(), now()]
    if where_clause:
        sql += f" AND {where_clause}"
        sql_params.extend(params)
    conn.execute(sql, tuple(sql_params))


def get_user_by_email(email: str):
    if not email:
        return None
    conn = get_conn()
    try:
        normalized_email = email.strip().lower()
        _expire_overdue_active_users(conn, "email=?", (normalized_email,))
        cur = conn.execute("SELECT * FROM users WHERE email=?", (normalized_email,))
        return cur.fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id: int):
    conn = get_conn()
    try:
        _expire_overdue_active_users(conn, "id=?", (user_id,))
        cur = conn.execute("SELECT * FROM users WHERE id=?", (user_id,))
        return cur.fetchone()
    finally:
        conn.close()


def get_active_ml_link_for_user(user_id: int):
    conn = get_conn()
    try:
        cur = conn.execute(
            """SELECT * FROM user_ml_links
               WHERE user_id=? AND status='active'
               ORDER BY updated_at DESC LIMIT 1""",
            (user_id,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def upsert_user_ml_link(
    user_id: int,
    client_id: str,
    ml_user_id: str = "",
    nickname: str = "",
    official_store: str = "",
    advertiser_id: str = "",
    seller_id: str = "",
    site_id: str = "",
    status: str = "active",
):
    conn = get_conn()
    try:
        ts = now()
        conn.execute(
            """INSERT INTO user_ml_links
               (user_id, client_id, ml_user_id, nickname, official_store,
                advertiser_id, seller_id, site_id, status, created_at, updated_at, last_verified_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 client_id=excluded.client_id,
                 ml_user_id=excluded.ml_user_id,
                 nickname=excluded.nickname,
                 official_store=excluded.official_store,
                 advertiser_id=excluded.advertiser_id,
                 seller_id=excluded.seller_id,
                 site_id=excluded.site_id,
                 status=excluded.status,
                 updated_at=excluded.updated_at,
                 last_verified_at=excluded.last_verified_at""",
            (
                user_id,
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
    finally:
        conn.close()


def mark_user_ml_link_disconnected(user_id: int):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE user_ml_links SET status='disconnected', updated_at=? WHERE user_id=?",
            (now(), user_id),
        )
    finally:
        conn.close()


def list_users(query: str = "", limit: int = 200):
    conn = get_conn()
    try:
        _expire_overdue_active_users(conn)
        if query:
            q = f"%{query.lower()}%"
            cur = conn.execute(
                """SELECT * FROM users
                   WHERE LOWER(email) LIKE ? OR LOWER(COALESCE(name,'')) LIKE ?
                   ORDER BY created_at DESC LIMIT ?""",
                (q, q, limit),
            )
        else:
            cur = conn.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (limit,))
        return cur.fetchall()
    finally:
        conn.close()


def set_password(user_id: int, password_hash: str):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
            (password_hash, now(), user_id),
        )
    finally:
        conn.close()


def set_user_status(user_id: int, status: str, expires_at=None):
    conn = get_conn()
    try:
        if expires_at is None:
            conn.execute(
                "UPDATE users SET status=?, updated_at=? WHERE id=?",
                (status, now(), user_id),
            )
        else:
            conn.execute(
                "UPDATE users SET status=?, expires_at=?, updated_at=? WHERE id=?",
                (status, expires_at, now(), user_id),
            )
    finally:
        conn.close()


def reset_user_password(user_id: int):
    """Limpa a senha — força o cliente a cadastrar nova senha no próximo acesso."""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE users SET password_hash=NULL, updated_at=? WHERE id=?",
            (now(), user_id),
        )
        # também derruba todas as sessões ativas
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    finally:
        conn.close()


# ---------- SESSIONS ----------

def create_session(user_id: int, token: str, ip: str, user_agent: str):
    """Cria sessão. Como queremos sessão ÚNICA por usuário, apaga as anteriores."""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        conn.execute(
            """INSERT INTO sessions (token, user_id, created_at, last_seen, ip, user_agent)
               VALUES (?,?,?,?,?,?)""",
            (token, user_id, now(), now(), ip, user_agent),
        )
    finally:
        conn.close()


def get_session(token: str):
    if not token:
        return None
    conn = get_conn()
    try:
        _expire_overdue_active_users(
            conn,
            "id IN (SELECT user_id FROM sessions WHERE token=?)",
            (token,),
        )
        cur = conn.execute(
            """SELECT s.*, u.email, u.name, u.status, u.expires_at, u.password_hash
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token=?""",
            (token,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def touch_session(token: str):
    conn = get_conn()
    try:
        conn.execute("UPDATE sessions SET last_seen=? WHERE token=?", (now(), token))
    finally:
        conn.close()


def delete_session(token: str):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    finally:
        conn.close()


# ---------- WEBHOOK EVENTS ----------

def webhook_event_seen(event_id: str) -> bool:
    conn = get_conn()
    try:
        cur = conn.execute(
            "SELECT status FROM webhook_events WHERE event_id=?",
            (event_id,),
        )
        row = cur.fetchone()
        return bool(row and row["status"] in ("processed", "ignored"))
    finally:
        conn.close()


def set_user_access_window(user_id: int, status: str = "active", expires_at=None, plan: str = ""):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE users SET status=?, expires_at=?, plan=COALESCE(?, plan), updated_at=? WHERE id=?",
            (status, expires_at, plan or None, now(), user_id),
        )
    finally:
        conn.close()


def webhook_event_claim(
    event_id: str,
    event_name: str,
    payload_metadata: str,
    payload_hash: str,
) -> str:
    """
    Reserve an event for processing.

    Returns claimed, processed, or in_progress. Failed events can be claimed
    again so an Eduzz retry is not discarded.
    """
    with _lock:
        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM webhook_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if row:
                if row["status"] in ("processed", "ignored"):
                    conn.execute("COMMIT")
                    return "processed"
                if row["status"] == "processing":
                    conn.execute("COMMIT")
                    return "in_progress"
                conn.execute(
                    """UPDATE webhook_events
                       SET event_name=?, received_at=?, payload=?,
                           payload_hash=?, status='processing',
                           processed_at=NULL, error=NULL
                       WHERE event_id=?""",
                    (event_name, now(), payload_metadata, payload_hash, event_id),
                )
            else:
                conn.execute(
                    """INSERT INTO webhook_events
                       (event_id, event_name, received_at, payload,
                        payload_hash, status, processed_at, error)
                       VALUES (?,?,?,?,?,'processing',NULL,NULL)""",
                    (event_id, event_name, now(), payload_metadata, payload_hash),
                )
            conn.execute("COMMIT")
            return "claimed"
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


def webhook_event_finish(event_id: str, status: str, error: str = ""):
    if status not in ("processed", "ignored", "failed"):
        raise ValueError("Invalid webhook status.")
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE webhook_events
               SET status=?, processed_at=?, error=?
               WHERE event_id=?""",
            (status, now(), (error or "")[:500] or None, event_id),
        )
    finally:
        conn.close()


def webhook_event_save(event_id: str, event_name: str, payload: str):
    """Compatibility helper for older callers."""
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    state = webhook_event_claim(event_id, event_name, "{}", digest)
    if state == "claimed":
        webhook_event_finish(event_id, "processed")


def get_webhook_event(event_id: str):
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT * FROM webhook_events WHERE event_id=?",
            (event_id,),
        ).fetchone()
    finally:
        conn.close()


# ---------- OAUTH STATES ----------

def save_oauth_state(state: str, ttl_seconds: int = 600):
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM oauth_states WHERE expires_at < ?", (now(),))
        conn.execute(
            """INSERT OR REPLACE INTO oauth_states(state_hash, expires_at, used_at)
               VALUES (?,?,NULL)""",
            (state_hash, now() + ttl_seconds),
        )
    finally:
        conn.close()


def save_ml_link_state(state: str, user_id: int, return_to: str = "/online", ttl_seconds: int = 900):
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    conn = get_conn()
    try:
        ts = now()
        conn.execute("DELETE FROM ml_link_states WHERE expires_at < ?", (ts,))
        conn.execute(
            """INSERT OR REPLACE INTO ml_link_states
               (state_hash, user_id, return_to, expires_at, created_at, attached_at, used_at)
               VALUES (?,?,?,?,?,NULL,NULL)""",
            (state_hash, user_id, return_to or "/online", ts + ttl_seconds, ts),
        )
    finally:
        conn.close()


def get_ml_link_state(state: str):
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    conn = get_conn()
    try:
        cur = conn.execute(
            """SELECT * FROM ml_link_states
               WHERE state_hash=?""",
            (state_hash,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def mark_ml_link_state_attached(state: str):
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE ml_link_states SET attached_at=? WHERE state_hash=?",
            (now(), state_hash),
        )
    finally:
        conn.close()


def consume_ml_link_state(state: str):
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    with _lock:
        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT * FROM ml_link_states
                   WHERE state_hash=?""",
                (state_hash,),
            ).fetchone()
            valid = bool(
                row
                and not row["used_at"]
                and row["expires_at"] >= now()
                and row["attached_at"]
            )
            if valid:
                conn.execute(
                    "UPDATE ml_link_states SET used_at=? WHERE state_hash=?",
                    (now(), state_hash),
                )
            conn.execute("COMMIT")
            return row if valid else None
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


def consume_oauth_state(state: str) -> bool:
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    with _lock:
        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT expires_at, used_at FROM oauth_states
                   WHERE state_hash=?""",
                (state_hash,),
            ).fetchone()
            valid = bool(row and not row["used_at"] and row["expires_at"] >= now())
            if valid:
                conn.execute(
                    "UPDATE oauth_states SET used_at=? WHERE state_hash=?",
                    (now(), state_hash),
                )
            conn.execute("COMMIT")
            return valid
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


# ---------- ADMINS ----------

def ensure_admin(email: str, password_hash: str):
    """Cria o admin se ele ainda não existir; atualiza a senha caso já exista."""
    email = (email or "").strip().lower()
    if not email or not password_hash:
        return
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO admins (email, password_hash, created_at) VALUES (?,?,?) "
            "ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash",
            (email, password_hash, now()),
        )
    finally:
        conn.close()


def get_admin(email: str):
    if not email:
        return None
    conn = get_conn()
    try:
        cur = conn.execute("SELECT * FROM admins WHERE email=?", (email.strip().lower(),))
        return cur.fetchone()
    finally:
        conn.close()


# ---------- AUDIT ----------

def log_audit(user_id, action: str, detail: str = "", ip: str = ""):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO audit_log (user_id, action, detail, ip, created_at) VALUES (?,?,?,?,?)",
            (user_id, action, detail, ip, now()),
        )
    finally:
        conn.close()
