# API App

A local Codex-style chat workspace for OpenAI-compatible APIs.

## Features

- First-launch API key setup
- Optional `.env` based private API key loading
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

## Private API key setup with `.env`

Create a local `.env` file next to `app.py`:

```bash
cp .env.example .env
```

Then edit `.env` and put your real API key there:

```env
APIAPP_API_KEY=replace-with-your-real-key
APIAPP_BASE_URL=https://integrate.api.nvidia.com/v1
APIAPP_MODEL=deepseek-ai/deepseek-v4-pro
APIAPP_TEMPERATURE=1
APIAPP_TOP_P=0.95
APIAPP_MAX_TOKENS=16384
```

The real `.env` file is ignored by Git. Do not commit it, screenshot it, paste it into Discord, or otherwise feed the credential goblins.

Accepted API key variable names:

```text
APIAPP_API_KEY
NVIDIA_API_KEY
OPENAI_API_KEY
```

`APIAPP_API_KEY` takes priority, then `NVIDIA_API_KEY`, then `OPENAI_API_KEY`.

When a server-side key exists, the browser setup screen is skipped and requests use the `.env` key automatically. You can still enter a browser key if you want to override it temporarily.

## API compatibility

The app sends requests to:

```text
{Base URL}/chat/completions
```

The endpoint should implement OpenAI-compatible streaming chat completions using `data:` server-sent events.

Examples of Base URL values:

```text
https://integrate.api.nvidia.com/v1
https://api.openai.com/v1
http://127.0.0.1:1234/v1
https://your-provider.example/v1
```

Use the exact model ID supported by your provider.

## API key handling

- The API key is never committed to this repository.
- Recommended: put your key in a local `.env` file.
- Browser fallback: by default, a manually entered key is kept in browser `sessionStorage`.
- Selecting **Remember key on this device** stores a manually entered key in browser `localStorage`.
- The local Python proxy forwards the key to the configured API endpoint for each request.
- Chat history and non-secret settings are stored locally in the browser.

Because remembered browser storage is readable by anyone with access to the same local browser profile, do not enable key persistence on a shared machine.

## Architecture

- `app.py`: dependency-free local HTTP server, `.env` loader, and streaming API proxy
- `.env.example`: safe template for private local configuration
- `index.html`: application shell and settings/setup dialogs
- `styles.css`: responsive dark workspace styling
- `app.js`: chat state, streaming parser, local persistence, rendering, controls
- `run.bat`: Windows launcher
- `run.sh`: macOS/Linux launcher

## Notes

This app intentionally has no npm build step and no external Python packages. It is designed to clone and run with a normal Python 3 installation.
