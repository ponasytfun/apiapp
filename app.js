const $ = (id) => document.getElementById(id);

const els = {
  sidebar: $("sidebar"), sidebarToggle: $("sidebarToggle"), chatList: $("chatList"),
  newChatButton: $("newChatButton"), settingsButton: $("settingsButton"), clearChatButton: $("clearChatButton"),
  chatTitle: $("chatTitle"), connectionState: $("connectionState"), modelSelect: $("modelSelect"),
  messages: $("messages"), emptyState: $("emptyState"), promptInput: $("promptInput"),
  sendButton: $("sendButton"), stopButton: $("stopButton"), setupModal: $("setupModal"),
  apiKeyInput: $("apiKeyInput"), baseUrlInput: $("baseUrlInput"), modelInput: $("modelInput"),
  rememberKeyInput: $("rememberKeyInput"), saveSetupButton: $("saveSetupButton"), setupError: $("setupError"),
  toggleKeyButton: $("toggleKeyButton"), settingsModal: $("settingsModal"), closeSettingsButton: $("closeSettingsButton"),
  settingsApiKey: $("settingsApiKey"), settingsBaseUrl: $("settingsBaseUrl"), settingsModel: $("settingsModel"),
  temperatureInput: $("temperatureInput"), temperatureValue: $("temperatureValue"), maxTokensInput: $("maxTokensInput"),
  systemPromptInput: $("systemPromptInput"), saveSettingsButton: $("saveSettingsButton"), forgetKeyButton: $("forgetKeyButton"),
  toast: $("toast")
};

const STORAGE_KEY = "apiapp-state-v1";
const KEY_STORAGE = "apiapp-secret-v1";
let abortController = null;
let state = loadState();

function defaultSettings() {
  return {
    baseUrl: "https://integrate.api.nvidia.com/v1",
    model: "deepseek-ai/deepseek-v4-pro",
    temperature: 1,
    maxTokens: 16384,
    systemPrompt: "You are a precise, helpful coding assistant. Prefer practical solutions, explain tradeoffs clearly, and never claim to have run tools you did not run."
  };
}

function loadState() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (parsed && Array.isArray(parsed.chats)) {
      return {
        settings: { ...defaultSettings(), ...(parsed.settings || {}) },
        chats: parsed.chats,
        activeChatId: parsed.activeChatId || parsed.chats[0]?.id || null,
        apiKey: sessionStorage.getItem(KEY_STORAGE) || localStorage.getItem(KEY_STORAGE) || "",
        hasServerApiKey: false,
        apiKeySource: null
      };
    }
  } catch (_) {}
  const chat = createChatObject();
  return {
    settings: defaultSettings(),
    chats: [chat],
    activeChatId: chat.id,
    apiKey: sessionStorage.getItem(KEY_STORAGE) || localStorage.getItem(KEY_STORAGE) || "",
    hasServerApiKey: false,
    apiKeySource: null
  };
}

async function loadServerConfig() {
  try {
    const response = await fetch("/api/config", { cache: "no-store" });
    if (!response.ok) return;
    const config = await response.json();
    state.hasServerApiKey = Boolean(config.hasServerApiKey);
    state.apiKeySource = config.apiKeySource || null;

    const currentDefaults = defaultSettings();
    if (!state.settings.baseUrl || state.settings.baseUrl === "https://api.openai.com/v1") state.settings.baseUrl = config.baseUrl || currentDefaults.baseUrl;
    if (!state.settings.model || state.settings.model === "gpt-4.1-mini") state.settings.model = config.model || currentDefaults.model;
    if (state.settings.temperature === undefined || state.settings.temperature === 0.7) state.settings.temperature = config.temperature ?? currentDefaults.temperature;
    if (!state.settings.maxTokens || state.settings.maxTokens === 4096) state.settings.maxTokens = config.maxTokens || currentDefaults.maxTokens;
    saveState();
  } catch (_) {
    state.hasServerApiKey = false;
    state.apiKeySource = null;
  }
}

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ settings: state.settings, chats: state.chats, activeChatId: state.activeChatId }));
}

function createChatObject() {
  return { id: crypto.randomUUID(), title: "New chat", messages: [], createdAt: Date.now(), updatedAt: Date.now() };
}

function activeChat() {
  return state.chats.find(c => c.id === state.activeChatId) || null;
}

function hasAnyApiKey() {
  return Boolean(state.apiKey || state.hasServerApiKey);
}

function persistKey(key, remember) {
  sessionStorage.removeItem(KEY_STORAGE);
  localStorage.removeItem(KEY_STORAGE);
  if (!key) return;
  (remember ? localStorage : sessionStorage).setItem(KEY_STORAGE, key);
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => els.toast.classList.add("hidden"), 2200);
}

