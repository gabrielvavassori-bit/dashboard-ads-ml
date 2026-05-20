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
    payload      TEXT NOT NULL
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
        cur = conn.execute("SELECT id, password_hash FROM users WHERE email=?", (email,))
        row = cur.fetchone()
        ts = now()
        if row:
            conn.execute(
                """UPDATE users
                   SET name=COALESCE(?, name),
                       eduzz_buyer_id=COALESCE(?, eduzz_buyer_id),
                       eduzz_contract_id=COALESCE(?, eduzz_contract_id),
                       plan=COALESCE(?, plan),
                       status=?,
                       expires_at=?,
                       updated_at=?
                   WHERE id=?""",
                (name, buyer_id, contract_id, plan, status, expires_at, ts, row["id"]),
            )
            return row["id"]
        else:
            cur = conn.execute(
                """INSERT INTO users
                   (email, name, eduzz_buyer_id, eduzz_contract_id, plan, status, expires_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (email, name, buyer_id, contract_id, plan, status, expires_at, ts, ts),
            )
            return cur.lastrowid
    finally:
        conn.close()


def get_user_by_email(email: str):
    if not email:
        return None
    conn = get_conn()
    try:
        cur = conn.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),))
        return cur.fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id: int):
    conn = get_conn()
    try:
        cur = conn.execute("SELECT * FROM users WHERE id=?", (user_id,))
        return cur.fetchone()
    finally:
        conn.close()


def list_users(query: str = "", limit: int = 200):
    conn = get_conn()
    try:
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
        cur = conn.execute("SELECT 1 FROM webhook_events WHERE event_id=?", (event_id,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def webhook_event_save(event_id: str, event_name: str, payload: str):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO webhook_events (event_id, event_name, received_at, payload) VALUES (?,?,?,?)",
            (event_id, event_name, now(), payload),
        )
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
