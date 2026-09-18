"""Server-Side Crons, Automations & Scheduled Tasks Engine (Feature 6).

Evaluates cron schedules and interval expressions against `automations.json`.
Executes jobs locally or delegates to cloud sandboxes.
Streams execution logs into SystemLogger and persists run history.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from control_plane.sandbox import SandboxResult, execute_action

logger = logging.getLogger("control_plane.scheduler")

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTOMATIONS_FILE = REPO_ROOT / "automations.json"


# ----------------------------------------------------------------------
# Schedule Evaluator (Cron & Shorthand Parser)
# ----------------------------------------------------------------------

def _match_cron_field(val: int, expr: str) -> bool:
    """Check if an integer matches a single cron field expression."""
    expr = expr.strip()
    if expr == "*":
        return True
    if "/" in expr:
        base, step = expr.split("/", 1)
        step_i = int(step)
        start = 0 if base == "*" else int(base)
        return (val >= start) and ((val - start) % step_i == 0)
    if "-" in expr:
        start_s, end_s = expr.split("-", 1)
        return int(start_s) <= val <= int(end_s)
    if "," in expr:
        return any(_match_cron_field(val, sub) for sub in expr.split(","))
    return int(expr) == val


def matches_cron(dt: datetime.datetime, cron_str: str) -> bool:
    """Evaluate 5-part cron syntax: minute hour day_of_month month day_of_week."""
    parts = cron_str.strip().split()
    if len(parts) != 5:
        return False
    min_expr, hr_expr, dom_expr, mon_expr, dow_expr = parts

    # Python weekday(): Monday=0, Sunday=6; Cron 0 or 7 is Sunday
    cron_dow = (dt.weekday() + 1) % 7

    if not _match_cron_field(dt.minute, min_expr):
        return False
    if not _match_cron_field(dt.hour, hr_expr):
        return False
    if not _match_cron_field(dt.day, dom_expr):
        return False
    if not _match_cron_field(dt.month, mon_expr):
        return False
    if not _match_cron_field(cron_dow, dow_expr):
        return False
    return True


def compute_next_run(
    schedule_str: str,
    from_dt: Optional[datetime.datetime] = None,
) -> datetime.datetime:
    """Calculate the next execution timestamp from a cron or shorthand expression."""
    base_dt = from_dt or datetime.datetime.now(datetime.timezone.utc)
    # Strip seconds and microseconds for minute-level granularity
    curr = base_dt.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)

    s = schedule_str.strip().lower()

    # Handle interval shorthands
    if s.startswith("@every"):
        m = re.match(r"@every\s+(\d+)\s*(m|min|minute|minutes|h|hr|hour|hours|d|day|days)?", s)
        if m:
            num = int(m.group(1))
            unit = (m.group(2) or "m").lower()
            if unit.startswith("h"):
                delta = datetime.timedelta(hours=num)
            elif unit.startswith("d"):
                delta = datetime.timedelta(days=num)
            else:
                delta = datetime.timedelta(minutes=num)
            return base_dt + delta

    if s == "@hourly":
        s = "0 * * * *"
    elif s == "@daily":
        s = "0 2 * * *"  # 02:00 AM UTC
    elif s == "@weekly":
        s = "0 3 * * 0"  # Sunday 03:00 AM UTC
    elif s == "@monthly":
        s = "0 4 1 * *"  # 1st of month 04:00 AM UTC

    # Standard 5-part cron evaluation: scan up to 365 days
    for _ in range(60 * 24 * 365):
        if matches_cron(curr, s):
            return curr
        curr += datetime.timedelta(minutes=1)

    # Fallback to 1 hour if expression could not match
    return base_dt + datetime.timedelta(hours=1)


# ----------------------------------------------------------------------
# Job Data Model & Store
# ----------------------------------------------------------------------

@dataclasses.dataclass
class AutomationJob:
    id: str
    name: str
    action: str  # ingest_inbox, github_sync, reindex, deploy_mirror, compile_wiki, reach_ingest, custom_command
    schedule: str  # Cron expression or shorthand
    params: Dict[str, Any] = dataclasses.field(default_factory=dict)
    tier: str = "local"  # "local" | "cloud"
    enabled: bool = True
    last_run_at: Optional[str] = None
    last_status: Optional[str] = "never"  # "never" | "running" | "success" | "failed"
    last_error: Optional[str] = None
    next_run_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AutomationJob:
        return cls(
            id=data.get("id") or str(uuid.uuid4())[:8],
            name=data.get("name", "Unnamed Job"),
            action=data.get("action", "ingest_inbox"),
            schedule=data.get("schedule", "@hourly"),
            params=data.get("params", {}),
            tier=data.get("tier", "local"),
            enabled=data.get("enabled", True),
            last_run_at=data.get("last_run_at"),
            last_status=data.get("last_status", "never"),
            last_error=data.get("last_error"),
            next_run_at=data.get("next_run_at"),
        )


DEFAULT_JOBS = [
    {
        "id": "job_inbox_ingest",
        "name": "Automatic Inbox Ingestion",
        "action": "ingest_inbox",
        "schedule": "@every 30m",
        "params": {},
        "tier": "local",
        "enabled": True,
    },
    {
        "id": "job_github_sync",
        "name": "GitHub Repositories Tracking Sync",
        "action": "github_sync",
        "schedule": "0 2 * * *",
        "params": {},
        "tier": "local",
        "enabled": True,
    },
    {
        "id": "job_reindex",
        "name": "Vector & BM25 Index Maintenance",
        "action": "reindex",
        "schedule": "0 3 * * *",
        "params": {},
        "tier": "local",
        "enabled": True,
    },
    {
        "id": "job_deploy_mirror",
        "name": "Cloudflare Pages Mirror Deployment",
        "action": "deploy_mirror",
        "schedule": "0 4 * * *",
        "params": {},
        "tier": "local",
        "enabled": True,
    },
    {
        "id": "job_compile_wiki",
        "name": "Workers AI Wiki Synthesis",
        "action": "compile_wiki",
        "schedule": "@weekly",
        "params": {"max_items": 15},
        "tier": "local",
        "enabled": False,
    },
]


class SchedulerStore:
    """Manages reading and writing of automations.json."""

    def __init__(self, file_path: Path | None = None) -> None:
        self.file_path = Path(file_path) if file_path else AUTOMATIONS_FILE
        self._lock = threading.Lock()
        self._ensure_init()

    def _ensure_init(self) -> None:
        if not self.file_path.exists():
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            initial = []
            for item in DEFAULT_JOBS:
                job = AutomationJob.from_dict(item)
                job.next_run_at = compute_next_run(job.schedule, now_dt).isoformat()
                initial.append(job.to_dict())
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self.file_path.write_text(json.dumps({"automations": initial}, indent=2), encoding="utf-8")

    def load_jobs(self) -> List[AutomationJob]:
        with self._lock:
            try:
                data = json.loads(self.file_path.read_text(encoding="utf-8"))
                jobs = [AutomationJob.from_dict(j) for j in data.get("automations", [])]
                # Ensure all jobs have a calculated next_run_at
                dirty = False
                now_dt = datetime.datetime.now(datetime.timezone.utc)
                for j in jobs:
                    if not j.next_run_at and j.enabled:
                        j.next_run_at = compute_next_run(j.schedule, now_dt).isoformat()
                        dirty = True
                if dirty:
                    self._save_unlocked(jobs)
                return jobs
            except Exception as e:
                logger.error("Failed to load automations.json: %s", e)
                return []

    def save_jobs(self, jobs: List[AutomationJob]) -> None:
        with self._lock:
            self._save_unlocked(jobs)

    def _save_unlocked(self, jobs: List[AutomationJob]) -> None:
        data = {"automations": [j.to_dict() for j in jobs]}
        self.file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_job(self, job_id: str) -> Optional[AutomationJob]:
        jobs = self.load_jobs()
        for j in jobs:
            if j.id == job_id:
                return j
        return None

    def upsert_job(self, job: AutomationJob) -> None:
        jobs = self.load_jobs()
        idx = next((i for i, j in enumerate(jobs) if j.id == job.id), None)
        if idx is not None:
            jobs[idx] = job
        else:
            jobs.append(job)
        self.save_jobs(jobs)

    def delete_job(self, job_id: str) -> bool:
        jobs = self.load_jobs()
        orig_len = len(jobs)
        jobs = [j for j in jobs if j.id != job_id]
        if len(jobs) != orig_len:
            self.save_jobs(jobs)
            return True
        return False


# ----------------------------------------------------------------------
# Background Scheduler Daemon
# ----------------------------------------------------------------------

class SchedulerDaemon:
    """Background thread that checks for due jobs and dispatches execution."""

    def __init__(
        self,
        repo_root: Path | None = None,
        store: SchedulerStore | None = None,
        check_interval_seconds: float = 10.0,
        logger_func: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.repo_root = Path(repo_root) if repo_root else REPO_ROOT
        self.store = store or SchedulerStore(self.repo_root / "automations.json")
        self.check_interval = check_interval_seconds
        self.logger_func = logger_func
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name="SchedulerDaemon", daemon=True)
        self._thread.start()
        logger.info("SchedulerDaemon started (interval=%0.1fs)", self.check_interval)

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("SchedulerDaemon stopped")

    def _log(self, level: str, msg: str) -> None:
        if self.logger_func:
            try:
                self.logger_func(level, msg)
            except Exception:
                pass
        else:
            logger.info("[%s] %s", level.upper(), msg)

    def _run_loop(self) -> None:
        while self._running:
            try:
                self.tick()
            except Exception as e:
                logger.error("Error in scheduler tick: %s", e)
            time.sleep(self.check_interval)

    def tick(self) -> None:
        """Single tick evaluating all jobs against current time."""
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        jobs = self.store.load_jobs()
        updated = False

        for job in jobs:
            if not job.enabled:
                continue

            # Check if job is due
            is_due = False
            if job.next_run_at:
                try:
                    next_dt = datetime.datetime.fromisoformat(job.next_run_at)
                    if next_dt.tzinfo is None:
                        next_dt = next_dt.replace(tzinfo=datetime.timezone.utc)
                    if now_dt >= next_dt:
                        is_due = True
                except Exception:
                    is_due = True
            else:
                is_due = True

            if is_due and job.last_status != "running":
                updated = True
                self._execute_job_sync(job, now_dt)

        if updated:
            self.store.save_jobs(jobs)

    def trigger_job(self, job_id: str) -> SandboxResult:
        """Trigger an automation job immediately on demand."""
        job = self.store.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        res = self._execute_job_sync(job, now_dt)
        self.store.upsert_job(job)
        return res

    def _execute_job_sync(self, job: AutomationJob, now_dt: datetime.datetime) -> SandboxResult:
        self._log("info", f"⚡ Executing automation [{job.name}] (action={job.action}, tier={job.tier})")
        job.last_status = "running"
        job.last_run_at = now_dt.isoformat()

        # Run via sandbox
        res = execute_action(
            action=job.action,
            params=job.params,
            tier=job.tier,
            repo_root=self.repo_root,
        )

        if res.success:
            job.last_status = "success"
            job.last_error = None
            self._log("info", f"✅ Automation [{job.name}] completed in {res.duration_seconds}s")
        else:
            job.last_status = "failed"
            job.last_error = res.stderr or res.error_message or "Execution failed"
            self._log("error", f"❌ Automation [{job.name}] failed: {job.last_error}")

        # Compute next scheduled execution
        next_dt = compute_next_run(job.schedule, now_dt)
        job.next_run_at = next_dt.isoformat()
        return res
