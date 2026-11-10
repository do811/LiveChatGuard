"""Conservative local accounting for this application's YouTube API requests.

This is NOT Google Cloud's actual remaining quota: other software, previous
versions, OAuth clients, and server-side accounting are not visible here.
Daily buckets reset at midnight America/Los_Angeles (YouTube PT).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .settings import data_dir


COSTS: dict[str, int] = {
    "liveBroadcasts.list": 1,
    "liveChatMessages.list": 5,
    "liveChatMessages.streamList": 5,
    "liveChatMessages.insert": 20,
    "liveChatMessages.delete": 20,
    "liveChatBans.insert": 200,
    "liveChatBans.delete": 200,
}


PT = ZoneInfo("America/Los_Angeles")


def quota_day(moment: datetime | None = None) -> str:
    now = moment or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("timezone-aware datetime required")
    return now.astimezone(PT).date().isoformat()


def oauth_project_key(client_secrets_path: str) -> str:
    """Identify the Cloud project without saving any client secret in the ledger.

    Project ID is often embedded in the Desktop OAuth JSON. If it cannot be
    read, group all unknown-account activity under one explicit unknown key.
    """
    try:
        source = json.loads(Path(client_secrets_path).read_text(encoding="utf-8"))
        client = source.get("installed") or source.get("web") or {}
        project_id = client.get("project_id", "")
        if isinstance(project_id, str) and project_id.strip():
            return project_id.strip()
        client_id = client.get("client_id", "")
        if isinstance(client_id, str) and client_id.strip():
            return "client-" + hashlib.sha256(client_id.encode()).hexdigest()[:16]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return "unknown-project"


@dataclass(frozen=True)
class QuotaSnapshot:
    date_pt: str
    project: str
    used: int
    calls: int
    limit: int
    quota_exceeded: bool

    @property
    def estimated_remaining(self) -> int:
        return max(0, self.limit - self.used)


class QuotaLedger:
    def __init__(self, db_path: Path | None = None, project: str = "unknown-project"):
        self.db_path = db_path or (data_dir() / "quota.sqlite3")
        self.project = project
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS quota_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project TEXT NOT NULL,
                    day_pt TEXT NOT NULL,
                    method TEXT NOT NULL,
                    units INTEGER NOT NULL,
                    at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_quota_day ON quota_calls(project, day_pt);
                CREATE TABLE IF NOT EXISTS quota_exceeded_events (
                    project TEXT NOT NULL,
                    day_pt TEXT NOT NULL,
                    at_utc TEXT NOT NULL,
                    PRIMARY KEY (project, day_pt)
                );
            """)
            # This ledger has no comments/users, but keep at most ~1 month of usage.
            cutoff = (datetime.now(timezone.utc).astimezone(PT).date() - timedelta(days=31)).isoformat()
            con.execute("DELETE FROM quota_calls WHERE day_pt < ?", (cutoff,))
            con.execute("DELETE FROM quota_exceeded_events WHERE day_pt < ?", (cutoff,))

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.execute("PRAGMA busy_timeout=10000")
        return con

    def record_attempt(self, method: str, moment: datetime | None = None) -> int:
        """Record once *just before* making each outbound API call."""
        if method not in COSTS:
            raise ValueError(f"Unknown YouTube API method: {method}")
        stamp = moment or datetime.now(timezone.utc)
        with self._connect() as con:
            con.execute("""INSERT INTO quota_calls(project, day_pt, method, units, at_utc)
                VALUES(?, ?, ?, ?, ?)""", (self.project, quota_day(stamp),
                        method, COSTS[method], stamp.isoformat()))
        return COSTS[method]

    def mark_exceeded(self, moment: datetime | None = None) -> None:
        stamp = moment or datetime.now(timezone.utc)
        with self._connect() as con:
            con.execute("""INSERT OR REPLACE INTO quota_exceeded_events(project,day_pt,at_utc)
                VALUES(?,?,?)""", (self.project, quota_day(stamp), stamp.isoformat()))

    def breakdown(self, moment: datetime | None = None) -> list[tuple[str, int, int]]:
        """Method-level estimated quota: (method, calls, units), largest cost first."""
        day = quota_day(moment)
        with self._connect() as con:
            rows = con.execute("""SELECT method, COUNT(*) AS calls, SUM(units) AS units
                FROM quota_calls WHERE project=? AND day_pt=?
                GROUP BY method ORDER BY units DESC, method ASC""",
                (self.project, day)).fetchall()
        return [(str(method), int(calls), int(units)) for method, calls, units in rows]

    def snapshot(self, limit: int = 10000, moment: datetime | None = None) -> QuotaSnapshot:
        day = quota_day(moment)
        with self._connect() as con:
            used, calls = con.execute("""SELECT COALESCE(SUM(units),0),COUNT(*)
                FROM quota_calls WHERE project=? AND day_pt=?""", (self.project, day)).fetchone()
            exceeded = con.execute("""SELECT EXISTS(SELECT 1 FROM quota_exceeded_events
                WHERE project=? AND day_pt=?)""", (self.project, day)).fetchone()[0]
        return QuotaSnapshot(day, self.project, int(used), int(calls), limit, bool(exceeded))
