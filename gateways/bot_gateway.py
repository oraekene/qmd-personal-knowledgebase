"""Multi-Client Bot Gateways (Telegram, Discord, Custom GPT Actions).

Routes mobile and external chat client requests to the QMD knowledgebase
and Pi Agent autonomous execution engine:
1. TelegramBotHandler: Webhook / polling processor for Telegram commands (/search, /get, /ingest, /run).
2. DiscordBotHandler: Interaction processor for Discord slash commands.
3. Custom GPT OpenAPI Spec generator for OpenAI Actions.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional
import urllib.error
import urllib.request

logger = logging.getLogger("bot_gateway")

REPO_ROOT = Path(__file__).resolve().parent.parent


class TelegramBotHandler:
    """Handles Telegram Bot updates and command routing to Pi and QMD."""

    def __init__(self, pi_bridge: Any | None = None, repo_root: Path | None = None):
        self.repo_root = repo_root or REPO_ROOT
        if pi_bridge is not None:
            self.pi = pi_bridge
        else:
            from control_plane.pi_bridge import PiBridge
            self.pi = PiBridge(repo_root=self.repo_root)
            self.pi.start()

    def handle_update(self, update: Dict[str, Any]) -> Dict[str, Any]:
        """Process an incoming Telegram update payload."""
        message = update.get("message") or update.get("edited_message")
        if not message:
            return {"status": "ignored", "reason": "no message found"}

        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()
        if not text:
            return {"status": "ignored", "chat_id": chat_id, "reason": "empty text"}

        response_text = self._route_command(text, chat_id)
        # Telegram hard limit: 4096 characters per message
        if len(response_text) > 4000:
            response_text = response_text[:3990] + "\n\n...[Truncated by Telegram limit]"

        return {
            "status": "handled",
            "chat_id": chat_id,
            "reply": response_text,
        }

    def _route_command(self, text: str, chat_id: Optional[int]) -> str:
        if text.startswith(("/start", "/help")):
            return (
                "🤖 *QMD Knowledgebase & Pi Agent Bot*\n\n"
                "Available commands:\n"
                "• `/search <query>` — Sub-second BM25 & semantic search\n"
                "• `/get <file>` — Read specific corpus document\n"
                "• `/ingest <url>` — Ingest YouTube, Twitter, Reddit, or Web page\n"
                "• `/status` — Knowledgebase and daemon readiness\n"
                "• `/run <goal>` — Run multi-step autonomous goal with Pi Agent\n\n"
                "Or simply send any question directly to execute with Pi Agent!"
            )

        if text.startswith("/status"):
            from auth_proxy.progressive_tools import call_tool
            try:
                res = call_tool("status", {}, self.repo_root)
                return f"📊 *Knowledgebase Status*:\n```\n{res}\n```"
            except Exception as e:
                return f"❌ Status check failed: {e}"

        if text.startswith("/search"):
            query = text[len("/search"):].strip()
            if not query:
                return "⚠️ Usage: `/search <keywords>`"
            from auth_proxy.progressive_tools import call_tool
            try:
                res = call_tool("search", {"query": query}, self.repo_root)
                return f"🔍 *Search Results for* `{query}`:\n\n{res}"
            except Exception as e:
                return f"❌ Search error: {e}"

        if text.startswith("/get"):
            filepath = text[len("/get"):].strip()
            if not filepath:
                return "⚠️ Usage: `/get <corpus/notes/file.md>`"
            from auth_proxy.progressive_tools import call_tool
            try:
                res = call_tool("get", {"file": filepath}, self.repo_root)
                return f"📄 *{filepath}*:\n\n```markdown\n{res}\n```"
            except Exception as e:
                return f"❌ Read error: {e}"

        if text.startswith("/ingest"):
            url = text[len("/ingest"):].strip()
            if not url:
                return "⚠️ Usage: `/ingest <url>`"
            from auth_proxy.progressive_tools import call_tool
            try:
                res = call_tool("ingest_url", {"url": url}, self.repo_root)
                return f"📥 *Ingested Successfully*:\nTitle: {res.get('title')}\nSaved to: `{res.get('file')}`\nSummary: {res.get('summary', 'Done.')}"
            except Exception as e:
                return f"❌ Ingest error: {e}"

        if text.startswith("/run"):
            goal = text[len("/run"):].strip()
            if not goal:
                return "⚠️ Usage: `/run <goal prompt>`"
            res = self.pi.execute_goal(goal)
            return f"⚡ *Pi Agent Result*:\n\n{res.get('response', 'Completed.')}"

        # Default fallback: Freeform prompt routed directly to Pi Agent
        res = self.pi.execute_goal(text)
        return res.get("response", "Completed.")


class DiscordBotHandler:
    """Handles Discord Interaction Webhooks and slash commands."""

    def __init__(self, pi_bridge: Any | None = None, repo_root: Path | None = None):
        self.repo_root = repo_root or REPO_ROOT
        if pi_bridge is not None:
            self.pi = pi_bridge
        else:
            from control_plane.pi_bridge import PiBridge
            self.pi = PiBridge(repo_root=self.repo_root)
            self.pi.start()

    def handle_interaction(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Discord slash command interaction (Type 2: APPLICATION_COMMAND)."""
        interaction_type = payload.get("type")
        if interaction_type == 1:  # PING
            return {"type": 1}

        data = payload.get("data", {})
        cmd_name = data.get("name", "")
        options = {opt.get("name"): opt.get("value") for opt in data.get("options", [])}

        if cmd_name == "search":
            query = options.get("query", "")
            from auth_proxy.progressive_tools import call_tool
            try:
                res = call_tool("search", {"query": query}, self.repo_root)
                msg = f"🔍 **Search Results for** `{query}`:\n\n{res}"
            except Exception as e:
                msg = f"❌ Search error: {e}"

        elif cmd_name == "get":
            file = options.get("file", "")
            from auth_proxy.progressive_tools import call_tool
            try:
                res = call_tool("get", {"file": file}, self.repo_root)
                msg = f"📄 **{file}**:\n```markdown\n{res[:1800]}\n```"
            except Exception as e:
                msg = f"❌ Read error: {e}"

        elif cmd_name == "run":
            goal = options.get("goal", "")
            res = self.pi.execute_goal(goal)
            msg = f"⚡ **Pi Agent Result**:\n\n{res.get('response', 'Completed.')}"

        else:
            msg = f"Unknown command: {cmd_name}"

        # Truncate to Discord 2000 char limit
        if len(msg) > 1950:
            msg = msg[:1940] + "\n...[Truncated]"

        return {
            "type": 4,  # CHANNEL_MESSAGE_WITH_SOURCE
            "data": {"content": msg},
        }