function setConnectedState() {
  const configured = Boolean(hasAnyApiKey() && state.settings.baseUrl && state.settings.model);
  const source = state.apiKey ? "browser key" : state.hasServerApiKey ? `${state.apiKeySource || ".env"}` : "no key";
  els.connectionState.textContent = configured ? `${state.settings.baseUrl.replace(/^https?:\/\//, "")} · ${source}` : "Not configured";
  els.connectionState.classList.toggle("live", configured);
}

function ensureModelOption(model) {
  const models = [...new Set([
    model,
    state.settings.model,
    "deepseek-ai/deepseek-v4-pro",
    "deepseek-ai/deepseek-v4-flash",
    "openai/gpt-oss-120b",
    "qwen/qwen3.5-122b-a10b",
    "gpt-4.1-mini",
    "gpt-4.1",
    "gpt-4o-mini",
    "gpt-4o"
  ].filter(Boolean))];
  els.modelSelect.innerHTML = "";
  for (const value of models) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    els.modelSelect.appendChild(option);
  }
  els.modelSelect.value = model || state.settings.model;
}

function renderSidebar() {
  els.chatList.innerHTML = "";
  const chats = [...state.chats].sort((a, b) => b.updatedAt - a.updatedAt);
  for (const chat of chats) {
    const row = document.createElement("div");
    row.className = `chat-item${chat.id === state.activeChatId ? " active" : ""}`;
    row.innerHTML = `<span class="chat-item-title"></span><button class="chat-item-delete" title="Delete chat">✕</button>`;
    row.querySelector(".chat-item-title").textContent = chat.title || "Untitled";
    row.addEventListener("click", (event) => {
      if (event.target.closest(".chat-item-delete")) return;
      state.activeChatId = chat.id;
      saveState();
      renderAll();
      els.sidebar.classList.remove("open");
    });
    row.querySelector(".chat-item-delete").addEventListener("click", () => deleteChat(chat.id));
    els.chatList.appendChild(row);
  }
}

function deleteChat(id) {
  state.chats = state.chats.filter(c => c.id !== id);
  if (!state.chats.length) state.chats.push(createChatObject());
  if (!state.chats.some(c => c.id === state.activeChatId)) state.activeChatId = state.chats[0].id;
  saveState();
  renderAll();
}

function newChat() {
  const chat = createChatObject();
  state.chats.push(chat);
  state.activeChatId = chat.id;
  saveState();
  renderAll();
  els.promptInput.focus();
}

function escapeHtml(value) {
  return value.replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
}

function renderMarkdown(text) {
  const parts = [];
  let cursor = 0;
  const fence = /```([^\n]*)\n([\s\S]*?)```/g;
  let match;
  while ((match = fence.exec(text))) {
    parts.push(renderInline(text.slice(cursor, match.index)));
    const lang = escapeHtml((match[1] || "text").trim() || "text");
    const code = escapeHtml(match[2]);
    parts.push(`<div class="code-block"><div class="code-header"><span>${lang}</span><button class="message-action copy-code">Copy</button></div><pre><code>${code}</code></pre></div>`);
    cursor = match.index + match[0].length;
  }
  parts.push(renderInline(text.slice(cursor)));
  return parts.join("");
}

function renderInline(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");
  html = html.replace(/^[-*] (.+)$/gm, "• $1");
  html = html.replace(/\n/g, "<br>");
  return html;
}

function renderMessages() {
  const chat = activeChat();
  els.messages.innerHTML = "";
  if (!chat || !chat.messages.length) {
    els.messages.appendChild(els.emptyState);
    els.emptyState.classList.remove("hidden");
    return;
  }

  for (const [index, message] of chat.messages.entries()) {
    const article = document.createElement("article");
    article.className = `message ${message.role}`;
    article.innerHTML = `
      <div class="message-meta">
        <span class="message-role">${message.role === "user" ? "You" : "Assistant"}</span>
        <span class="message-actions"><button class="message-action copy-message">Copy</button>${message.role === "assistant" ? '<button class="message-action regenerate-message">Regenerate</button>' : ""}</span>
      </div>
      <div class="message-body${message.streaming ? " streaming-cursor" : ""}"></div>`;
    const body = article.querySelector(".message-body");
    if (message.error) body.innerHTML = `<div class="error-card">${escapeHtml(message.content)}</div>`;
    else body.innerHTML = renderMarkdown(message.content || "");
    article.querySelector(".copy-message").addEventListener("click", () => navigator.clipboard.writeText(message.content || "").then(() => showToast("Copied")));
    article.querySelectorAll(".copy-code").forEach(button => button.addEventListener("click", () => {
      const code = button.closest(".code-block").querySelector("code").textContent;
      navigator.clipboard.writeText(code).then(() => showToast("Code copied"));
    }));
    const regen = article.querySelector(".regenerate-message");
    if (regen) regen.addEventListener("click", () => regenerate(index));
    els.messages.appendChild(article);
  }
  requestAnimationFrame(() => { els.messages.scrollTop = els.messages.scrollHeight; });
}

