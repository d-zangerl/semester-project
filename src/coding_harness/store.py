from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, project TEXT NOT NULL, request TEXT NOT NULL, start_commit TEXT, first_commit TEXT NOT NULL,
    workspace TEXT NOT NULL, git_directory TEXT NOT NULL, settings TEXT NOT NULL, limits TEXT NOT NULL,
    state TEXT NOT NULL, reason TEXT, final_response TEXT NOT NULL DEFAULT '', counters TEXT NOT NULL DEFAULT '{}',
    checks TEXT NOT NULL DEFAULT '[]', cancel_requested INTEGER NOT NULL DEFAULT 0, pid INTEGER,
    review_decision TEXT, created TEXT NOT NULL, updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id), pid INTEGER NOT NULL,
    started TEXT NOT NULL, ended TEXT, outcome TEXT
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id), run_id INTEGER NOT NULL,
    tool TEXT NOT NULL, arguments TEXT NOT NULL, status TEXT NOT NULL, result TEXT, denied INTEGER NOT NULL DEFAULT 0,
    workspace_hash TEXT, checkpoint TEXT, started TEXT NOT NULL, finished TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id), run_id INTEGER,
    kind TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class TaskStore:
    """Durable tasks, runs, actions, and an append-only event history in SQLite."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create_task(self, task_id: str, project: str, request: str, start_commit: str | None, first_commit: str,
                    workspace: Path, git_directory: Path, settings: dict, limits: dict) -> None:
        now = _now()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO tasks (id, project, request, start_commit, first_commit, workspace, git_directory, "
                "settings, limits, state, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)",
                (task_id, project, request, start_commit, first_commit, str(workspace), str(git_directory),
                 json.dumps(settings), json.dumps(limits), now, now))

    def _update(self, task_id: str, **columns) -> None:
        names = ", ".join(f"{name} = ?" for name in columns)
        with self._connection() as connection:
            connection.execute(f"UPDATE tasks SET {names}, updated = ? WHERE id = ?",
                               (*columns.values(), _now(), task_id))

    def task(self, task_id: str) -> sqlite3.Row | None:
        with self._connection() as connection:
            return connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

    def tasks(self) -> list[sqlite3.Row]:
        with self._connection() as connection:
            return connection.execute("SELECT * FROM tasks ORDER BY created DESC, rowid DESC").fetchall()

    def set_state(self, task_id: str, state: str, reason: str | None = None) -> None:
        self._update(task_id, state=state, reason=reason)

    def save_progress(self, task_id: str, counters: dict) -> None:
        self._update(task_id, counters=json.dumps(counters))

    def save_outcome(self, task_id: str, state: str, reason: str | None, final_response: str,
                     checks: list[dict] | None) -> None:
        columns = dict(state=state, reason=reason, final_response=final_response, pid=None)
        if checks is not None:
            columns["checks"] = json.dumps(checks)
        self._update(task_id, **columns)

    def save_review_decision(self, task_id: str, decision: str) -> None:
        self._update(task_id, review_decision=decision)

    def request_cancel(self, task_id: str) -> None:
        self._update(task_id, cancel_requested=1)

    def cancel_requested(self, task_id: str) -> bool:
        with self._connection() as connection:
            row = connection.execute("SELECT cancel_requested FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def begin_run(self, task_id: str, pid: int) -> int:
        with self._connection() as connection:
            run_id = connection.execute("INSERT INTO runs (task_id, pid, started) VALUES (?, ?, ?)",
                                        (task_id, pid, _now())).lastrowid
            connection.execute("UPDATE tasks SET pid = ?, state = 'running', reason = NULL, cancel_requested = 0, "
                               "updated = ? WHERE id = ?", (pid, _now(), task_id))
        return run_id

    def end_run(self, run_id: int, outcome: str) -> None:
        with self._connection() as connection:
            connection.execute("UPDATE runs SET ended = ?, outcome = ? WHERE id = ?", (_now(), outcome, run_id))

    def run_count(self, task_id: str) -> int:
        with self._connection() as connection:
            return connection.execute("SELECT COUNT(*) FROM runs WHERE task_id = ?", (task_id,)).fetchone()[0]

    def action_started(self, task_id: str, run_id: int, tool: str, arguments: dict) -> int:
        with self._connection() as connection:
            return connection.execute(
                "INSERT INTO actions (task_id, run_id, tool, arguments, status, started) VALUES (?, ?, ?, ?, 'started', ?)",
                (task_id, run_id, tool, json.dumps(arguments), _now())).lastrowid

    def action_finished(self, action_id: int, result: str, denied: bool, workspace_hash: str, checkpoint: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE actions SET status = 'finished', result = ?, denied = ?, workspace_hash = ?, checkpoint = ?, "
                "finished = ? WHERE id = ?", (result, int(denied), workspace_hash, checkpoint, _now(), action_id))

    def resolve_action(self, action_id: int, resolution: str) -> None:
        with self._connection() as connection:
            connection.execute("UPDATE actions SET status = ?, finished = ? WHERE id = ?",
                               (resolution, _now(), action_id))

    def actions(self, task_id: str) -> list[sqlite3.Row]:
        with self._connection() as connection:
            return connection.execute("SELECT * FROM actions WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()

    def add_event(self, task_id: str, run_id: int | None, kind: str, payload: dict) -> None:
        with self._connection() as connection:
            connection.execute("INSERT INTO events (task_id, run_id, kind, payload, created) VALUES (?, ?, ?, ?, ?)",
                               (task_id, run_id, kind, json.dumps(payload), _now()))

    def events(self, task_id: str, kind: str | None = None) -> list[dict]:
        query = "SELECT * FROM events WHERE task_id = ?" + (" AND kind = ?" if kind else "") + " ORDER BY id"
        with self._connection() as connection:
            rows = connection.execute(query, (task_id, kind) if kind else (task_id,)).fetchall()
        return [{"kind": row["kind"], "created": row["created"], "run_id": row["run_id"], **json.loads(row["payload"])}
                for row in rows]
