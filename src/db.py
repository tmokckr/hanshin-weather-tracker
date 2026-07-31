"""SQLite接続とスキーマ初期化。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "tracker.db"
SCHEMA_PATH = ROOT / "schema.sql"
SEED_STADIUMS_PATH = ROOT / "seed_stadiums.sql"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.executescript(SEED_STADIUMS_PATH.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()


def find_stadium_id(conn: sqlite3.Connection, raw_name: str) -> str | None:
    """日程ページ上の表記（例: '甲子園', '東京D'）からstadiums.idを引く。"""
    raw_name = raw_name.strip()
    for row in conn.execute("SELECT id, official_name, aliases FROM stadiums"):
        if raw_name == row["official_name"]:
            return row["id"]
        aliases = json.loads(row["aliases"])
        if raw_name in aliases:
            return row["id"]
    return None


if __name__ == "__main__":
    init_db()
    print(f"initialized {DB_PATH}")
