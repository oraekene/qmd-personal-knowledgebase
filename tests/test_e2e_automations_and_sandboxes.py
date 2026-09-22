"""E2E Test Suite 6: Server-Side Crons, Automations & Multi-Tier Sandboxes.

Tests end-to-end automation and sandboxing:
- 5-part cron syntax matching and next-run calculation
- Interval shorthands (@every 30m, @hourly, @daily, @weekly)
- SchedulerStore persistence, CRUD, and default jobs in automations.json
- LocalSubprocessSandbox execution, environment isolation, and strict timeout enforcement
- On-demand manual job triggering (trigger_job) and last_status/last_run_at tracking
- Cloud sandbox tier fallback when cloud VM providers are unconfigured
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from control_plane.sandbox import (
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


@pytest.fixture
def scheduler_workspace(tmp_path: pathlib.Path):
    """Sets up an isolated workspace for scheduler and sandboxes."""
    auto_file = tmp_path / "automations.json"
    return tmp_path, auto_file


def test_e2e_cron_parser_and_interval_calculation():
    """Verifies standard 5-part cron syntax, step expressions, and shorthands."""
    # 1. Exact minute and hour matching
    dt1 = datetime.datetime(2026, 9, 22, 14, 30, tzinfo=datetime.timezone.utc)
    assert matches_cron(dt1, "30 14 * * *") is True
    assert matches_cron(dt1, "0 14 * * *") is False

    # 2. Step expressions (every 15 minutes)
    assert matches_cron(dt1, "*/15 * * * *") is True
    dt_off = datetime.datetime(2026, 9, 22, 14, 31, tzinfo=datetime.timezone.utc)
    assert matches_cron(dt_off, "*/15 * * * *") is False

    # 3. Next run calculation for interval shorthand
    base_dt = datetime.datetime(2026, 9, 22, 10, 0, 0, tzinfo=datetime.timezone.utc)
    next_30m = compute_next_run("@every 30m", from_dt=base_dt)
    assert next_30m == base_dt + datetime.timedelta(minutes=30)

    # 4. Next run for @daily (02:00 AM UTC)
    next_daily = compute_next_run("@daily", from_dt=base_dt)
    assert next_daily.hour == 2
    assert next_daily.minute == 0
    assert next_daily > base_dt


def test_e2e_scheduler_store_crud_and_persistence(scheduler_workspace: tuple[pathlib.Path, pathlib.Path]):
    """Verifies that jobs can be loaded, created, updated, and deleted from disk."""
    ws, auto_file = scheduler_workspace
    store = SchedulerStore(file_path=auto_file)

    # 1. Verify default jobs initialized
    jobs = store.load_jobs()
    assert len(jobs) >= 5
    job_ids = [j.id for j in jobs]
    assert "job_inbox_ingest" in job_ids

    # 2. Create custom automation job
    custom_job = AutomationJob(
        id="job_custom_analytics",
        name="Run Daily Analytics",
        action="custom_command",
        schedule="0 5 * * *",
        params={"command": "python -c 'print(1)'"},
        tier="local",
        enabled=True,
    )
    store.upsert_job(custom_job)

    # Verify persistence
    reloaded = store.get_job("job_custom_analytics")
    assert reloaded is not None
    assert reloaded.name == "Run Daily Analytics"

    # 3. Update existing job
    reloaded.params = {"command": "python -c 'print(2)'"}
    store.upsert_job(reloaded)
    updated = store.get_job("job_custom_analytics")
    assert updated.params["command"] == "python -c 'print(2)'"

    # 4. Delete job
    deleted = store.delete_job("job_custom_analytics")
    assert deleted is True
    assert store.get_job("job_custom_analytics") is None


def test_e2e_local_sandbox_execution_and_timeout(scheduler_workspace: tuple[pathlib.Path, pathlib.Path]):
    """Verifies subprocess execution, stdout capture, and timeout protection."""
    ws, _ = scheduler_workspace
    sandbox = LocalSubprocessSandbox(repo_root=ws)

    # 1. Successful execution
    res = sandbox.run_command([sys.executable, "-c", "print('HELLO_SANDBOX')"], timeout=10)
    assert res.success is True
    assert res.exit_code == 0
    assert "HELLO_SANDBOX" in res.stdout

    # 2. Failing execution
    res_err = sandbox.run_command([sys.executable, "-c", "import sys; sys.exit(42)"], timeout=10)
    assert res_err.success is False
    assert res_err.exit_code == 42

    # 3. Timeout enforcement
    res_timeout = sandbox.run_command(
        [sys.executable, "-c", "import time; time.sleep(3)"],
        timeout=1,
    )
    assert res_timeout.success is False
    assert res_timeout.exit_code == -1
    assert "TimeoutExpired: 1s" in res_timeout.error_message


def test_e2e_scheduler_daemon_trigger_and_state_update(scheduler_workspace: tuple[pathlib.Path, pathlib.Path]):
    """Verifies that triggering a job updates last_status, last_run_at, and calculates next_run_at."""
    ws, auto_file = scheduler_workspace
    store = SchedulerStore(file_path=auto_file)

    # Add a safe test job using custom_command
    test_job = AutomationJob(
        id="job_test_ping",
        name="Ping Test",
        action="custom_command",
        schedule="@hourly",
        params={"command": f"{sys.executable} -c \"print('JOB_EXECUTED_OK')\""},
        tier="local",
        enabled=True,
    )
    store.upsert_job(test_job)

    daemon = SchedulerDaemon(repo_root=ws, store=store)

    # Trigger job manually
    run_result = daemon.trigger_job("job_test_ping")
    assert run_result.success is True
    assert "JOB_EXECUTED_OK" in run_result.stdout

    # Verify job record updated in store
    job_record = store.get_job("job_test_ping")
    assert job_record.last_status == "success"
    assert job_record.last_run_at is not None
    assert job_record.next_run_at is not None
    assert job_record.last_error is None


def test_e2e_cloud_sandbox_tier_graceful_handling(scheduler_workspace: tuple[pathlib.Path, pathlib.Path]):
    """Verifies that requesting cloud tier when unconfigured returns graceful error without crash."""
    ws, _ = scheduler_workspace
    res = execute_action(
        action="custom_command",
        params={"command": "echo test"},
        tier="cloud",
        repo_root=ws,
    )
    assert res.success is False
    assert res.tier == "cloud"
    # Either e2b or modal uninstalled message
    assert "not installed" in res.stderr.lower() or "not configured" in res.stderr.lower() or res.exit_code != 0
