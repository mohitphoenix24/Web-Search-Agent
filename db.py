"""
PHASE 5 — SAVED CHATS (persistence)

In Phase 4 the chat lived in the browser: refresh the page and it was gone.
Now every finished turn is saved in SQLite — a whole database in one file
(chats.db). SQLite comes with Python, so there's nothing to install.

This also moves the agent's MEMORY to the server: to answer a follow-up,
the server loads the earlier turns of the chat from here.

We store each turn's *events* (the same ones we stream to the UI). To show an
old chat, the UI simply replays them, so old turns come back with their full
trace, sources and answer.
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).with_name("chats.db")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["title"]
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chats (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS turns (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
                question   TEXT NOT NULL,
                answer     TEXT NOT NULL,
                events     TEXT NOT NULL,   -- JSON list of agent events
                seconds    REAL NOT NULL,
                created_at REAL NOT NULL
            );
        """)


def chat_exists(chat_id: int) -> bool:
    with connect() as conn:
        return conn.execute("SELECT 1 FROM chats WHERE id = ?", (chat_id,)).fetchone() is not None


def list_chats() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("""
            SELECT chats.id, chats.title, chats.updated_at, COUNT(turns.id) AS turn_count
            FROM chats LEFT JOIN turns ON turns.chat_id = chats.id
            GROUP BY chats.id
            ORDER BY chats.updated_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


def get_chat(chat_id: int) -> dict | None:
    with connect() as conn:
        chat = conn.execute("SELECT id, title FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if chat is None:
            return None
        turns = conn.execute(
            "SELECT id, question, answer, events, seconds FROM turns WHERE chat_id = ? ORDER BY id",
            (chat_id,),
        ).fetchall()
    return {
        **dict(chat),
        "turns": [{**dict(t), "events": json.loads(t["events"])} for t in turns],
    }


def history(chat_id: int, limit: int) -> list[dict]:
    """The last `limit` Q&A pairs of a chat, oldest first — the agent's memory."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT question, answer FROM turns WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def save_turn(chat_id: int | None, question: str, answer: str, events: list, seconds: float) -> dict:
    """Save a finished turn. Creates the chat first if it's new. Returns {chat_id, title}."""
    now = time.time()
    with connect() as conn:
        if chat_id is None:
            title = question if len(question) <= 60 else question[:57].rstrip() + "…"
            chat_id = conn.execute(
                "INSERT INTO chats (title, created_at, updated_at) VALUES (?, ?, ?)", (title, now, now)
            ).lastrowid
        conn.execute(
            "INSERT INTO turns (chat_id, question, answer, events, seconds, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, question, answer, json.dumps(events), seconds, now),
        )
        conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now, chat_id))
        title = conn.execute("SELECT title FROM chats WHERE id = ?", (chat_id,)).fetchone()["title"]
    return {"chat_id": chat_id, "title": title}


def delete_chat(chat_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))  # turns go too (ON DELETE CASCADE)