def generate_openapi_schema(base_url: str = "https://kb.parmeterai.space") -> Dict[str, Any]:
    """Generate OpenAPI 3.1.0 specification for Custom GPT Actions."""
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "QMD Personal Knowledgebase & Autonomous Pi Engine API",
            "description": "API allowing Custom GPTs, Claude, and external clients to search, retrieve, ingest, and execute autonomous tasks on personal knowledgebase.",
            "version": "1.0.0",
        },
        "servers": [{"url": base_url}],
        "paths": {
            "/api/search": {
                "get": {
                    "summary": "Search personal knowledgebase",
                    "operationId": "searchKnowledgebase",
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "Keywords or search phrase",
                        },
                        {
                            "name": "silo",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string"},
                            "description": "Optional silo filter (notes, wiki, github, chats, pdfs, web, twitter)",
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Search results list with snippets and filenames",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
            "/api/pi/goal": {
                "post": {
                    "summary": "Execute autonomous multi-step goal with Pi Agent",
                    "operationId": "executePiGoal",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "prompt": {"type": "string", "description": "Goal or question for Pi Agent"},
                                        "model": {"type": "string", "description": "Optional model override"},
                                    },
                                    "required": ["prompt"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Completed response with executed tool calls",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
            "/api/connectors/reach": {
                "post": {
                    "summary": "Ingest web content or social media into knowledgebase",
                    "operationId": "ingestUrl",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "url": {"type": "string", "description": "URL to ingest"},
                                        "type": {"type": "string", "description": "Channel type (auto, youtube, twitter, web, etc)"},
                                    },
                                    "required": ["url"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Ingestion confirmation and saved path",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
            "/api/sync/status": {
                "get": {
                    "summary": "Check Cloudflare Artifacts and R2 sync status",
                    "operationId": "getSyncStatus",
                    "responses": {
                        "200": {
                            "description": "Status and recent commit history",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    },
                }
            },
        },
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Bearer token authentication",
                }
            }
        },
        "security": [{"BearerAuth": []}],
    }


def run_telegram_polling(
    token: str | None = None,
    repo_root: Path | None = None,
    poll_interval: float = 2.0,
    stop_event: Any | None = None,
    max_loops: int | None = None,
) -> None:
    """Long-polling daemon runner for Telegram Bot."""
    root = repo_root or REPO_ROOT
    from control_plane.server import read_env_dict
    env = read_env_dict(root / ".env")
    bot_token = token or env.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not configured in .env. Bot gateway cannot poll.")
        return

    handler = TelegramBotHandler(repo_root=root)
    offset = 0
    logger.info("Telegram polling daemon started for QMD Knowledgebase.")
    loop_count = 0

    while True:
        if stop_event and stop_event.is_set():
            logger.info("Stop event received, terminating Telegram bot polling.")
            break
        if max_loops is not None and loop_count >= max_loops:
            break
        loop_count += 1

        url = f"https://api.telegram.org/bot{bot_token}/getUpdates?offset={offset}&timeout=10"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "QMD-Bot/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok"):
                    for update in data.get("result", []):
                        update_id = update.get("update_id", 0)
                        offset = max(offset, update_id + 1)
                        result = handler.handle_update(update)
                        if result.get("status") == "handled" and result.get("chat_id") and result.get("reply"):
                            chat_id = result["chat_id"]
                            reply = result["reply"]
                            send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                            send_payload = json.dumps({
                                "chat_id": chat_id,
                                "text": reply,
                                "parse_mode": "Markdown",
                            }).encode("utf-8")
                            send_req = urllib.request.Request(
                                send_url,
                                data=send_payload,
                                headers={"Content-Type": "application/json", "User-Agent": "QMD-Bot/1.0"},
                                method="POST",
                            )
                            try:
                                with urllib.request.urlopen(send_req, timeout=10):
                                    pass
                            except Exception as se:
                                logger.warning("Failed to send Telegram message to chat %s: %s", chat_id, se)
        except Exception as e:
            logger.debug("Telegram polling error or timeout: %s", e)

        time.sleep(poll_interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_telegram_polling()

