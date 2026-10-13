"""Serialized local SQLite journal; critical transitions have consistent Drive backups."""
from __future__ import annotations

import copy
import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .config import RouterError

TERMINAL = {"complete", "partial", "failed", "cancelled", "submission_uncertain"}


def now_ms():
    return int(time.time() * 1000)


def canonical(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class Journal:
    def __init__(self, root: Path, drive: Path):
        self.root, self.drive = Path(root).resolve(), Path(drive).resolve()
        if self.root == self.drive or self.drive in self.root.parents:
            raise RouterError("The live journal must be on local disk, outside the persistent Drive folder.")
        self.root.mkdir(parents=True, exist_ok=True)
        self.drive.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._backup_needed = False
        # The OS lock prevents two local router processes sharing a journal.
        self._lock_handle = (self.root / "router.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self._lock_handle.seek(0)
                if not self._lock_handle.read(1):
                    self._lock_handle.write(b"0"); self._lock_handle.flush()
                self._lock_handle.seek(0)
                msvcrt.locking(self._lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lock_handle.close()
            raise RouterError("Another router is using this local state folder.", 503) from exc
        path = self.root / "journal.sqlite3"
        backup = self.drive / "journal.sqlite3"
        if not path.exists() and backup.is_file():
            shutil.copyfile(backup, path)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, client TEXT NOT NULL,
                request TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
                UNIQUE(client,request));
            CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS downloads (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS actions (job TEXT NOT NULL, request TEXT NOT NULL, PRIMARY KEY(job,request));
        """)
        row = self.db.execute("SELECT value FROM meta WHERE key='studioId'").fetchone()
        self.studio_id = row[0] if row else str(uuid.uuid4())
        if not row:
            self.db.execute("INSERT INTO meta VALUES ('studioId',?)", (self.studio_id,))
            self._backup()
        else:
            # A previous local process may have committed before its Drive copy
            # failed. Re-establish that checkpoint before public recovery.
            self._backup_needed = True

    def _backup(self):
        self._backup_needed = True
        # SQLite backup includes committed WAL data without copying live sidecars.
        scratch = self.root / "journal.snapshot.sqlite3"
        with contextlib.closing(sqlite3.connect(scratch)) as dest:
            self.db.backup(dest)
            # Backup can inherit WAL mode. Checkpoint into the standalone file
            # before copying it; no destination sidecar may hold accepted jobs.
            dest.execute("PRAGMA journal_mode=DELETE")
        temporary = self.drive / "journal.sqlite3.part"
        with scratch.open("rb") as source, temporary.open("wb") as target:
            shutil.copyfileobj(source, target)
            target.flush(); os.fsync(target.fileno())
        os.replace(temporary, self.drive / "journal.sqlite3")
        self._backup_needed = False

    def create_job(self, request: dict, workers: list[dict], timeout_seconds: int):
        with self._lock:
            fingerprint = hashlib.sha256(canonical(request).encode()).hexdigest()
            row = self.db.execute("SELECT fingerprint,payload FROM jobs WHERE client=? AND request=?",
                                  (request["clientId"], request["requestId"])).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise RouterError("This request ID already belongs to different settings.", 409, "request_conflict")
                if self._backup_needed:
                    self._backup()  # Retry a failed copy without rewriting each replay.
                return json.loads(row[1]), False
            stamp = now_ms()
            job = copy.deepcopy(request)
            job.update(studioId=self.studio_id, jobId=str(uuid.uuid4()), revision=1, state="accepted",
                       createdAtMillis=stamp, updatedAtMillis=stamp, deadlineMillis=stamp + timeout_seconds * 1000,
                       effectivePrompt=request["originalPrompt"], enhancementStatus="pending",
                       editPlan=None, warnings=[], error=None, workers=copy.deepcopy(workers), candidates=[],
                       selection={"status": "pending", "winnerCandidateId": None, "reason": "", "scores": [],
                                  "reviewerModel": "", "reviewerRevision": ""})
            self.db.execute("INSERT INTO jobs VALUES (?,?,?,?,?)", (job["jobId"], request["clientId"], request["requestId"], fingerprint, canonical(job)))
            self._backup_needed = True
            self._backup()
            return job, True

    def get(self, job_id: str, durable=False):
        with self._lock:
            row = self.db.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise RouterError("That router job is not in this studio.", 404, "not_found")
            if durable and self._backup_needed:
                self._backup()
            return json.loads(row[0])

    def recover(self, client_id: str, request_id: str, durable=False):
        with self._lock:
            row = self.db.execute("SELECT payload FROM jobs WHERE client=? AND request=?", (client_id, request_id)).fetchone()
            if not row:
                raise RouterError("No accepted job has that client/request ID.", 404, "not_found")
            if durable and self._backup_needed:
                self._backup()
            return json.loads(row[0])

    def update(self, job_id: str, transform, durable=True):
        with self._lock:
            job = self.get(job_id)
            transform(job)
            job["revision"] += 1
            job["updatedAtMillis"] = now_ms()
            self.db.execute("UPDATE jobs SET payload=? WHERE id=?", (canonical(job), job_id))
            if durable:
                self._backup_needed = True
                self._backup()
            return job

    def jobs(self):
        with self._lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM jobs ORDER BY rowid")]

    def asset(self, asset_id):
        with self._lock:
            row = self.db.execute("SELECT payload FROM assets WHERE id=?", (asset_id,)).fetchone()
            if not row:
                raise RouterError("That image is not stored in this studio.", 404, "not_found")
            return json.loads(row[0])

    def assets(self):
        with self._lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM assets")]

    def put_asset(self, asset):
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO assets VALUES (?,?)", (asset["assetId"], canonical(asset)))
            self._backup_needed = True
            self._backup()

    def put_download(self, download):
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO downloads VALUES (?,?)", (download["jobId"], canonical(download)))
            self._backup_needed = True
            self._backup()

    def download(self, download_id):
        with self._lock:
            row = self.db.execute("SELECT payload FROM downloads WHERE id=?", (download_id,)).fetchone()
            if not row:
                raise RouterError("That download is not in this studio.", 404, "not_found")
            return json.loads(row[0])

    def retry(self, job_id, request_id, transform):
        """Reserve retry and transition in one transaction; repeating its key is a read."""
        with self._lock:
            job = self.get(job_id)
            if request_id is not None and self.db.execute("SELECT 1 FROM actions WHERE job=? AND request=?", (job_id, request_id)).fetchone():
                if self._backup_needed:
                    self._backup()
                return job, False
            transform(job)
            job["revision"] += 1
            job["updatedAtMillis"] = now_ms()
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute("UPDATE jobs SET payload=? WHERE id=?", (canonical(job), job_id))
                if request_id is not None:
                    self.db.execute("INSERT INTO actions VALUES (?,?)", (job_id, request_id))
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self._backup_needed = True
            self._backup()
            return job, True

    def close(self):
        with self._lock:
            self._backup()
            self.db.close()
            self._lock_handle.close()

