from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from oasis.config import OASIS_DIR

DB_PATH = OASIS_DIR / "jobs.db"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    location    TEXT,
    salary      TEXT,
    job_url     TEXT,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'new',
    first_seen  TEXT NOT NULL DEFAULT (datetime('now')),
    applied_at  TEXT,
    notes       TEXT
);
"""


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    OASIS_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        con.execute(CREATE_TABLE)
        con.commit()
        yield con
    finally:
        con.close()


def _job_id(job_url: str | None, company: str, title: str, location: str | None) -> str:
    key = job_url or f"{company}|{title}|{location or ''}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def upsert_jobs(jobs: list[dict]) -> None:
    with _conn() as con:
        con.executemany(
            """INSERT OR IGNORE INTO jobs
               (id, title, company, location, salary, job_url, description)
               VALUES (:id, :title, :company, :location, :salary, :job_url, :description)""",
            [
                {
                    "id": _job_id(j.get("job_url"), j["company"], j["title"], j.get("location")),
                    "title": j["title"],
                    "company": j["company"],
                    "location": j.get("location"),
                    "salary": j.get("salary"),
                    "job_url": j.get("job_url"),
                    "description": j.get("description"),
                }
                for j in jobs
            ],
        )
        con.commit()


def filter_unseen(jobs: list[dict]) -> list[dict]:
    """Return only jobs not yet in the DB (truly new postings)."""
    with _conn() as con:
        result = []
        for j in jobs:
            jid = _job_id(j.get("job_url"), j["company"], j["title"], j.get("location"))
            row = con.execute("SELECT status FROM jobs WHERE id = ?", (jid,)).fetchone()
            if row is None or row["status"] == "new":
                j["_id"] = jid
                result.append(j)
        return result


def set_status(job_id: str, status: str) -> None:
    with _conn() as con:
        applied_at = datetime.now(timezone.utc).isoformat() if status == "applied" else None
        con.execute(
            "UPDATE jobs SET status = ?, applied_at = COALESCE(?, applied_at) WHERE id = ?",
            (status, applied_at, job_id),
        )
        con.commit()


def get_history(status: str | None = None) -> list[sqlite3.Row]:
    with _conn() as con:
        if status:
            rows = con.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY first_seen DESC", (status,)
            ).fetchall()
        else:
            rows = con.execute("SELECT * FROM jobs ORDER BY first_seen DESC").fetchall()
        return rows
