"""Durable, ordered wiring changes shared by local capture and future cloud playback."""

import json
import random
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def normalize_pairs(pairs: Any) -> List[List[str]]:
    result = set()
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("每条接线必须包含两个端子")
        a, b = (str(value).strip() for value in pair)
        if not a or not b or a == b:
            raise ValueError("接线端子不能为空或相同")
        result.add(tuple(sorted((a, b))))
    return [list(pair) for pair in sorted(result)]


class WiringRecorder:
    def __init__(self, path: Path, recover: bool = False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.clocks: Dict[str, float] = {}
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS recordings (
                    id TEXT PRIMARY KEY, metadata TEXT NOT NULL,
                    started_at TEXT NOT NULL, ended_at TEXT,
                    status TEXT NOT NULL, initial_pairs TEXT NOT NULL,
                    current_pairs TEXT NOT NULL, score REAL NOT NULL,
                    last_seq INTEGER NOT NULL DEFAULT 0,
                    last_batch INTEGER NOT NULL DEFAULT 0,
                    elapsed_ms INTEGER NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_recording
                    ON recordings(status) WHERE status = 'recording';
                CREATE TABLE IF NOT EXISTS batches (
                    recording_id TEXT NOT NULL, batch_id INTEGER NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY(recording_id, batch_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    recording_id TEXT NOT NULL, seq INTEGER NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY(recording_id, seq)
                );
            """)
            if recover:
                db.execute("UPDATE recordings SET status='interrupted', ended_at=? "
                           "WHERE status='recording'", (utc_now(),))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def begin(self, metadata: Dict[str, Any], pairs: Any, score: float = 0) -> str:
        metadata = dict(metadata, initial_score=score)
        initial = json.dumps(normalize_pairs(pairs), ensure_ascii=False)
        recording_id = uuid.uuid4().hex
        with self.lock, self.connection() as db:
            db.execute(
                "INSERT INTO recordings "
                "(id, metadata, started_at, status, initial_pairs, current_pairs, score) "
                "VALUES (?, ?, ?, 'recording', ?, ?, ?)",
                (recording_id, json.dumps(metadata, ensure_ascii=False), utc_now(), initial, initial, score),
            )
            self.clocks[recording_id] = time.monotonic()
        return recording_id

    def append_snapshot(self, recording_id: str, pairs: Any, score: float,
                        source: str = "stm32") -> List[Dict[str, Any]]:
        current = normalize_pairs(pairs)
        with self.lock, self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
            if row is None:
                raise KeyError(recording_id)
            if row["status"] != "recording":
                raise ValueError("记录已结束，无法追加接线")
            previous = {tuple(pair) for pair in json.loads(row["current_pairs"])}
            latest = {tuple(pair) for pair in current}
            changes = [("add", pair) for pair in sorted(latest - previous)]
            changes += [("remove", pair) for pair in sorted(previous - latest)]
            random.shuffle(changes)
            batch_id = row["last_batch"] + 1
            elapsed_ms = max(row["elapsed_ms"], int(
                (time.monotonic() - self.clocks[recording_id]) * 1000))
            timestamp = utc_now()
            events = []
            for index, (operation, pair) in enumerate(changes, 1):
                seq = row["last_seq"] + index
                event = {
                    "event_id": f"{recording_id}:{seq}", "seq": seq,
                    "batch_id": batch_id, "index_in_batch": index,
                    "timestamp": timestamp, "elapsed_ms": elapsed_ms,
                    "operation": operation, "terminals": list(pair),
                    "order_in_batch": "randomized" if len(changes) > 1 else "single",
                }
                db.execute("INSERT INTO events VALUES (?, ?, ?)",
                           (recording_id, seq, json.dumps(event, ensure_ascii=False)))
                events.append(event)
            batch = {
                "batch_id": batch_id, "timestamp": timestamp, "elapsed_ms": elapsed_ms,
                "source": source, "first_seq": events[0]["seq"] if events else None,
                "last_seq": events[-1]["seq"] if events else None,
                "event_count": len(events), "pairs": current, "score_after_batch": score,
            }
            db.execute("INSERT INTO batches VALUES (?, ?, ?)",
                       (recording_id, batch_id, json.dumps(batch, ensure_ascii=False)))
            db.execute("UPDATE recordings SET current_pairs=?, score=?, last_seq=?, "
                       "last_batch=?, elapsed_ms=? WHERE id=?",
                       (json.dumps(current, ensure_ascii=False), score,
                        row["last_seq"] + len(events), batch_id, elapsed_ms, recording_id))
        return events

    def finish(self, recording_id: str, status: str = "completed") -> None:
        if status not in {"completed", "failed", "interrupted"}:
            raise ValueError("无效的记录状态")
        with self.lock, self.connection() as db:
            db.execute("UPDATE recordings SET status=?, ended_at=? WHERE id=? AND status='recording'",
                       (status, utc_now(), recording_id))
            self.clocks.pop(recording_id, None)

    def list_recordings(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT id, metadata, started_at, ended_at, status, last_seq, "
                              "last_batch, elapsed_ms FROM recordings "
                              "ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [dict(row, metadata=json.loads(row["metadata"])) for row in rows]

    def read(self, recording_id: str, after_seq: int = 0,
             limit: Optional[int] = None) -> Dict[str, Any]:
        # One read transaction keeps the manifest, events and batches at the same revision.
        with self.connection() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
            if row is None:
                raise KeyError(recording_id)
            query = "SELECT data FROM events WHERE recording_id=? AND seq>? ORDER BY seq"
            args = [recording_id, after_seq]
            if limit is not None:
                query += " LIMIT ?"
                args.append(limit)
            events = [json.loads(item[0]) for item in db.execute(query, args)]
            through_seq = events[-1]["seq"] if events else after_seq
            if limit is None:
                batches = db.execute("SELECT data FROM batches WHERE recording_id=? ORDER BY batch_id",
                                     (recording_id,)).fetchall()
            else:
                batches = []
                batch_ids = sorted({event["batch_id"] for event in events})
                for batch_id in batch_ids:
                    batches.append(db.execute("SELECT data FROM batches WHERE recording_id=? AND batch_id=?",
                                              (recording_id, batch_id)).fetchone())
            return {
                "schema_version": 1, "recording_id": recording_id,
                "capture_semantics": "stm32_reported_pairs",
                "batch_order_policy": "shuffle_once_on_capture",
                "metadata": json.loads(row["metadata"]),
                "started_at": row["started_at"], "ended_at": row["ended_at"],
                "status": row["status"], "elapsed_ms": row["elapsed_ms"],
                "initial_state": {"pairs": json.loads(row["initial_pairs"]),
                                  "score": json.loads(row["metadata"]).get("initial_score", 0)},
                "latest_state": {"pairs": json.loads(row["current_pairs"]), "score": row["score"]},
                "last_seq": row["last_seq"], "last_batch": row["last_batch"],
                "next_after_seq": through_seq, "has_more": through_seq < row["last_seq"],
                "events": events, "batches": [json.loads(item[0]) for item in batches],
            }
