from __future__ import annotations

import json
import mimetypes
import os
import threading
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def load_env_file(path: Path) -> None:
    """Load a simple .env file without third-party dependencies.

    Existing process environment variables win over values from the file.
    Supports KEY=value, optional export prefix, and quoted values.
    """
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


load_env_file(ROOT / ".env")

HOST = os.environ.get("APIAPP_HOST", "127.0.0.1")
PORT = int(os.environ.get("APIAPP_PORT", "8765"))
ENV_API_KEY = os.environ.get("APIAPP_API_KEY", "").strip()
ENV_BASE_URL = os.environ.get("APIAPP_BASE_URL", "https://integrate.api.nvidia.com/v1").strip().rstrip("/")
ENV_MODEL = os.environ.get("APIAPP_MODEL", "deepseek-ai/deepseek-v4-pro").strip()
ENV_TEMPERATURE = float(os.environ.get("APIAPP_TEMPERATURE", "1"))
ENV_TOP_P = float(os.environ.get("APIAPP_TOP_P", "0.95"))
ENV_MAX_TOKENS = int(os.environ.get("APIAPP_MAX_TOKENS", "16384"))
ENV_THINKING = os.environ.get("APIAPP_THINKING", "false").strip().lower() in {"1", "true", "yes", "on"}


class AppHandler(BaseHTTPRequestHandler):
    server_version = "APIApp/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        # Keep the terminal readable. Errors are still surfaced to the client.
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self._send_json(200, {"ok": True, "envConfigured": bool(ENV_API_KEY)})
            return

        if path == "/api/config":
            self._send_json(
                200,
                {
                    "hasEnvApiKey": bool(ENV_API_KEY),
                    "baseUrl": ENV_BASE_URL,
                    "model": ENV_MODEL,
                    "temperature": ENV_TEMPERATURE,
                    "topP": ENV_TOP_P,
                    "maxTokens": ENV_MAX_TOKENS,
                    "thinking": ENV_THINKING,
                },
            )
            return

        if path == "/":
            path = "/index.html"

        requested = (ROOT / path.lstrip("/")).resolve()
        if ROOT not in requested.parents and requested != ROOT:
            self._send_json(403, {"error": "Forbidden"})
            return
        if not requested.is_file():
            self._send_json(404, {"error": "Not found"})
            return

        content = requested.read_bytes()
        mime = mimetypes.guess_type(str(requested))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        if self.path != "/api/chat":
            self._send_json(404, {"error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 10_000_000:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send_json(400, {"error": f"Invalid request: {exc}"})
            return

        api_key = str(payload.pop("apiKey", "")).strip() or ENV_API_KEY
        base_url = str(payload.pop("baseUrl", "")).strip().rstrip("/") or ENV_BASE_URL
        if not api_key:
            self._send_json(400, {"error": "API key is required. Add it in the app or set APIAPP_API_KEY in .env"})
            return
        if not base_url.startswith(("http://", "https://")):
            self._send_json(400, {"error": "Base URL must start with http:// or https://"})
            return

        payload["model"] = str(payload.get("model") or ENV_MODEL)
        payload["temperature"] = float(payload.get("temperature", ENV_TEMPERATURE))
        payload["top_p"] = float(payload.get("top_p", ENV_TOP_P))
        payload["max_tokens"] = int(payload.get("max_tokens", ENV_MAX_TOKENS))
        payload["stream"] = True
        payload.setdefault("chat_template_kwargs", {"thinking": ENV_THINKING})

        target = f"{base_url}/chat/completions"
        request = urllib.request.Request(
            target,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": "APIApp/1.1",
            },
            method="POST",
        )

        try:
            upstream = urllib.request.urlopen(request, timeout=300)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw)
            except json.JSONDecodeError:
                detail = {"error": raw or exc.reason}
            self._send_json(exc.code, {"error": "Upstream API error", "detail": detail})
            return
        except (urllib.error.URLError, TimeoutError) as exc:
            self._send_json(502, {"error": f"Could not reach API: {exc}"})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.end_headers()

        try:
            while True:
                chunk = upstream.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            upstream.close()


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    url = f"http://{HOST}:{PORT}"
    print(f"API App running at {url}")
    print(f"Provider: {ENV_BASE_URL}")
    print(f"Model: {ENV_MODEL}")
    print(f".env API key loaded: {'yes' if ENV_API_KEY else 'no'}")
    print("Close this window or press Ctrl+C to stop it.")
    threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
