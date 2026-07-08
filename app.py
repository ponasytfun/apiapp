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
HOST = "127.0.0.1"
PORT = int(os.environ.get("APIAPP_PORT", "8765"))


def load_dotenv(path: Path) -> None:
    """Small .env loader so the app stays dependency-free."""
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv(ROOT / ".env")

DEFAULT_BASE_URL = os.environ.get("APIAPP_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
DEFAULT_MODEL = os.environ.get("APIAPP_MODEL", "deepseek-ai/deepseek-v4-pro")
DEFAULT_TEMPERATURE = float(os.environ.get("APIAPP_TEMPERATURE", "1"))
DEFAULT_TOP_P = float(os.environ.get("APIAPP_TOP_P", "0.95"))
DEFAULT_MAX_TOKENS = int(os.environ.get("APIAPP_MAX_TOKENS", "16384"))

API_KEY_ENV_NAMES = ("APIAPP_API_KEY", "NVIDIA_API_KEY", "OPENAI_API_KEY")


def get_env_api_key() -> tuple[str, str | None]:
    for name in API_KEY_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value, name
    return "", None


class AppHandler(BaseHTTPRequestHandler):
    server_version = "APIApp/1.0"

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
            self._send_json(200, {"ok": True})
            return

        if path == "/api/config":
            _, key_source = get_env_api_key()
            self._send_json(
                200,
                {
                    "baseUrl": DEFAULT_BASE_URL,
                    "model": DEFAULT_MODEL,
                    "temperature": DEFAULT_TEMPERATURE,
                    "topP": DEFAULT_TOP_P,
                    "maxTokens": DEFAULT_MAX_TOKENS,
                    "hasServerApiKey": key_source is not None,
                    "apiKeySource": key_source,
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

        env_api_key, _ = get_env_api_key()
        api_key = str(payload.pop("apiKey", "")).strip() or env_api_key
        base_url = str(payload.pop("baseUrl", DEFAULT_BASE_URL)).strip().rstrip("/") or DEFAULT_BASE_URL
        if not api_key:
            self._send_json(400, {"error": "API key is required. Put it in .env or enter it in the app."})
            return
        if not base_url.startswith(("http://", "https://")):
            self._send_json(400, {"error": "Base URL must start with http:// or https://"})
            return

        payload.setdefault("temperature", DEFAULT_TEMPERATURE)
        payload.setdefault("top_p", DEFAULT_TOP_P)
        payload.setdefault("max_tokens", DEFAULT_MAX_TOKENS)
        payload.setdefault("stream", True)

        if base_url == "https://integrate.api.nvidia.com/v1" and "chat_template_kwargs" not in payload:
            payload["chat_template_kwargs"] = {"thinking": False}

        target = f"{base_url}/chat/completions"
        request = urllib.request.Request(
            target,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": "APIApp/1.0",
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
    key_source = get_env_api_key()[1]
    if key_source:
        print(f"Loaded API key from {key_source}.")
    else:
        print("No .env API key found. The browser setup screen will ask for one.")
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
