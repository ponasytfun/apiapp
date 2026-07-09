from __future__ import annotations

import json
import os
import queue
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

ROOT = Path(__file__).resolve().parent


def load_env_file(path: Path) -> None:
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
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


load_env_file(ROOT / ".env")


@dataclass
class Settings:
    api_key: str = os.environ.get("APIAPP_API_KEY", "").strip()
    base_url: str = os.environ.get("APIAPP_BASE_URL", "https://integrate.api.nvidia.com/v1").strip().rstrip("/")
    model: str = os.environ.get("APIAPP_MODEL", "deepseek-ai/deepseek-v4-pro").strip()
    temperature: float = float(os.environ.get("APIAPP_TEMPERATURE", "1"))
    top_p: float = float(os.environ.get("APIAPP_TOP_P", "0.95"))
    max_tokens: int = int(os.environ.get("APIAPP_MAX_TOKENS", "16384"))
    thinking: bool = os.environ.get("APIAPP_THINKING", "false").strip().lower() in {"1", "true", "yes", "on"}
    system_prompt: str = (
        "You are a precise coding assistant. Prefer practical solutions, explain tradeoffs clearly, "
        "and never claim to have run tools you did not run."
    )


class ApiApp(tk.Tk):
    BG = "#0b0d10"
    PANEL = "#111419"
    PANEL_2 = "#171b22"
    BORDER = "#2a3039"
    TEXT = "#f2f4f7"
    MUTED = "#9ca6b5"
    ACCENT = "#8b5cf6"
    ACCENT_HOVER = "#7c3aed"
    DANGER = "#ef4444"
    SUCCESS = "#22c55e"

    def __init__(self) -> None:
        super().__init__()
        self.title("API App")
        self.geometry("1180x760")
        self.minsize(860, 600)
        self.configure(bg=self.BG)

        self.settings = Settings()
        self.messages: list[dict[str, str]] = []
        self.worker_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.generating = False

        self._configure_style()
        self._build_ui()
        self._apply_settings_to_controls()
        self.after(80, self._drain_worker_queue)

        if not self.settings.api_key:
            self.after(250, self._show_settings_dialog)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("Top.TFrame", background=self.BG)
        style.configure("App.TLabel", background=self.BG, foreground=self.TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=self.BG, foreground=self.MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=self.BG, foreground=self.TEXT, font=("Segoe UI Semibold", 16))
        style.configure("SidebarTitle.TLabel", background=self.PANEL, foreground=self.TEXT, font=("Segoe UI Semibold", 12))
        style.configure("SidebarMuted.TLabel", background=self.PANEL, foreground=self.MUTED, font=("Segoe UI", 8))
        style.configure("Accent.TButton", background=self.ACCENT, foreground="white", borderwidth=0, padding=(12, 8), font=("Segoe UI Semibold", 9))
        style.map("Accent.TButton", background=[("active", self.ACCENT_HOVER), ("disabled", "#4c3b72")])
        style.configure("Ghost.TButton", background=self.PANEL_2, foreground=self.TEXT, borderwidth=0, padding=(10, 7))
        style.map("Ghost.TButton", background=[("active", "#20262f")])
        style.configure("Danger.TButton", background="#3a1618", foreground="#fecaca", borderwidth=0, padding=(10, 7))
        style.map("Danger.TButton", background=[("active", "#521d21")])
        style.configure("Dark.TCombobox", fieldbackground=self.PANEL_2, background=self.PANEL_2, foreground=self.TEXT, arrowcolor=self.TEXT, bordercolor=self.BORDER, lightcolor=self.BORDER, darkcolor=self.BORDER)

    def _build_ui(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self, style="Panel.TFrame", width=250)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(3, weight=1)

        brand = ttk.Frame(sidebar, style="Panel.TFrame")
        brand.grid(row=0, column=0, sticky="ew", padx=16, pady=(18, 16))
        mark = tk.Label(brand, text="A", bg=self.ACCENT, fg="white", width=3, height=1, font=("Segoe UI Semibold", 14))
        mark.pack(side="left", padx=(0, 10))
        title_box = ttk.Frame(brand, style="Panel.TFrame")
        title_box.pack(side="left")
        ttk.Label(title_box, text="API App", style="SidebarTitle.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="Native coding chat", style="SidebarMuted.TLabel").pack(anchor="w")

        ttk.Button(sidebar, text="+ New chat", style="Accent.TButton", command=self._new_chat).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        ttk.Label(sidebar, text="CHAT", style="SidebarMuted.TLabel").grid(row=2, column=0, sticky="w", padx=18, pady=(4, 6))

        self.chat_status = tk.Label(
            sidebar,
            text="New chat\n\nMessages stay in memory until you close the app.",
            justify="left",
            anchor="nw",
            wraplength=210,
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Segoe UI", 9),
        )
        self.chat_status.grid(row=3, column=0, sticky="nsew", padx=18, pady=8)

        ttk.Button(sidebar, text="Settings", style="Ghost.TButton", command=self._show_settings_dialog).grid(row=4, column=0, sticky="ew", padx=16, pady=(8, 16))

        main = ttk.Frame(self, style="App.TFrame")
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        top = ttk.Frame(main, style="Top.TFrame")
        top.grid(row=0, column=0, sticky="ew", padx=22, pady=(16, 10))
        top.columnconfigure(0, weight=1)

        title_area = ttk.Frame(top, style="Top.TFrame")
        title_area.grid(row=0, column=0, sticky="w")
        ttk.Label(title_area, text="Workspace", style="Title.TLabel").pack(anchor="w")
        self.connection_label = ttk.Label(title_area, text="Not configured", style="Muted.TLabel")
        self.connection_label.pack(anchor="w", pady=(2, 0))

        self.model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(
            top,
            textvariable=self.model_var,
            state="normal",
            width=36,
            style="Dark.TCombobox",
            values=(
                "deepseek-ai/deepseek-v4-pro",
                "deepseek-ai/deepseek-v4-flash",
                "openai/gpt-oss-120b",
                "qwen/qwen3.5-122b-a10b",
            ),
        )
        self.model_combo.grid(row=0, column=1, padx=(12, 8))
        ttk.Button(top, text="Clear", style="Ghost.TButton", command=self._clear_chat).grid(row=0, column=2)

        transcript_frame = tk.Frame(main, bg=self.BG)
        transcript_frame.grid(row=1, column=0, sticky="nsew", padx=22, pady=(2, 12))
        transcript_frame.rowconfigure(0, weight=1)
        transcript_frame.columnconfigure(0, weight=1)

        self.transcript = ScrolledText(
            transcript_frame,
            wrap="word",
            bg=self.BG,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            selectbackground="#4c1d95",
            relief="flat",
            borderwidth=0,
            padx=18,
            pady=16,
            font=("Segoe UI", 10),
            state="disabled",
        )
        self.transcript.grid(row=0, column=0, sticky="nsew")
        self.transcript.tag_configure("user_name", foreground="#c4b5fd", font=("Segoe UI Semibold", 10), spacing1=14, spacing3=4)
        self.transcript.tag_configure("assistant_name", foreground="#86efac", font=("Segoe UI Semibold", 10), spacing1=14, spacing3=4)
        self.transcript.tag_configure("body", foreground=self.TEXT, lmargin1=4, lmargin2=4, spacing3=10)
        self.transcript.tag_configure("muted", foreground=self.MUTED, font=("Segoe UI", 9))
        self.transcript.tag_configure("error", foreground="#fecaca", background="#2b1114", spacing1=8, spacing3=8)

        composer = tk.Frame(main, bg=self.PANEL_2, highlightbackground=self.BORDER, highlightthickness=1)
        composer.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 18))
        composer.columnconfigure(0, weight=1)

        self.prompt = tk.Text(
            composer,
            height=4,
            wrap="word",
            bg=self.PANEL_2,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            selectbackground="#4c1d95",
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=10,
            font=("Segoe UI", 10),
        )
        self.prompt.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.prompt.bind("<Return>", self._on_return)

        ttk.Label(composer, text="Enter to send · Shift+Enter for newline", style="Muted.TLabel").grid(row=1, column=0, sticky="w", padx=12, pady=(0, 10))
        self.stop_button = ttk.Button(composer, text="Stop", style="Danger.TButton", command=self._stop_generation)
        self.stop_button.grid(row=1, column=1, padx=(8, 6), pady=(0, 8))
        self.stop_button.state(["disabled"])
        self.send_button = ttk.Button(composer, text="Send", style="Accent.TButton", command=self._send_message)
        self.send_button.grid(row=1, column=2, padx=(0, 8), pady=(0, 8))

        self._append_system_hint()

    def _append_system_hint(self) -> None:
        self._append_text("API App\n", "assistant_name")
        self._append_text("Enter your NVIDIA API key in Settings, then start chatting.\n", "muted")

    def _apply_settings_to_controls(self) -> None:
        self.model_var.set(self.settings.model)
        self._refresh_connection_status()

    def _refresh_connection_status(self) -> None:
        if self.settings.api_key:
            host = self.settings.base_url.replace("https://", "").replace("http://", "")
            self.connection_label.configure(text=f"{host} · ready")
        else:
            self.connection_label.configure(text="No API key configured")

    def _new_chat(self) -> None:
        if self.generating:
            messagebox.showwarning("Generation running", "Stop the current generation before starting a new chat.")
            return
        self.messages.clear()
        self._replace_transcript("")
        self._append_system_hint()
        self.chat_status.configure(text="New chat\n\n0 messages")
        self.prompt.focus_set()

    def _clear_chat(self) -> None:
        self._new_chat()

    def _show_settings_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("API App Settings")
        dialog.geometry("650x560")
        dialog.minsize(560, 500)
        dialog.configure(bg=self.PANEL)
        dialog.transient(self)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)

        def add_label(row: int, text: str) -> None:
            tk.Label(dialog, text=text, bg=self.PANEL, fg=self.MUTED, font=("Segoe UI Semibold", 9)).grid(row=row, column=0, sticky="nw", padx=(20, 12), pady=8)

        def add_entry(row: int, variable: tk.Variable, show: str | None = None) -> tk.Entry:
            entry = tk.Entry(dialog, textvariable=variable, show=show or "", bg="#0c0f13", fg=self.TEXT, insertbackground=self.TEXT, relief="flat", highlightbackground=self.BORDER, highlightcolor=self.ACCENT, highlightthickness=1, font=("Segoe UI", 10))
            entry.grid(row=row, column=1, sticky="ew", padx=(0, 20), pady=8, ipady=7)
            return entry

        key_var = tk.StringVar(value=self.settings.api_key)
        base_var = tk.StringVar(value=self.settings.base_url)
        model_var = tk.StringVar(value=self.model_var.get() or self.settings.model)
        temp_var = tk.StringVar(value=str(self.settings.temperature))
        top_p_var = tk.StringVar(value=str(self.settings.top_p))
        max_tokens_var = tk.StringVar(value=str(self.settings.max_tokens))
        thinking_var = tk.BooleanVar(value=self.settings.thinking)

        add_label(0, "API key")
        key_entry = add_entry(0, key_var, show="•")
        show_var = tk.BooleanVar(value=False)

        def toggle_key() -> None:
            key_entry.configure(show="" if show_var.get() else "•")

        tk.Checkbutton(dialog, text="Show key", variable=show_var, command=toggle_key, bg=self.PANEL, fg=self.MUTED, selectcolor=self.PANEL_2, activebackground=self.PANEL, activeforeground=self.TEXT).grid(row=1, column=1, sticky="w", padx=(0, 20))

        add_label(2, "Base URL")
        add_entry(2, base_var)
        add_label(3, "Model")
        add_entry(3, model_var)
        add_label(4, "Temperature")
        add_entry(4, temp_var)
        add_label(5, "Top P")
        add_entry(5, top_p_var)
        add_label(6, "Max tokens")
        add_entry(6, max_tokens_var)

        tk.Checkbutton(dialog, text="Enable model thinking", variable=thinking_var, bg=self.PANEL, fg=self.TEXT, selectcolor=self.PANEL_2, activebackground=self.PANEL, activeforeground=self.TEXT).grid(row=7, column=1, sticky="w", padx=(0, 20), pady=8)

        add_label(8, "System prompt")
        system_box = tk.Text(dialog, height=7, wrap="word", bg="#0c0f13", fg=self.TEXT, insertbackground=self.TEXT, relief="flat", highlightbackground=self.BORDER, highlightcolor=self.ACCENT, highlightthickness=1, font=("Segoe UI", 10))
        system_box.grid(row=8, column=1, sticky="nsew", padx=(0, 20), pady=8)
        system_box.insert("1.0", self.settings.system_prompt)
        dialog.rowconfigure(8, weight=1)

        info = tk.Label(dialog, text="Tip: put the real key in a local .env file as APIAPP_API_KEY. Never commit it.", bg=self.PANEL, fg=self.MUTED, wraplength=560, justify="left", font=("Segoe UI", 8))
        info.grid(row=9, column=0, columnspan=2, sticky="w", padx=20, pady=(4, 10))

        buttons = tk.Frame(dialog, bg=self.PANEL)
        buttons.grid(row=10, column=0, columnspan=2, sticky="e", padx=20, pady=(0, 18))

        def save() -> None:
            try:
                temperature = float(temp_var.get())
                top_p = float(top_p_var.get())
                max_tokens = int(max_tokens_var.get())
            except ValueError:
                messagebox.showerror("Invalid settings", "Temperature, Top P, and Max Tokens must be valid numbers.", parent=dialog)
                return
            if not base_var.get().strip().startswith(("http://", "https://")):
                messagebox.showerror("Invalid Base URL", "Base URL must start with http:// or https://", parent=dialog)
                return
            if not model_var.get().strip():
                messagebox.showerror("Invalid model", "Model ID cannot be empty.", parent=dialog)
                return

            self.settings.api_key = key_var.get().strip()
            self.settings.base_url = base_var.get().strip().rstrip("/")
            self.settings.model = model_var.get().strip()
            self.settings.temperature = temperature
            self.settings.top_p = top_p
            self.settings.max_tokens = max_tokens
            self.settings.thinking = bool(thinking_var.get())
            self.settings.system_prompt = system_box.get("1.0", "end-1c").strip()
            self.model_var.set(self.settings.model)
            self._refresh_connection_status()
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", style="Ghost.TButton", command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Save", style="Accent.TButton", command=save).pack(side="left")

    def _on_return(self, event: tk.Event[Any]) -> str | None:
        if event.state & 0x0001:
            return None
        self._send_message()
        return "break"

    def _send_message(self) -> None:
        if self.generating:
            return
        content = self.prompt.get("1.0", "end-1c").strip()
        if not content:
            return
        if not self.settings.api_key:
            self._show_settings_dialog()
            return

        self.prompt.delete("1.0", "end")
        self.messages.append({"role": "user", "content": content})
        self._append_text("You\n", "user_name")
        self._append_text(content + "\n", "body")
        self._append_text("Assistant\n", "assistant_name")
        self._set_generating(True)
        self.cancel_event.clear()

        payload_messages: list[dict[str, str]] = []
        if self.settings.system_prompt:
            payload_messages.append({"role": "system", "content": self.settings.system_prompt})
        payload_messages.extend(self.messages)

        thread = threading.Thread(target=self._request_worker, args=(payload_messages,), daemon=True)
        thread.start()

    def _request_worker(self, messages: list[dict[str, str]]) -> None:
        payload = {
            "model": self.model_var.get().strip() or self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "top_p": self.settings.top_p,
            "max_tokens": self.settings.max_tokens,
            "stream": True,
            "chat_template_kwargs": {"thinking": self.settings.thinking},
        }
        request = urllib.request.Request(
            f"{self.settings.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": "APIApp-Desktop/1.0",
            },
            method="POST",
        )

        assembled: list[str] = []
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                for raw_line in response:
                    if self.cancel_event.is_set():
                        self.worker_queue.put(("stopped", ""))
                        return
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        parsed = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = parsed.get("choices", [{}])[0].get("delta", {}).get("content")
                    if isinstance(delta, str) and delta:
                        assembled.append(delta)
                        self.worker_queue.put(("chunk", delta))
            self.worker_queue.put(("done", "".join(assembled)))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self.worker_queue.put(("error", f"HTTP {exc.code}: {detail}"))
        except urllib.error.URLError as exc:
            self.worker_queue.put(("error", f"Could not reach API: {exc}"))
        except Exception as exc:  # noqa: BLE001
            self.worker_queue.put(("error", f"Request failed: {exc}"))

    def _drain_worker_queue(self) -> None:
        try:
            while True:
                kind, value = self.worker_queue.get_nowait()
                if kind == "chunk":
                    self._append_text(str(value), "body")
                elif kind == "done":
                    text = str(value)
                    if text:
                        self.messages.append({"role": "assistant", "content": text})
                    else:
                        self._append_text("The API returned no text.\n", "muted")
                    self._append_text("\n", "body")
                    self._set_generating(False)
                elif kind == "stopped":
                    self._append_text("\nGeneration stopped.\n", "muted")
                    self._set_generating(False)
                elif kind == "error":
                    self._append_text("\n" + str(value) + "\n", "error")
                    self._set_generating(False)
        except queue.Empty:
            pass
        self.after(80, self._drain_worker_queue)

    def _stop_generation(self) -> None:
        if self.generating:
            self.cancel_event.set()
            self._append_text("\nStopping...\n", "muted")

    def _set_generating(self, running: bool) -> None:
        self.generating = running
        if running:
            self.send_button.state(["disabled"])
            self.stop_button.state(["!disabled"])
            self.connection_label.configure(text="Generating...")
        else:
            self.send_button.state(["!disabled"])
            self.stop_button.state(["disabled"])
            self._refresh_connection_status()
            self.chat_status.configure(text=f"Current chat\n\n{len(self.messages)} messages")

    def _append_text(self, text: str, tag: str) -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", text, tag)
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

    def _replace_transcript(self, text: str) -> None:
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        if text:
            self.transcript.insert("end", text)
        self.transcript.configure(state="disabled")


def main() -> None:
    app = ApiApp()
    app.mainloop()


if __name__ == "__main__":
    main()
