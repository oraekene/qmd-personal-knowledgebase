"""Tests for Server-Side Crons, Automations & Sandboxes (Feature 6)."""

from __future__ import annotations

import datetime
import json
import os
import sys
import time
from pathlib import Path
import pytest

from control_plane.sandbox import (
    CloudSandbox,
    LocalSubprocessSandbox,
    SandboxResult,
    execute_action,
)
from control_plane.scheduler import (
    AutomationJob,
    SchedulerDaemon,
    SchedulerStore,
    compute_next_run,
    matches_cron,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------------
# 1. Cron Evaluator Tests
# ----------------------------------------------------------------------

def test_matches_cron_wildcards() -> None:
    dt = datetime.datetime(2026, 9, 18, 14, 30, tzinfo=datetime.timezone.utc)
    assert matches_cron(dt, "* * * * *") is True
    assert matches_cron(dt, "30 * * * *") is True
    assert matches_cron(dt, "15 * * * *") is False
    assert matches_cron(dt, "* 14 * * *") is True
    assert matches_cron(dt, "* 10 * * *") is False


def test_matches_cron_steps_and_ranges() -> None:
    dt = datetime.datetime(2026, 9, 18, 14, 45, tzinfo=datetime.timezone.utc)
    assert matches_cron(dt, "*/15 * * * *") is True
    assert matches_cron(dt, "*/10 * * * *") is False
    assert matches_cron(dt, "40-50 * * * *") is True
    assert matches_cron(dt, "0-30 * * * *") is False
    assert matches_cron(dt, "15,30,45 * * * *") is True


def test_compute_next_run_intervals() -> None:
    base_dt = datetime.datetime(2026, 9, 18, 12, 0, 0, tzinfo=datetime.timezone.utc)
    # @every 15m
    next_15 = compute_next_run("@every 15m", from_dt=base_dt)
    assert (next_15 - base_dt).total_seconds() == 15 * 60

    # @every 2h
    next_2h = compute_next_run("@every 2h", from_dt=base_dt)
    assert (next_2h - base_dt).total_seconds() == 2 * 3600

    # @hourly
    next_hourly = compute_next_run("@hourly", from_dt=base_dt)
    assert next_hourly.minute == 0
    assert next_hourly > base_dt

    # Daily at 02:00
    next_daily = compute_next_run("0 2 * * *", from_dt=base_dt)
    assert next_daily.hour == 2
    assert next_daily.minute == 0
    assert next_daily > base_dt


# ----------------------------------------------------------------------
# 2. Scheduler Store & Jobs Tests
# ----------------------------------------------------------------------

def test_scheduler_store_crud(tmp_path: Path) -> None:
    store_file = tmp_path / "automations.json"
    store = SchedulerStore(store_file)

    # Initial defaults should be generated
    jobs = store.load_jobs()
    assert len(jobs) >= 5
    job_ids = {j.id for j in jobs}
    assert "job_inbox_ingest" in job_ids

    # Upsert new job
    custom_job = AutomationJob(
        id="test_job_1",
        name="Test Job",
        action="custom_command",
        schedule="@every 10m",
        params={"command": "echo test"},
        tier="local",
        enabled=True,
    )
    store.upsert_job(custom_job)

    loaded = store.get_job("test_job_1")
    assert loaded is not None
    assert loaded.name == "Test Job"

    # Delete job
    assert store.delete_job("test_job_1") is True
    assert store.get_job("test_job_1") is None
    assert store.delete_job("non_existent") is False


# ----------------------------------------------------------------------
# 3. Local & Cloud Sandbox Tests
# ----------------------------------------------------------------------

def test_local_sandbox_execution(tmp_path: Path) -> None:
    sandbox = LocalSubprocessSandbox(repo_root=tmp_path)
    py_bin = sys.executable

    # Successful command
    res = sandbox.run_command([py_bin, "-c", "print('hello from sandbox')"], timeout=10)
    assert res.success is True
    assert res.exit_code == 0
    assert "hello from sandbox" in res.stdout
    assert res.tier == "local"
    assert res.duration_seconds >= 0

    # Failing command
    fail_res = sandbox.run_command([py_bin, "-c", "import sys; sys.exit(42)"], timeout=10)
    assert fail_res.success is False
    assert fail_res.exit_code == 42

    # Timeout command
    to_res = sandbox.run_command([py_bin, "-c", "import time; time.sleep(5)"], timeout=1)
    assert to_res.success is False
    assert "timed out" in to_res.stderr.lower() or "timeoutexpired" in str(to_res.error_message).lower()


def test_cloud_sandbox_unconfigured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("SIMULATE_CLOUD_SANDBOX", raising=False)

    cloud = CloudSandbox(repo_root=tmp_path)
    configured, provider = cloud.is_configured()
    assert configured is False
    assert provider == "none"

    res = cloud.run_cloud_task("ingest_inbox", {})
    assert res.success is False
    assert res.error_message == "MissingCloudCredentials"


def test_cloud_sandbox_simulated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SIMULATE_CLOUD_SANDBOX", "1")
    cloud = CloudSandbox(repo_root=tmp_path)
    res = cloud.run_cloud_task("reach_ingest", {"url": "https://example.com"})
    assert res.success is True
    assert res.tier == "cloud"
    assert "Simulated Cloud Sandbox" in res.stdout


def test_execute_action_dispatch(tmp_path: Path) -> None:
    # custom_command
    res = execute_action(
        action="custom_command",
        params={"command": "python -c \"print('action executed')\""},
        tier="local",
        repo_root=tmp_path,
    )
    assert res.success is True
    assert "action executed" in res.stdout

    # Unknown action
    unknown_res = execute_action(action="unknown_action_xyz", repo_root=tmp_path)
    assert unknown_res.success is False
    assert "UnknownAction" in str(unknown_res.error_message)


# ----------------------------------------------------------------------
# 4. Scheduler Daemon Tests
# ----------------------------------------------------------------------

def test_scheduler_daemon_tick_and_trigger(tmp_path: Path) -> None:
    store_file = tmp_path / "automations.json"
    store = SchedulerStore(store_file)

    logs = []
    daemon = SchedulerDaemon(
        repo_root=tmp_path,
        store=store,
        check_interval_seconds=1.0,
        logger_func=lambda lvl, msg: logs.append((lvl, msg)),
    )

    # Add a fast custom test job
    job = AutomationJob(
        id="daemon_test_job",
        name="Daemon Test Job",
        action="custom_command",
        schedule="@every 1m",
        params={"command": "python -c \"print('cron tick ok')\""},
        tier="local",
        enabled=True,
        # Set next_run_at in past to force execution on tick
        next_run_at=(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)).isoformat(),
    )
    store.upsert_job(job)

    # Run single tick
    daemon.tick()

    updated = store.get_job("daemon_test_job")
    assert updated is not None
    assert updated.last_status == "success"
    assert updated.last_run_at is not None
    assert any("completed" in m[1].lower() for m in logs)

    # Test manual trigger
    trig_res = daemon.trigger_job("daemon_test_job")
    assert trig_res.success is True
    assert "cron tick ok" in trig_res.stdout
