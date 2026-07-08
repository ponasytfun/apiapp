# API App

A local Codex-style chat workspace for OpenAI-compatible APIs.

## Features

- First-launch API key setup
- Configurable OpenAI-compatible Base URL and model ID
- Streaming chat responses
- Multiple local chat histories
- Stop and regenerate controls
- Markdown-style rendering and fenced code blocks
- Copy message and copy code actions
- Editable chat titles
- System prompt, temperature, and max-token settings
- Responsive dark interface
- No package manager or third-party Python dependencies

## Run on Windows

Double-click `run.bat`.

The app starts a local server at `http://127.0.0.1:8765` and opens your browser automatically.

## Run on macOS/Linux

```bash
chmod +x run.sh
./run.sh
```

Or run directly:

```bash
python3 app.py
```

## API compatibility

The app sends requests to:

```text
{Base URL}/chat/completions
```

The endpoint should implement OpenAI-compatible streaming chat completions using `data:` server-sent events.

Examples of Base URL values:

```text
https://api.openai.com/v1
http://127.0.0.1:1234/v1
https://your-provider.example/v1
```

Use the exact model ID supported by your provider.

## API key handling

- The API key is never committed to this repository.
- By default, the key is kept in browser `sessionStorage`.
- Selecting **Remember key on this device** stores it in browser `localStorage`.
- The local Python proxy forwards the key to the configured API endpoint for each request.
- Chat history and non-secret settings are stored locally in the browser.

Because remembered browser storage is readable by anyone with access to the same local browser profile, do not enable key persistence on a shared machine.

## Architecture

- `app.py`: dependency-free local HTTP server and streaming API proxy
- `index.html`: application shell and settings/setup dialogs
- `styles.css`: responsive dark workspace styling
- `app.js`: chat state, streaming parser, local persistence, rendering, controls
- `run.bat`: Windows launcher
- `run.sh`: macOS/Linux launcher

## Notes

This app intentionally has no npm build step and no external Python packages. It is designed to clone and run with a normal Python 3 installation.
