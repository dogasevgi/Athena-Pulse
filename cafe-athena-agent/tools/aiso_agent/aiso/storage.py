"""Every query result is stored, so any run can be re-scored or compared later."""
from __future__ import annotations
import json
import os
import sqlite3
import time
import uuid

from .queries import categorize

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, label TEXT, kind TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS results (
  run_id TEXT, query_id TEXT, query TEXT, category TEXT, platform TEXT,
  answer TEXT, restaurants TEXT, target_pos INTEGER, created_at REAL);
"""


class DB:
    def __init__(self, path="out/aiso.db"):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(results)")}
        if "sources" not in cols:  # migrate older databases
            self.con.execute("ALTER TABLE results ADD COLUMN sources TEXT")

    def new_run(self, label: str, kind: str = "live") -> str:
        run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.con.execute("INSERT INTO runs VALUES (?,?,?,?)", (run_id, label, kind, time.time()))
        self.con.commit()
        return run_id

    def add_result(self, run_id, q, platform, answer, restaurants, pos, sources=None):
        self.con.execute(
            "INSERT INTO results (run_id, query_id, query, category, platform, answer, "
            "restaurants, target_pos, created_at, sources) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, q["id"], q["text"], q["category"], platform, answer,
             json.dumps(restaurants), pos, time.time(), json.dumps(sources or [])))
        self.con.commit()

    def runs(self, kind: str | None = None) -> list[dict]:
        sql = "SELECT * FROM runs" + (" WHERE kind=?" if kind else "") + " ORDER BY created_at"
        return [dict(r) for r in self.con.execute(sql, (kind,) if kind else ())]

    def results(self, run_id: str) -> list[dict]:
        rows = self.con.execute("SELECT * FROM results WHERE run_id=?", (run_id,))
        out = []
        for r in rows:
            d = dict(r)
            d["restaurants"] = json.loads(d["restaurants"])
            d["sources"] = json.loads(d.get("sources") or "[]")
            d["category"] = categorize(d["query"])  # same rules for old and new runs
            out.append(d)
        return out

    def latest(self, kind: str | None = None, label: str | None = None) -> str | None:
        runs = [r for r in self.runs(kind) if label is None or r["label"] == label]
        return runs[-1]["run_id"] if runs else None
