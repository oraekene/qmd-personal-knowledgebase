"""Orchestrator — single re-index + failure isolation + CrawlState.

Per #10 locked contract + research #2 + spec.md:120-124:
- Python + OS scheduler (Task Scheduler / systemd) runs connectors on independent schedules
- Each connector: try fetch_recent(since) -> write_unit; set_last_seen(now) only on success, else log+continue
- Persists CrawlState corpus/_state/crawl_state.json (atomic, gitignored)
- After all connectors: exactly one qmd update && qmd embed (no per-collection hooks), then isolated llmwiki compile --stale
- Env secrets never in YAML, VPS-ready rsync

This is the production orchestrator for #15 — testable via run_once.
"""
from __future__ import annotations
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, List

from connectors.sdk.state import CrawlState
from connectors.sdk.writer import write_unit

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("corpus/_state/crawl_state.json")
DEFAULT_CORPUS_ROOT = Path("corpus")


@dataclass(frozen=True)
class OrchestratorConfig:
    """Single locality for pipeline knobs + Corpus-relative paths (issue #22).

    Parses env once so wiki_runner/mirror_runner closures stop scattering
    os.environ.get across the module. Paths resolve from corpus_root.
    Note: MIRROR_TOKEN is deliberately NOT parsed here — it stays behind
    load_mirror_token() so the secret never lands in a logged/repr'd config.
    """

    corpus_root: Path = DEFAULT_CORPUS_ROOT
    wiki_enabled: bool = True
    wiki_mode: str = "compile"
    wiki_min_interval_hours: float = 0.0
    mirror_host: str = "https://qmd-mirror.pages.dev"
    dist_dir: Path = field(default_factory=lambda: Path("dist"))

    @property
    def wiki_state_file(self) -> Path:
        from scripts.wiki import resolve_state_path

        return resolve_state_path(self.corpus_root)

    @classmethod
    def from_env(cls, corpus_root: Path = DEFAULT_CORPUS_ROOT) -> "OrchestratorConfig":
        enabled = os.environ.get("WIKI_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
        mode = os.environ.get("WIKI_MODE", "compile").strip().lower() or "compile"
        try:
            min_hours = float(os.environ.get("WIKI_MIN_INTERVAL_HOURS", "0").strip() or "0")
        except ValueError:
            min_hours = 0.0
        host = os.environ.get("MIRROR_HOST", "https://qmd-mirror.pages.dev").strip() or "https://qmd-mirror.pages.dev"
        dist_raw = os.environ.get("MIRROR_DIST", "dist").strip() or "dist"
        return cls(
            corpus_root=corpus_root,
            wiki_enabled=enabled,
            wiki_mode=mode,
            wiki_min_interval_hours=min_hours,
            mirror_host=host,
            dist_dir=Path(dist_raw),
        )


def run_once(
    connectors: List,
    corpus_root: Path,
    state_path: Path,
    qmd_runner: Callable[[], int],
    wiki_runner: Callable[[], int],
    now: datetime | None = None,
    mirror_runner: Callable[[], int] | None = None,
) -> None:
    """Run one orchestrator cycle: connectors -> single qmd -> isolated wiki -> isolated mirror.

    - connectors: list of SourcePlugin-like objects with NAME and fetch_recent(since)
    - corpus_root: Path("corpus")
    - state_path: Path("corpus/_state/crawl_state.json")
    - qmd_runner: callable that does `qmd update && qmd embed`, returns exit code
    - wiki_runner: callable that does `llmwiki compile --stale`, may raise
    - now: for testing, fixed now; otherwise datetime.now(timezone.utc)
    - mirror_runner: callable that does `build_mirror + wrangler deploy`, may raise, isolated
    """
    if now is None:
        now = datetime.now(timezone.utc)

    state = CrawlState(state_path)
    corpus_root.mkdir(parents=True, exist_ok=True)

    # Default since is 48h ago for production; tests use 2025-01-01 via state default
    default_since = now - timedelta(days=2)

    for connector in connectors:
        name = getattr(connector, "NAME", str(connector))
        try:
            since = state.get_last_seen(name, default_since)
            # Snapshot now before fetch so that last_seen advances to run start on success
            run_start = now
            count = 0
            # fetch_recent may raise (e.g. expired X cookie)
            for payload in connector.fetch_recent(since):
                # For #14 dedup: first-seen-wins is handled at orchestrator level via seen set,
                # but for #15 single-connector test we just write
                # In real orchestrator, dedupe_by_source_id would be called here with shared seen set
                write_unit(payload, corpus_root)
                count += 1
                # Increment per-payload count (optional)
                state.increment_forward_count(name, 1)
            # Success — advance last_seen to run_start (not to payload's created_at)
            state.set_last_seen(name, run_start)
            if count:
                logger.info("Connector %s: wrote %d Units", name, count)
            else:
                logger.info("Connector %s: no new Units", name)
        except Exception as e:
            # Failure isolation: log and continue, do NOT advance last_seen so next run retries same window
            logger.error("Connector %s failed: %s", name, e, exc_info=True)
            continue

    # Persist state once after all connectors (atomic)
    state.save()

    # Single qmd update && qmd embed after all connectors — exactly one call
    try:
        qmd_runner()
    except Exception as e:
        logger.error("qmd update && qmd embed failed: %s", e, exc_info=True)

    # Isolated wiki compile — failure does not block qmd or mirror
    try:
        wiki_runner()
    except Exception as e:
        logger.error("Wiki synthesis failed (isolated): %s", e, exc_info=True)

    # Isolated mirror build + deploy — failure does not block indexing
    if mirror_runner is not None:
        try:
            mirror_runner()
        except Exception as e:
            logger.error("Mirror build/deploy failed (isolated): %s", e, exc_info=True)


if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description="QMD Knowledgebase Orchestrator")
    parser.add_argument("--source", help="Run only this source (e.g. github, twitter)")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS_ROOT), help="corpus root")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="state file")
    args = parser.parse_args()

    # Discovery — load all connectors from connectors/
    from connectors.sdk.discovery import load_plugins

    plugins = load_plugins(Path("connectors"))
    connectors = list(plugins.values())
    if args.source:
        connectors = [c for c in connectors if c.NAME == args.source]
        if not connectors:
            print(f"No connector named {args.source}")
            raise SystemExit(1)

    corpus_root = Path(args.corpus)
    state_path = Path(args.state)

    def qmd_runner():
        import subprocess
        # Single re-index: qmd update && qmd embed (no per-collection hooks)
        # Use subprocess; in tests this is mocked
        result = subprocess.run(["qmd", "update"], check=False)
        if result.returncode != 0:
            raise RuntimeError(f"qmd update failed {result.returncode}")
        result = subprocess.run(["qmd", "embed"], check=False)
        if result.returncode != 0:
            raise RuntimeError(f"qmd embed failed {result.returncode}")
        return 0

    def wiki_runner():
        # Wiki synthesis after embed — config locality via OrchestratorConfig (issue #22).
        cfg = OrchestratorConfig.from_env(corpus_root)
        if not cfg.wiki_enabled:
            logger.info("Wiki compile skipped — WIKI_ENABLED=0 (frequency knob)")
            return 0
        try:
            if cfg.wiki_min_interval_hours > 0:
                state_file = cfg.wiki_state_file
                if state_file.exists():
                    import time

                    age_h = (time.time() - state_file.stat().st_mtime) / 3600.0
                    if age_h < cfg.wiki_min_interval_hours:
                        logger.info(
                            "Wiki compile skipped — last compile %.1fh ago < WIKI_MIN_INTERVAL_HOURS=%.1f",
                            age_h,
                            cfg.wiki_min_interval_hours,
                        )
                        return 0
        except Exception as e:
            logger.warning("Wiki interval check failed, proceeding: %s", e)

        try:
            from scripts.wiki import compile_wiki, refresh_stale

            if cfg.wiki_mode in ("refresh", "stale", "refresh --stale"):
                result = refresh_stale(corpus_root)
            else:
                result = compile_wiki(corpus_root)
            logger.info("Wiki compile result: %s", result)
            return 0
        except Exception as e:
            # Provider guard throws ProviderUnavailableError (provider-guard.ts) — log and re-raise for isolation
            logger.error("Wiki compile failed: %s", e, exc_info=True)
            raise

    def mirror_runner():
        import subprocess

        # Reuse shared token loader — fixes Duplicated Code with scripts/build_mirror
        from scripts.build_mirror import build_mirror, load_mirror_token

        token = load_mirror_token()
        if not token:
            logger.warning("MIRROR_TOKEN not set and mirror-token.txt missing — skipping mirror build (isolated)")
            return 0

        cfg = OrchestratorConfig.from_env(corpus_root)
        host = cfg.mirror_host
        try:
            dist = cfg.dist_dir
            build_mirror(corpus_root, dist, token, host)
            logger.info("Mirror built to %s with token %s... host %s", dist, token[:6], host)
        except Exception as e:
            logger.error("Mirror build failed: %s", e, exc_info=True)
            raise

        api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        if not api_token or not account_id:
            logger.info("Skipping wrangler deploy — CLOUDFLARE_API_TOKEN/ACCOUNT_ID not set (local build only)")
            return 0

        result = subprocess.run(
            ["npx", "wrangler", "pages", "deploy", "dist", "--project-name", "qmd-mirror", "--branch", "main"],
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"wrangler pages deploy failed {result.returncode}")
        logger.info("Mirror deployed via wrangler pages deploy")
        return 0

    run_once(connectors, corpus_root, state_path, qmd_runner, wiki_runner, mirror_runner=mirror_runner)
