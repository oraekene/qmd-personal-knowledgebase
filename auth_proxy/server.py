"""Auth Proxy HTTP server — runnable side of the split (fixes Divergent Change).

Listens on 127.0.0.1:3210, forwards verbatim to QMD at 127.0.0.1:8181 if authorized.
Preserves method/path/body/headers verbatim; on upstream HTTPError forwards
status/headers/body verbatim (no forced Content-Type overwrite).

Per #18 + spec.md:128-131 + research #4.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from auth_proxy.oauth import handle_oauth_request
from auth_proxy.progressive_tools import get_progressive_tools_manifest, handle_progressive_tool_call
from auth_proxy.prompt_engine import get_prompt_response, list_prompts, synthesize_system_prompt
from auth_proxy.proxy import _UNAUTHORIZED_BODY, _UNAUTHORIZED_HEADERS, check_auth, check_origin

logger = logging.getLogger("auth_proxy")

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def _load_dotenv() -> None:
    """Load repo-root .env variables into os.environ if missing."""
    env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(env_file):
        return
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


def _allowed_origins() -> tuple[str, ...]:
    raw = os.environ.get("QMD_ALLOWED_ORIGINS", "*").strip()
    if not raw or raw == "*":
        return ("*",)
    return tuple(o.strip() for o in raw.split(",") if o.strip()) or ("*",)


def _send_unauthorized(handler: BaseHTTPRequestHandler) -> None:
    """Send 401 plain — deliberately no WWW-Authenticate header."""
    handler.send_response(401)
    for k, v in _UNAUTHORIZED_HEADERS.items():
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(_UNAUTHORIZED_BODY)


def make_handler(token: str, target: str) -> type[BaseHTTPRequestHandler]:
    """Factory so token/target are captured without globals."""

    class Handler(BaseHTTPRequestHandler):
        # class vars for introspection/tests
        expected_token: ClassVar[str] = token
        upstream_target: ClassVar[str] = target

        def handle(self) -> None:
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout, TimeoutError):
                pass
            except OSError as e:
                if getattr(e, "winerror", None) in (10054, 10053) or getattr(e, "errno", None) in (32, 104):
                    pass
                else:
                    raise

        def handle_one_request(self) -> None:
            try:
                super().handle_one_request()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout, TimeoutError):
                pass
            except OSError as e:
                if getattr(e, "winerror", None) in (10054, 10053) or getattr(e, "errno", None) in (32, 104):
                    pass
                else:
                    raise

        def _proxy_request(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            headers = {k: v for k, v in self.headers.items()}
            # OAuth shim: intercept discovery, dynamic registration, authorize, and token exchange
            if handle_oauth_request(self, self.command, self.path, headers, body, token):
                print(f"[AUTH_PROXY] Handled OAuth: {self.command} {self.path}", flush=True)
                return
            if self.command == "OPTIONS":
                self.send_response(204)
                origin = headers.get("Origin", "*")
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Authorization, Content-Type, Accept, User-Agent, X-Requested-With",
                )
                self.send_header("Access-Control-Max-Age", "86400")
                self.end_headers()
                return
            if not check_auth(headers, token):
                print(f"[AUTH_PROXY] 401 Unauthorized: {self.command} {self.path}", flush=True)
                _send_unauthorized(self)
                return
            if not check_origin(headers, _allowed_origins()):
                print(f"[AUTH_PROXY] 403 Forbidden Origin '{headers.get('Origin')}' for {self.path}", flush=True)
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden origin"}')
                return

            req_is_initialize = False
            req_is_tools_list = False
            if self.command == "POST" and self.path.startswith("/mcp") and body:
                try:
                    payload = json.loads(body.decode("utf-8"))
                    m = payload.get("method")

                    # Handle MCP prompts/list directly
                    if m == "prompts/list":
                        resp_payload = {"jsonrpc": "2.0", "id": payload.get("id"), "result": {"prompts": list_prompts()}}
                        resp_body = json.dumps(resp_payload).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(resp_body)))
                        self.end_headers()
                        self.wfile.write(resp_body)
                        return

                    # Handle MCP prompts/get directly
                    if m == "prompts/get":
                        params = payload.get("params", {})
                        p_name = params.get("name", "")
                        p_args = params.get("arguments", {})
                        try:
                            prompt_res = get_prompt_response(p_name, p_args, REPO_ROOT)
                            resp_payload = {"jsonrpc": "2.0", "id": payload.get("id"), "result": prompt_res}
                            status_code = 200
                        except ValueError as err:
                            resp_payload = {
                                "jsonrpc": "2.0",
                                "id": payload.get("id"),
                                "error": {"code": -32602, "message": str(err)},
                            }
                            status_code = 400
                        resp_body = json.dumps(resp_payload).encode("utf-8")
                        self.send_response(status_code)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(resp_body)))
                        self.end_headers()
                        self.wfile.write(resp_body)
                        return

                    if m == "initialize":
                        req_is_initialize = True

                    # Progressive tool disclosure interception
                    prog_mode = os.getenv("PROGRESSIVE_TOOLS", "auto").lower()
                    if m == "tools/list":
                        if prog_mode in ("1", "true", "on"):
                            resp_payload = {
                                "jsonrpc": "2.0",
                                "id": payload.get("id"),
                                "result": {"tools": get_progressive_tools_manifest()},
                            }
                            resp_body = json.dumps(resp_payload).encode("utf-8")
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.send_header("Content-Length", str(len(resp_body)))
                            self.end_headers()
                            self.wfile.write(resp_body)
                            return
                        else:
                            req_is_tools_list = True

                    if m == "tools/call":
                        tool_name = payload.get("params", {}).get("name", "")
                        if tool_name in (
                            "skills_list",
                            "skill_view",
                            "tool_search",
                            "tool_describe",
                            "tool_call",
                        ):
                            tool_args = payload.get("params", {}).get("arguments", {})
                            res = handle_progressive_tool_call(tool_name, tool_args, REPO_ROOT)
                            resp_payload = {
                                "jsonrpc": "2.0",
                                "id": payload.get("id"),
                                "result": res,
                            }
                            resp_body = json.dumps(resp_payload).encode("utf-8")
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.send_header("Content-Length", str(len(resp_body)))
                            self.end_headers()
                            self.wfile.write(resp_body)
                            return

                    # If tools/call query in cpu-only mode without explicit rerank, default to rerank=False for sub-second response
                    retrieval_mode = os.getenv("RETRIEVAL_MODE", "cpu-only").lower()
                    if (
                        retrieval_mode == "cpu-only"
                        and m == "tools/call"
                        and payload.get("params", {}).get("name") == "query"
                    ):
                        args = payload.setdefault("params", {}).setdefault("arguments", {})
                        if "rerank" not in args:
                            args["rerank"] = False
                            body = json.dumps(payload).encode("utf-8")
                except Exception:
                    pass

            url = target + self.path
            # Preserve verbatim method via self.command; body only if present
            data = body if body else None
            req = urllib.request.Request(url, data=data, method=self.command)
            for k, v in self.headers.items():
                if k.lower() not in ("host", "content-length"):
                    req.add_header(k, v)

            # Ensure Accept header includes both application/json and text/event-stream
            # to satisfy QMD MCP server transport requirement (#881 / MCP 2024-11-05).
            accept_val = req.get_header("Accept", "")
            if not accept_val or accept_val == "*/*":
                req.headers["Accept"] = "application/json, text/event-stream"
            elif "text/event-stream" not in accept_val:
                req.headers["Accept"] = f"{accept_val}, text/event-stream"

            try:
                resp_cm = None
                max_attempts = 3
                last_err = None
                for attempt in range(max_attempts):
                    try:
                        resp_cm = urllib.request.urlopen(req)
                        break
                    except (urllib.error.URLError, TimeoutError) as conn_err:
                        last_err = conn_err
                        # Fallback between 127.0.0.1 and localhost if IPv4/IPv6 loopback differs
                        fallback_url = None
                        if "127.0.0.1" in url:
                            fallback_url = url.replace("127.0.0.1", "localhost")
                        elif "localhost" in url:
                            fallback_url = url.replace("localhost", "127.0.0.1")
                        if fallback_url:
                            try:
                                fallback_req = urllib.request.Request(
                                    fallback_url, data=data, method=self.command, headers=req.headers
                                )
                                resp_cm = urllib.request.urlopen(fallback_req)
                                break
                            except (urllib.error.URLError, TimeoutError) as fb_err:
                                last_err = fb_err
                        if attempt < max_attempts - 1:
                            time.sleep(0.2 * (attempt + 1))
                if resp_cm is None:
                    raise last_err

                with resp_cm as resp:
                    resp_body = resp.read()

                    # If response is to initialize, inject synthesized system prompt instructions & prompts capability
                    if req_is_initialize and resp.status == 200:
                        try:
                            raw_text = resp_body.decode("utf-8")
                            is_sse = False
                            prefix = ""
                            suffix = ""
                            json_text = raw_text

                            if "data: " in raw_text:
                                is_sse = True
                                lines = raw_text.splitlines(keepends=True)
                                for i, line in enumerate(lines):
                                    if line.startswith("data: "):
                                        prefix = "".join(lines[:i]) + "data: "
                                        suffix = "".join(lines[i + 1:])
                                        json_text = line[len("data: "):].strip()
                                        break

                            init_data = json.loads(json_text)
                            if "result" in init_data:
                                qmd_instructions = init_data["result"].get("instructions", "")
                                synthesized = synthesize_system_prompt(REPO_ROOT)
                                combined = f"{synthesized}\n\n---\n\n{qmd_instructions}" if qmd_instructions else synthesized
                                init_data["result"]["instructions"] = combined
                                caps = init_data["result"].setdefault("capabilities", {})
                                caps["prompts"] = {}

                                if is_sse:
                                    resp_body = (prefix + json.dumps(init_data) + suffix).encode("utf-8")
                                else:
                                    resp_body = json.dumps(init_data).encode("utf-8")
                        except Exception as ex:
                            logger.warning("Failed to inject initialize instructions: %s", ex)

                    # If response is to tools/list, ensure progressive tools are also available
                    if req_is_tools_list and resp.status == 200:
                        try:
                            raw_text = resp_body.decode("utf-8")
                            is_sse = False
                            prefix = ""
                            suffix = ""
                            json_text = raw_text

                            if "data: " in raw_text:
                                is_sse = True
                                lines = raw_text.splitlines(keepends=True)
                                for i, line in enumerate(lines):
                                    if line.startswith("data: "):
                                        prefix = "".join(lines[:i]) + "data: "
                                        suffix = "".join(lines[i + 1:])
                                        json_text = line[len("data: "):].strip()
                                        break

                            t_data = json.loads(json_text)
                            if "result" in t_data and "tools" in t_data["result"]:
                                existing_names = {t["name"] for t in t_data["result"]["tools"]}
                                for pt in get_progressive_tools_manifest():
                                    if pt["name"] not in existing_names:
                                        t_data["result"]["tools"].append(pt)
                                if is_sse:
                                    resp_body = (prefix + json.dumps(t_data) + suffix).encode("utf-8")
                                else:
                                    resp_body = json.dumps(t_data).encode("utf-8")
                        except Exception as ex:
                            logger.warning("Failed to inject progressive tools into tools/list response: %s", ex)

                    self.send_response(resp.status)
                    # Strip hop-by-hop headers to prevent protocol breakage (e.g. dechunked body with chunked header)
                    for k, v in resp.headers.items():
                        if k.lower() not in _HOP_BY_HOP and k.lower() != "content-length":
                            self.send_header(k, v)
                    self.send_header("Content-Length", str(len(resp_body)))
                    self.end_headers()
                    self.wfile.write(resp_body)
                    print(f"[AUTH_PROXY] 200 Forwarded {self.command} {self.path} ({len(resp_body)} bytes)", flush=True)
            except urllib.error.HTTPError as e:
                # Forward upstream error verbatim — status/headers/body, stripping hop-by-hop headers
                err_body = e.read() if hasattr(e, "read") else b""
                self.send_response(e.code)
                if e.headers is not None:
                    for k, v in e.headers.items():
                        if k.lower() not in _HOP_BY_HOP and k.lower() != "content-length":
                            self.send_header(k, v)
                else:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_body)))
                self.end_headers()
                self.wfile.write(err_body)
                print(f"[AUTH_PROXY] Upstream {e.code} for {self.command} {self.path}", flush=True)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.error):
                return
            except OSError as e:
                if getattr(e, "winerror", None) in (10054, 10053) or getattr(e, "errno", None) in (32, 104):
                    return
                raise
            except Exception as e:
                if isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionRefusedError)):
                    logger.error("Proxy upstream connection failed for %s %s: %s", self.command, self.path, e)
                else:
                    logger.exception("Proxy upstream forwarding error")
                try:
                    err_bytes = json.dumps({"error": f"Bad Gateway: {e}"}).encode("utf-8")
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(err_bytes)))
                    self.end_headers()
                    self.wfile.write(err_bytes)
                    print(f"[AUTH_PROXY] 502 Bad Gateway for {self.command} {self.path}: {e}", flush=True)
                except Exception:
                    pass

        # Verb-preserving: each HTTP verb delegates to _proxy_request
        def do_GET(self) -> None:  # noqa: N802
            self._proxy_request()

        def do_POST(self) -> None:  # noqa: N802
            self._proxy_request()

        def do_PUT(self) -> None:  # noqa: N802
            self._proxy_request()

        def do_DELETE(self) -> None:  # noqa: N802
            self._proxy_request()

        def do_PATCH(self) -> None:  # noqa: N802
            self._proxy_request()

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._proxy_request()

        def do_HEAD(self) -> None:  # noqa: N802
            self._proxy_request()

        def log_message(self, format: str, *args: object) -> None:
            sys.stderr.write(
                "%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), format % args)
            )

    return Handler


def main() -> None:
    _load_dotenv()
    token = os.environ.get("AUTH_PROXY_TOKEN", "")
    if not token:
        if os.environ.get("ALLOW_INSECURE_DEFAULT"):
            token = "secret123"
            print("WARNING: AUTH_PROXY_TOKEN not set — using insecure default secret123 (ALLOW_INSECURE_DEFAULT=1).", file=sys.stderr)
        else:
            print(
                "ERROR: AUTH_PROXY_TOKEN not set — fail-closed. Set AUTH_PROXY_TOKEN or ALLOW_INSECURE_DEFAULT=1 for local smoke.",
                file=sys.stderr,
            )
            # Fail-closed: use placeholder that never matches, so every request 401
            token = "__UNSET_AUTH_PROXY_TOKEN__"

    target = os.environ.get("QMD_TARGET", "http://localhost:8181")
    listen_port = int(os.environ.get("PROXY_PORT", "3210"))
    if _allowed_origins() == ("*",):
        print(
            "INFO: QMD_ALLOWED_ORIGINS=* — Origin passthrough (fail-open). "
            "Set QMD_ALLOWED_ORIGINS=https://claude.ai to 403 spoofed Origins in proxy.",
            file=sys.stderr,
        )

    handler_cls = make_handler(token, target)
    print(f"Auth Proxy listening on 127.0.0.1:{listen_port} -> {target}")
    print(
        'Smoke: curl -i -X POST http://127.0.0.1:3210/mcp -H "Authorization: Bearer $AUTH_PROXY_TOKEN" '
        '-d \'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\''
    )
    try:
        server = ThreadingHTTPServer(("127.0.0.1", listen_port), handler_cls)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)


if __name__ == "__main__":
    main()