function renderAll() {
  const chat = activeChat();
  renderSidebar();
  renderMessages();
  els.chatTitle.value = chat?.title || "New chat";
  ensureModelOption(state.settings.model);
  setConnectedState();
}

function autoGrow() {
  els.promptInput.style.height = "auto";
  els.promptInput.style.height = `${Math.min(220, els.promptInput.scrollHeight)}px`;
}

function buildApiMessages(chat) {
  const messages = [];
  if (state.settings.systemPrompt.trim()) messages.push({ role: "system", content: state.settings.systemPrompt.trim() });
  for (const msg of chat.messages) {
    if (!msg.error && !msg.streaming && ["user", "assistant"].includes(msg.role)) messages.push({ role: msg.role, content: msg.content });
  }
  return messages;
}

async function sendCurrentPrompt() {
  const content = els.promptInput.value.trim();
  if (!content || abortController) return;
  if (!hasAnyApiKey()) {
    openSetup();
    return;
  }
  const chat = activeChat();
  chat.messages.push({ role: "user", content, createdAt: Date.now() });
  if (chat.title === "New chat") chat.title = content.replace(/\s+/g, " ").slice(0, 46) || "New chat";
  chat.updatedAt = Date.now();
  els.promptInput.value = "";
  autoGrow();
  saveState();
  renderAll();
  await requestAssistant(chat);
}

async function requestAssistant(chat) {
  const assistant = { role: "assistant", content: "", createdAt: Date.now(), streaming: true };
  chat.messages.push(assistant);
  chat.updatedAt = Date.now();
  abortController = new AbortController();
  updateGenerationUi(true);
  renderAll();

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: abortController.signal,
      body: JSON.stringify({
        apiKey: state.apiKey || "",
        baseUrl: state.settings.baseUrl,
        model: els.modelSelect.value || state.settings.model,
        temperature: Number(state.settings.temperature),
        max_tokens: Number(state.settings.maxTokens),
        messages: buildApiMessages(chat).filter((_, i, arr) => !(i === arr.length - 1 && arr[i].role === "assistant"))
      })
    });

    if (!response.ok) {
      let detail = await response.text();
      try {
        const parsed = JSON.parse(detail);
        detail = parsed.detail?.error?.message || parsed.detail?.message || parsed.error || detail;
      } catch (_) {}
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const data = line.slice(5).trim();
        if (!data || data === "[DONE]") continue;
        try {
          const parsed = JSON.parse(data);
          const delta = parsed.choices?.[0]?.delta?.content;
          if (typeof delta === "string") assistant.content += delta;
        } catch (_) {}
      }
      renderMessages();
    }
    if (!assistant.content) assistant.content = "The API returned no text content.";
  } catch (error) {
    if (error.name === "AbortError") {
      if (!assistant.content) assistant.content = "Generation stopped.";
    } else {
      assistant.error = true;
      assistant.content = `Request failed: ${error.message}`;
    }
  } finally {
    assistant.streaming = false;
    chat.updatedAt = Date.now();
    abortController = null;
    updateGenerationUi(false);
    saveState();
    renderAll();
  }
}

async function regenerate(index) {
  if (abortController) return;
  const chat = activeChat();
  if (!chat) return;
  const target = chat.messages[index];
  if (!target || target.role !== "assistant") return;
  chat.messages = chat.messages.slice(0, index);
  saveState();
  renderAll();
  await requestAssistant(chat);
}

function updateGenerationUi(running) {
  els.sendButton.disabled = running;
  els.stopButton.classList.toggle("hidden", !running);
}

function openSetup() {
  els.apiKeyInput.value = state.apiKey || "";
  els.apiKeyInput.placeholder = state.hasServerApiKey ? `Using ${state.apiKeySource || ".env"}; leave blank to keep it` : "nvapi-...";
  els.baseUrlInput.value = state.settings.baseUrl;
  els.modelInput.value = state.settings.model;
  els.rememberKeyInput.checked = Boolean(localStorage.getItem(KEY_STORAGE));
  els.setupError.classList.add("hidden");
  els.setupModal.classList.remove("hidden");
  setTimeout(() => els.apiKeyInput.focus(), 30);
}

