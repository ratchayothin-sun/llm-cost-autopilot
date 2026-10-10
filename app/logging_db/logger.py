import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "autopilot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    prompt TEXT,
    task_type TEXT,
    final_tier TEXT,
    total_cost REAL,
    total_latency REAL,
    escalations INTEGER
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER REFERENCES requests(id),
    tier TEXT,
    model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    cost REAL,
    latency REAL,
    verified INTEGER,
    error TEXT
);
"""


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def log_request(messages, task_type, attempts):
    prompt = messages[-1]["content"] if messages else ""
    final = attempts[-1]
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO requests
               (prompt, task_type, final_tier, total_cost, total_latency, escalations)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                prompt,
                task_type,
                final["tier"],
                sum(a["cost"] for a in attempts),
                sum(a["latency"] for a in attempts),
                len(attempts) - 1,
            ),
        )
        request_id = cur.lastrowid
        conn.executemany(
            """INSERT INTO attempts
               (request_id, tier, model, prompt_tokens, completion_tokens,
                cost, latency, verified, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    request_id,
                    a["tier"],
                    a.get("model"),
                    a["prompt_tokens"],
                    a["completion_tokens"],
                    a["cost"],
                    a["latency"],
                    int(a["verified"]),
                    a.get("error"),
                )
                for a in attempts
            ],
        )