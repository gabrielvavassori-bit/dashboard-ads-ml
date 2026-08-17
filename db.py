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
    beta_enabled      INTEGER DEFAULT NULL,             -- NULL = allowlist, 1 = liberado, 0 = bloqueado
    sales_enabled     INTEGER NOT NULL DEFAULT 1,       -- 1 = inteligencia de vendas liberada, 0 = bloqueada
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

CREATE TABLE IF NOT EXISTS user_ml_accounts (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                  INTEGER NOT NULL,
    slot_number              INTEGER NOT NULL,
    client_id                TEXT NOT NULL,
    ml_user_id               TEXT,
    nickname                 TEXT,
    official_store           TEXT,
    advertiser_id            TEXT,
    seller_id                TEXT,
    site_id                  TEXT,
    status                   TEXT NOT NULL DEFAULT 'active',
    admin_granted            INTEGER NOT NULL DEFAULT 0,
    bound_at                 INTEGER NOT NULL,
    last_replaced_at         INTEGER,
    replacement_locked_until INTEGER,
    created_at               INTEGER NOT NULL,
    updated_at               INTEGER NOT NULL,
    last_verified_at         INTEGER,
    UNIQUE(user_id, slot_number),
    UNIQUE(user_id, client_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_ml_accounts_user_status
    ON user_ml_accounts(user_id, status);
CREATE INDEX IF NOT EXISTS idx_user_ml_accounts_client
    ON user_ml_accounts(client_id);

CREATE TABLE IF NOT EXISTS ml_link_states (
    state_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    slot_number INTEGER NOT NULL DEFAULT 1,
    return_to   TEXT NOT NULL,
    expires_at  INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    attached_at INTEGER,
    used_at     INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS shopee_link_states (
    state_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    return_to  TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at    INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_shopee_accounts (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id               INTEGER NOT NULL,
    shop_id               TEXT NOT NULL,
    shop_name             TEXT,
    region                TEXT NOT NULL DEFAULT 'BR',
    status                TEXT NOT NULL DEFAULT 'active',
    access_token_encrypted  TEXT NOT NULL,
    refresh_token_encrypted TEXT,
    token_expires_at      INTEGER,
    refresh_expires_at    INTEGER,
    connected_at          INTEGER NOT NULL,
    last_verified_at      INTEGER,
    created_at            INTEGER NOT NULL,
    updated_at            INTEGER NOT NULL,
    UNIQUE(user_id, shop_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_shopee_accounts_user_status
    ON user_shopee_accounts(user_id, status);

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

CREATE TABLE IF NOT EXISTS beta_handoffs (
    nonce_hash TEXT PRIMARY KEY,
    expires_at INTEGER NOT NULL,
    used_at INTEGER NOT NULL
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
            if "beta_enabled" not in user_columns:
                conn.execute("ALTER TABLE users ADD COLUMN beta_enabled INTEGER DEFAULT NULL")
            if "sales_enabled" not in user_columns:
                conn.execute("ALTER TABLE users ADD COLUMN sales_enabled INTEGER NOT NULL DEFAULT 1")
            if "ml_slot_limit" not in user_columns:
                conn.execute("ALTER TABLE users ADD COLUMN ml_slot_limit INTEGER NOT NULL DEFAULT 1")
            conn.execute(
                """UPDATE users
                   SET sales_enabled=1
                   WHERE status='active' AND (sales_enabled IS NULL OR sales_enabled NOT IN (0,1))"""
            )
            ml_link_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(user_ml_links)")
            }
            ml_link_migrations = {
                "ml_user_id": "ALTER TABLE user_ml_links ADD COLUMN ml_user_id TEXT",
                "nickname": "ALTER TABLE user_ml_links ADD COLUMN nickname TEXT",
                "official_store": "ALTER TABLE user_ml_links ADD COLUMN official_store TEXT",
                "advertiser_id": "ALTER TABLE user_ml_links ADD COLUMN advertiser_id TEXT",
                "seller_id": "ALTER TABLE user_ml_links ADD COLUMN seller_id TEXT",
                "site_id": "ALTER TABLE user_ml_links ADD COLUMN site_id TEXT",
                "last_verified_at": "ALTER TABLE user_ml_links ADD COLUMN last_verified_at INTEGER",
            }
            for column, statement in ml_link_migrations.items():
                if column not in ml_link_columns:
                    conn.execute(statement)
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_ml_links_user_unique ON user_ml_links(user_id)"
            )
            ml_state_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(ml_link_states)")
            }
            if "attached_at" not in ml_state_columns:
                conn.execute("ALTER TABLE ml_link_states ADD COLUMN attached_at INTEGER")
            if "slot_number" not in ml_state_columns:
                conn.execute("ALTER TABLE ml_link_states ADD COLUMN slot_number INTEGER NOT NULL DEFAULT 1")
            session_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(sessions)")
            }
            if "selected_ml_account_id" not in session_columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN selected_ml_account_id INTEGER")
            conn.execute(
                """INSERT OR IGNORE INTO user_ml_accounts
                   (user_id, slot_number, client_id, ml_user_id, nickname,
                    official_store, advertiser_id, seller_id, site_id, status,
                    admin_granted, bound_at, created_at, updated_at, last_verified_at)
                   SELECT user_id, 1, client_id, ml_user_id, nickname,
                          official_store, advertiser_id, seller_id, site_id, status,
                          0, created_at, created_at, updated_at, last_verified_at
                   FROM user_ml_links"""
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


def list_active_ml_links_for_user(user_id: int):
    conn = get_conn()
    try:
        return conn.execute(
            """SELECT * FROM user_ml_accounts
               WHERE user_id=? AND status='active'
               ORDER BY slot_number, id""",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def list_active_shopee_accounts_for_user(user_id: int):
    conn = get_conn()
    try:
        return conn.execute(
            """SELECT id, user_id, shop_id, shop_name, region, status,
                      token_expires_at, refresh_expires_at, connected_at,
                      last_verified_at, created_at, updated_at
               FROM user_shopee_accounts
               WHERE user_id=? AND status='active'
               ORDER BY connected_at DESC, id DESC""",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def get_ml_account_for_user(user_id: int, account_id: int):
    conn = get_conn()
    try:
        return conn.execute(
            """SELECT * FROM user_ml_accounts
               WHERE id=? AND user_id=? AND status='active'""",
            (account_id, user_id),
        ).fetchone()
    finally:
        conn.close()


def get_ml_account_by_slot(user_id: int, slot_number: int):
    conn = get_conn()
    try:
        return conn.execute(
            """SELECT * FROM user_ml_accounts
               WHERE user_id=? AND slot_number=? AND status='active'""",
            (user_id, int(slot_number)),
        ).fetchone()
    finally:
        conn.close()


def get_active_ml_link_for_user(user_id: int, selected_account_id=None):
    if selected_account_id is not None:
        return get_ml_account_for_user(user_id, int(selected_account_id))
    links = list_active_ml_links_for_user(user_id)
    return links[0] if len(links) == 1 else None


def claim_beta_handoff(nonce: str, expires_at: int) -> bool:
    """Consumes a bridge nonce exactly once in this environment."""
    if not nonce:
        return False
    nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    ts = now()
    with _lock:
        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM beta_handoffs WHERE expires_at<?", (ts,))
            existing = conn.execute(
                "SELECT nonce_hash FROM beta_handoffs WHERE nonce_hash=?",
                (nonce_hash,),
            ).fetchone()
            if existing or int(expires_at) <= ts:
                conn.execute("ROLLBACK")
                return False
            conn.execute(
                "INSERT INTO beta_handoffs (nonce_hash, expires_at, used_at) VALUES (?,?,?)",
                (nonce_hash, int(expires_at), ts),
            )
            conn.execute("COMMIT")
            return True
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


def upsert_beta_identity(identity: dict) -> int:
    """Materializes a beta user without importing a password or credential."""
    email = (identity.get("email") or "").strip().lower()
    if not email:
        raise ValueError("email beta ausente")
    ts = now()
    conn = get_conn()
    try:
        existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        values = (
            identity.get("name") or "",
            identity.get("plan") or "beta",
            identity.get("status") or "active",
            identity.get("beta_enabled"),
            1 if identity.get("sales_enabled", True) else 0,
            max(1, min(5, int(identity.get("ml_slot_limit") or 1))),
            identity.get("expires_at"),
            ts,
        )
        if existing:
            conn.execute(
                """UPDATE users SET name=?, plan=?, status=?, beta_enabled=?, sales_enabled=?,
                   ml_slot_limit=?, expires_at=?,
                   access_origin='beta_bridge', updated_at=? WHERE id=?""",
                (*values, existing["id"]),
            )
            return int(existing["id"])
        cur = conn.execute(
            """INSERT INTO users
               (email, name, access_origin, plan, status, beta_enabled, sales_enabled,
                ml_slot_limit, expires_at, created_at, updated_at)
               VALUES (?,?, 'beta_bridge', ?,?,?,?,?,?,?,?)""",
            (email, values[0], values[1], values[2], values[3], values[4], values[5], values[6], ts, ts),
        )
        return int(cur.lastrowid)
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
    slot_number: int = 1,
    admin_granted: bool = False,
    allow_replacement: bool = False,
):
    slot_number = int(slot_number or 1)
    if slot_number < 1 or slot_number > 5:
        raise ValueError("slot_number deve ficar entre 1 e 5")
    client_id = (client_id or "").strip()
    if not client_id:
        raise ValueError("client_id obrigatorio")
    conn = get_conn()
    try:
        ts = now()
        user = conn.execute(
            "SELECT ml_slot_limit FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        if not user:
            raise ValueError("usuario nao encontrado")
        if slot_number > int(user["ml_slot_limit"] or 1):
            raise ValueError("slot nao liberado para este usuario")
        existing = conn.execute(
            "SELECT * FROM user_ml_accounts WHERE user_id=? AND slot_number=?",
            (user_id, slot_number),
        ).fetchone()
        duplicate = conn.execute(
            "SELECT id, slot_number FROM user_ml_accounts WHERE user_id=? AND client_id=?",
            (user_id, client_id),
        ).fetchone()
        if duplicate and (not existing or duplicate["id"] != existing["id"]):
            raise ValueError(f"esta conta Mercado Livre ja ocupa o slot {duplicate['slot_number']}")
        if existing:
            replacing = existing["client_id"] != client_id
            locked_until = int(existing["replacement_locked_until"] or 0)
            if replacing and locked_until > ts and not allow_replacement:
                raise ValueError("este slot so podera trocar de conta apos o fim do ciclo de 30 dias")
            conn.execute(
                """UPDATE user_ml_accounts
                   SET client_id=?,
                       ml_user_id=?,
                       nickname=?,
                       official_store=?,
                       advertiser_id=?,
                       seller_id=?,
                       site_id=?,
                       status=?,
                       admin_granted=?,
                       bound_at=CASE WHEN client_id<>? THEN ? ELSE bound_at END,
                       last_replaced_at=CASE WHEN client_id<>? THEN ? ELSE last_replaced_at END,
                       replacement_locked_until=CASE WHEN client_id<>? THEN ? ELSE replacement_locked_until END,
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
                    1 if admin_granted else int(existing["admin_granted"] or 0),
                    client_id,
                    ts,
                    client_id,
                    ts,
                    client_id,
                    ts + (30 * 86400),
                    ts,
                    ts,
                    existing["id"],
                ),
            )
            account_id = int(existing["id"])
        else:
            cur = conn.execute(
                """INSERT INTO user_ml_accounts
                   (user_id, slot_number, client_id, ml_user_id, nickname, official_store,
                    advertiser_id, seller_id, site_id, status, admin_granted, bound_at,
                    created_at, updated_at, last_verified_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user_id,
                    slot_number,
                    client_id,
                    ml_user_id,
                    nickname,
                    official_store,
                    advertiser_id,
                    seller_id,
                    site_id,
                    status,
                    1 if admin_granted else 0,
                    ts,
                    ts,
                    ts,
                    ts,
                ),
            )
            account_id = int(cur.lastrowid)
        if slot_number == 1:
            legacy = conn.execute(
                "SELECT id FROM user_ml_links WHERE user_id=?",
                (user_id,),
            ).fetchone()
            values = (
                client_id, ml_user_id, nickname, official_store, advertiser_id,
                seller_id, site_id, status, ts, ts,
            )
            if legacy:
                conn.execute(
                    """UPDATE user_ml_links SET client_id=?, ml_user_id=?, nickname=?,
                       official_store=?, advertiser_id=?, seller_id=?, site_id=?, status=?,
                       updated_at=?, last_verified_at=? WHERE id=?""",
                    (*values, legacy["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO user_ml_links
                       (user_id, client_id, ml_user_id, nickname, official_store,
                        advertiser_id, seller_id, site_id, status, created_at,
                        updated_at, last_verified_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (user_id, client_id, ml_user_id, nickname, official_store,
                     advertiser_id, seller_id, site_id, status, ts, ts, ts),
                )
        return account_id
    finally:
        conn.close()


def mark_user_ml_link_disconnected(user_id: int, account_id=None):
    conn = get_conn()
    try:
        if account_id is None:
            conn.execute(
                "UPDATE user_ml_accounts SET status='disconnected', updated_at=? WHERE user_id=?",
                (now(), user_id),
            )
        else:
            conn.execute(
                """UPDATE user_ml_accounts SET status='disconnected', updated_at=?
                   WHERE user_id=? AND id=?""",
                (now(), user_id, int(account_id)),
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


def set_user_beta_access(user_id: int, enabled: bool) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE users SET beta_enabled=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, now(), user_id),
        )
    finally:
        conn.close()


def set_user_sales_access(user_id: int, enabled: bool) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE users SET sales_enabled=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, now(), user_id),
        )
    finally:
        conn.close()


def set_user_ml_slot_limit(user_id: int, slot_limit: int) -> None:
    slot_limit = int(slot_limit)
    if slot_limit < 1 or slot_limit > 5:
        raise ValueError("o limite de contas deve ficar entre 1 e 5")
    conn = get_conn()
    try:
        highest = conn.execute(
            """SELECT COALESCE(MAX(slot_number), 0) AS highest
               FROM user_ml_accounts WHERE user_id=? AND status='active'""",
            (user_id,),
        ).fetchone()["highest"]
        if int(highest or 0) > slot_limit:
            raise ValueError("remova ou bloqueie as contas excedentes antes de reduzir o limite")
        conn.execute(
            "UPDATE users SET ml_slot_limit=?, updated_at=? WHERE id=?",
            (slot_limit, now(), user_id),
        )
    finally:
        conn.close()


def delete_user_sessions(user_id: int) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
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


def set_session_selected_ml_account(token: str, user_id: int, account_id: int) -> bool:
    account = get_ml_account_for_user(user_id, account_id)
    if not account:
        return False
    conn = get_conn()
    try:
        cur = conn.execute(
            """UPDATE sessions SET selected_ml_account_id=?, last_seen=?
               WHERE token=? AND user_id=?""",
            (account_id, now(), token, user_id),
        )
        return cur.rowcount == 1
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


def save_ml_link_state(
    state: str,
    user_id: int,
    return_to: str = "/online",
    ttl_seconds: int = 900,
    slot_number: int = 1,
):
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    conn = get_conn()
    try:
        ts = now()
        conn.execute("DELETE FROM ml_link_states WHERE expires_at < ?", (ts,))
        conn.execute(
            """INSERT OR REPLACE INTO ml_link_states
               (state_hash, user_id, slot_number, return_to, expires_at, created_at, attached_at, used_at)
               VALUES (?,?,?,?,?,?,NULL,NULL)""",
            (state_hash, user_id, int(slot_number), return_to or "/online", ts + ttl_seconds, ts),
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


def save_shopee_link_state(state: str, user_id: int, return_to: str = "/shopee", ttl_seconds: int = 900):
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    conn = get_conn()
    try:
        ts = now()
        conn.execute("DELETE FROM shopee_link_states WHERE expires_at < ?", (ts,))
        conn.execute(
            """INSERT OR REPLACE INTO shopee_link_states
               (state_hash, user_id, return_to, expires_at, used_at)
               VALUES (?,?,?,?,NULL)""",
            (state_hash, user_id, return_to or "/shopee", ts + ttl_seconds),
        )
    finally:
        conn.close()


def sync_beta_ml_accounts(user_id: int, accounts: list[dict]) -> int:
    """Mirrors non-secret account metadata from production into beta."""
    normalized = []
    seen_slots = set()
    seen_clients = set()
    for raw in accounts:
        account = dict(raw)
        slot_number = int(account.get("slot_number") or 0)
        client_id = (account.get("client_id") or "").strip()
        if slot_number < 1 or slot_number > 5 or not client_id:
            raise ValueError("conta Mercado Livre invalida para sincronizacao beta")
        if slot_number in seen_slots or client_id in seen_clients:
            raise ValueError("slots ou contas Mercado Livre duplicados")
        seen_slots.add(slot_number)
        seen_clients.add(client_id)
        normalized.append(account)

    with _lock:
        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute(
                "SELECT ml_slot_limit FROM users WHERE id=?", (int(user_id),)
            ).fetchone()
            if not user:
                raise ValueError("usuario beta inexistente")
            slot_limit = max(1, min(5, int(user["ml_slot_limit"] or 1)))
            if any(int(account["slot_number"]) > slot_limit for account in normalized):
                raise ValueError("conta Mercado Livre excede o limite de slots")

            previous = {
                (int(row["slot_number"]), str(row["client_id"]))
                for row in conn.execute(
                    "SELECT slot_number, client_id FROM user_ml_accounts WHERE user_id=?",
                    (int(user_id),),
                ).fetchall()
            }
            current = {
                (int(account["slot_number"]), str(account["client_id"]))
                for account in normalized
            }
            ts = now()
            conn.execute("DELETE FROM user_ml_accounts WHERE user_id=?", (int(user_id),))
            for account in sorted(normalized, key=lambda item: int(item["slot_number"])):
                conn.execute(
                    """INSERT INTO user_ml_accounts
                       (user_id, slot_number, client_id, ml_user_id, nickname, official_store,
                        advertiser_id, seller_id, site_id, status, admin_granted, bound_at,
                        last_replaced_at, replacement_locked_until, created_at, updated_at,
                        last_verified_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        int(user_id), int(account["slot_number"]), str(account["client_id"]),
                        account.get("ml_user_id"), account.get("nickname"), account.get("official_store"),
                        account.get("advertiser_id"), account.get("seller_id"), account.get("site_id"),
                        account.get("status") or "active", 1 if account.get("admin_granted") else 0,
                        account.get("bound_at") or account.get("created_at") or ts,
                        account.get("last_replaced_at"),
                        account.get("replacement_locked_until"), account.get("created_at") or ts,
                        account.get("updated_at") or ts, account.get("last_verified_at"),
                    ),
                )

            conn.execute("DELETE FROM user_ml_links WHERE user_id=?", (int(user_id),))
            if normalized:
                legacy = sorted(normalized, key=lambda item: int(item["slot_number"]))[0]
                conn.execute(
                    """INSERT INTO user_ml_links
                       (user_id, client_id, ml_user_id, nickname, official_store, advertiser_id,
                        seller_id, site_id, status, created_at, updated_at, last_verified_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        int(user_id), str(legacy["client_id"]), legacy.get("ml_user_id"),
                        legacy.get("nickname"), legacy.get("official_store"), legacy.get("advertiser_id"),
                        legacy.get("seller_id"), legacy.get("site_id"), legacy.get("status") or "active",
                        legacy.get("created_at") or ts, legacy.get("updated_at") or ts,
                        legacy.get("last_verified_at"),
                    ),
                )
            if previous != current:
                conn.execute(
                    "UPDATE sessions SET selected_ml_account_id=NULL WHERE user_id=?",
                    (int(user_id),),
                )
            conn.execute("COMMIT")
            return len(normalized)
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


def consume_shopee_link_state(state: str):
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    with _lock:
        conn = get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM shopee_link_states WHERE state_hash=?", (state_hash,)
            ).fetchone()
            valid = bool(row and not row["used_at"] and row["expires_at"] >= now())
            if valid:
                conn.execute("UPDATE shopee_link_states SET used_at=? WHERE state_hash=?", (now(), state_hash))
            conn.execute("COMMIT")
            return row if valid else None
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


def upsert_shopee_account(
    user_id: int,
    shop_id: int | str,
    access_token_encrypted: str,
    refresh_token_encrypted: str = "",
    token_expires_at=None,
    refresh_expires_at=None,
    shop_name: str = "",
    region: str = "BR",
):
    shop_id = str(shop_id or "").strip()
    if not shop_id or not access_token_encrypted:
        raise ValueError("shop_id e token protegido sao obrigatorios")
    conn = get_conn()
    try:
        ts = now()
        existing = conn.execute(
            "SELECT id FROM user_shopee_accounts WHERE user_id=? AND shop_id=?", (user_id, shop_id)
        ).fetchone()
        values = (
            shop_name or None, region or "BR", access_token_encrypted,
            refresh_token_encrypted or None, token_expires_at, refresh_expires_at,
            ts, ts, user_id, shop_id,
        )
        if existing:
            conn.execute(
                """UPDATE user_shopee_accounts
                   SET shop_name=?, region=?, access_token_encrypted=?, refresh_token_encrypted=?,
                       token_expires_at=?, refresh_expires_at=?, status='active',
                       connected_at=?, updated_at=?
                   WHERE user_id=? AND shop_id=?""",
                values,
            )
            return int(existing["id"])
        cur = conn.execute(
            """INSERT INTO user_shopee_accounts
               (user_id, shop_id, shop_name, region, status, access_token_encrypted,
                refresh_token_encrypted, token_expires_at, refresh_expires_at,
                connected_at, created_at, updated_at)
               VALUES (?,?,?,?, 'active', ?,?,?,?,?,?,?)""",
            (user_id, shop_id, shop_name or None, region or "BR", access_token_encrypted,
             refresh_token_encrypted or None, token_expires_at, refresh_expires_at,
             ts, ts, ts),
        )
        return int(cur.lastrowid)
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


def list_recent_audit_for_user(user_id: int, limit: int = 10):
    conn = get_conn()
    try:
        cur = conn.execute(
            """SELECT * FROM audit_log
               WHERE user_id=?
               ORDER BY created_at DESC, id DESC
               LIMIT ?""",
            (user_id, limit),
        )
        return cur.fetchall()
    finally:
        conn.close()