function saveSetup() {
  const key = els.apiKeyInput.value.trim();
  const baseUrl = els.baseUrlInput.value.trim().replace(/\/$/, "");
  const model = els.modelInput.value.trim();
  if ((!key && !state.hasServerApiKey) || !baseUrl || !model) {
    els.setupError.textContent = "API key, Base URL, and Model are required. If you use .env, restart the app after creating it.";
    els.setupError.classList.remove("hidden");
    return;
  }
  state.apiKey = key;
  state.settings.baseUrl = baseUrl;
  state.settings.model = model;
  persistKey(key, els.rememberKeyInput.checked);
  saveState();
  els.setupModal.classList.add("hidden");
  renderAll();
  showToast(key ? "API configured" : "Using .env API key");
}

function openSettings() {
  els.settingsApiKey.value = state.apiKey;
  els.settingsApiKey.placeholder = state.hasServerApiKey ? `Using ${state.apiKeySource || ".env"}; optional browser override` : "Optional browser key";
  els.settingsBaseUrl.value = state.settings.baseUrl;
  els.settingsModel.value = state.settings.model;
  els.temperatureInput.value = state.settings.temperature;
  els.temperatureValue.textContent = state.settings.temperature;
  els.maxTokensInput.value = state.settings.maxTokens;
  els.systemPromptInput.value = state.settings.systemPrompt;
  els.settingsModal.classList.remove("hidden");
}

function saveSettings() {
  state.apiKey = els.settingsApiKey.value.trim();
  state.settings.baseUrl = els.settingsBaseUrl.value.trim().replace(/\/$/, "");
  state.settings.model = els.settingsModel.value.trim();
  state.settings.temperature = Number(els.temperatureInput.value);
  state.settings.maxTokens = Number(els.maxTokensInput.value) || 16384;
  state.settings.systemPrompt = els.systemPromptInput.value;
  const remember = Boolean(localStorage.getItem(KEY_STORAGE));
  persistKey(state.apiKey, remember);
  saveState();
  els.settingsModal.classList.add("hidden");
  renderAll();
  showToast("Settings saved");
}

els.newChatButton.addEventListener("click", newChat);
els.settingsButton.addEventListener("click", openSettings);
els.closeSettingsButton.addEventListener("click", () => els.settingsModal.classList.add("hidden"));
els.saveSettingsButton.addEventListener("click", saveSettings);
els.saveSetupButton.addEventListener("click", saveSetup);
els.toggleKeyButton.addEventListener("click", () => {
  const showing = els.apiKeyInput.type === "text";
  els.apiKeyInput.type = showing ? "password" : "text";
  els.toggleKeyButton.textContent = showing ? "Show" : "Hide";
});
els.temperatureInput.addEventListener("input", () => els.temperatureValue.textContent = els.temperatureInput.value);
els.forgetKeyButton.addEventListener("click", () => {
  localStorage.removeItem(KEY_STORAGE);
  sessionStorage.removeItem(KEY_STORAGE);
  state.apiKey = "";
  els.settingsApiKey.value = "";
  showToast(state.hasServerApiKey ? "Browser key forgotten; .env key still active" : "Saved key forgotten");
});
els.sendButton.addEventListener("click", sendCurrentPrompt);
els.stopButton.addEventListener("click", () => abortController?.abort());
els.promptInput.addEventListener("input", autoGrow);
els.promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendCurrentPrompt();
  }
});
els.chatTitle.addEventListener("change", () => {
  const chat = activeChat();
  if (!chat) return;
  chat.title = els.chatTitle.value.trim() || "Untitled";
  chat.updatedAt = Date.now();
  saveState();
  renderSidebar();
});
els.modelSelect.addEventListener("change", () => {
  state.settings.model = els.modelSelect.value;
  saveState();
  setConnectedState();
});
els.clearChatButton.addEventListener("click", () => {
  const chat = activeChat();
  if (!chat) return;
  chat.messages = [];
  chat.updatedAt = Date.now();
  saveState();
  renderAll();
});
els.sidebarToggle.addEventListener("click", () => els.sidebar.classList.toggle("open"));
document.querySelectorAll(".suggestion").forEach(button => button.addEventListener("click", () => {
  els.promptInput.value = button.textContent;
  autoGrow();
  els.promptInput.focus();
}));

async function init() {
  await loadServerConfig();
  renderAll();
  autoGrow();
  if (!hasAnyApiKey()) openSetup();
  else els.setupModal.classList.add("hidden");
}

init();
