let activeConversationId = null;
let lastAssistantText = "";
let recognition = null;
let speechSynthesisSupported = "speechSynthesis" in window;
let streamController = null;

const messages = document.querySelector("#messages");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const conversationList = document.querySelector("#conversation-list");
const newChat = document.querySelector("#new-chat");
const voiceInputButton = document.querySelector("#voice-input");
const voiceOutputButton = document.querySelector("#voice-output");
const cancelStreamButton = document.querySelector("#cancel-stream");
const themeSelect = document.querySelector("#theme-select");

function applyTheme(theme) {
  const resolvedTheme = theme === "dark" ? "dark" : "light";
  document.body.setAttribute("data-theme", resolvedTheme);
  if (themeSelect) {
    themeSelect.value = resolvedTheme;
  }
  localStorage.setItem("aios-theme", resolvedTheme);
}

const savedTheme = localStorage.getItem("aios-theme");
applyTheme(savedTheme || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));

if (themeSelect) {
  themeSelect.addEventListener("change", (event) => {
    applyTheme(event.target.value);
  });
}

if (window.SpeechRecognition || window.webkitSpeechRecognition) {
  const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognitionCtor();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = "en-US";

  recognition.onresult = (event) => {
    const transcript = Array.from(event.results)
      .map((result) => result[0].transcript)
      .join(" ");
    input.value = transcript;
    input.focus();
    voiceInputButton.classList.remove("active");

    if (transcript.trim()) {
      form.requestSubmit();
    }
  };

  recognition.onerror = () => {
    voiceInputButton.classList.remove("active");
  };
}

voiceInputButton.addEventListener("click", () => {
  if (!recognition) {
    updateMessage(appendMessage("assistant", "Voice input is not supported in this browser."), "");
    return;
  }

  if (voiceInputButton.classList.contains("active")) {
    recognition.stop();
    voiceInputButton.classList.remove("active");
    return;
  }

  voiceInputButton.classList.add("active");
  recognition.start();
});

voiceOutputButton.addEventListener("click", () => {
  if (!speechSynthesisSupported || !lastAssistantText) {
    updateMessage(appendMessage("assistant", "Speech output is not available in this browser."), "");
    return;
  }

  const utterance = new SpeechSynthesisUtterance(lastAssistantText);
  utterance.lang = "en-US";
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!content) return;

  input.value = "";
  input.disabled = true;
  appendMessage("user", content);
  const pending = appendMessage("assistant", "Thinking...");
  streamController = new AbortController();
  cancelStreamButton.hidden = false;

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: activeConversationId, message: content, stream: true }),
      signal: streamController.signal,
    });

    if (!response.ok) {
      const payload = await response.json();
      updateMessage(pending, `Error: ${shortError(payload.error || "Something went wrong.")}`);
      return;
    }

    await readChatStream(response, pending);
    lastAssistantText = pending.textContent || "";
    localStorage.removeItem("aios-active-stream");
    await loadConversations();
  } catch (error) {
    if (error.name === "AbortError") {
      updateMessage(pending, `${lastAssistantText || "Response"}\n\n[Response stopped.]`);
      await recoverInterruptedStream();
    } else {
      updateMessage(pending, `Error: ${shortError(error.message || "Could not reach the local AIOS server.")}`);
      await recoverInterruptedStream();
    }
  } finally {
    input.disabled = false;
    input.focus();
    cancelStreamButton.hidden = true;
    streamController = null;
  }
});

cancelStreamButton.addEventListener("click", () => {
  if (streamController) {
    streamController.abort();
  }
});

newChat.addEventListener("click", async () => {
  const response = await fetch("/api/conversations", { method: "POST" });
  const conversation = await response.json();
  activeConversationId = conversation.id;
  messages.innerHTML = "";
  localStorage.removeItem("aios-active-stream");
  await loadConversations();
});

async function loadConversations() {
  const response = await fetch("/api/conversations");
  const payload = await response.json();
  conversationList.innerHTML = "";

  payload.conversations.forEach((conversation) => {
    const button = document.createElement("button");
    button.className = "secondary";
    button.textContent = conversation.title;
    button.addEventListener("click", () => openConversation(conversation.id));
    conversationList.appendChild(button);
  });
}

async function openConversation(id) {
  const response = await fetch(`/api/conversations/${id}`);
  const conversation = await response.json();
  activeConversationId = id;
  localStorage.removeItem("aios-active-stream");
  messages.innerHTML = "";
  conversation.messages.forEach((message) => appendMessage(message.role, message.content));
}

async function readChatStream(response, pending) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let assistantText = "";
  let provider = "";
  let progressText = "";

  const processChunk = (chunk) => {
    const lines = chunk.split(/\n+/);
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const event = JSON.parse(trimmed);
        if (event.type === "meta") {
          activeConversationId = event.conversation_id;
          provider = event.provider || "";
          localStorage.setItem("aios-active-stream", activeConversationId);
          updateMessage(pending, assistantText || "Thinking...", provider, progressText);
        } else if (event.type === "progress") {
          progressText = event.message || event.stage || "";
          updateMessage(pending, assistantText || "Thinking...", provider, progressText);
        } else if (event.type === "delta") {
          assistantText += event.content || "";
          updateMessage(pending, assistantText, provider, progressText);
        } else if (event.type === "done") {
          progressText = "";
          localStorage.removeItem("aios-active-stream");
          updateMessage(pending, event.message.content || assistantText, provider);
        } else if (event.type === "error") {
          throw new Error(event.error || "Streaming failed.");
        }
      } catch (parseError) {
        if (parseError instanceof SyntaxError) {
          console.error("Invalid stream event", trimmed, parseError);
        } else {
          throw parseError;
        }
      }
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    const lastNewline = buffer.lastIndexOf("\n");
    if (lastNewline >= 0) {
      const completeChunk = buffer.slice(0, lastNewline);
      processChunk(completeChunk);
      buffer = buffer.slice(lastNewline + 1);
    }

    if (done) {
      if (buffer.trim()) {
        processChunk(buffer);
      }
      break;
    }
  }
}

function appendMessage(role, content) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  article.innerHTML = messageHtml(role, content);
  messages.appendChild(article);
  messages.scrollTop = messages.scrollHeight;
  return article;
}

function updateMessage(article, content, provider = "", progress = "") {
  const role = provider ? `assistant via ${provider}` : "assistant";
  article.innerHTML = messageHtml(role, content, progress);
  messages.scrollTop = messages.scrollHeight;
  if (role.startsWith("assistant")) {
    lastAssistantText = content;
  }
}

function messageHtml(role, content, progress = "") {
  const progressHtml = progress ? `<div class="stream-progress">${escapeHtml(progress)}</div>` : "";
  return `<strong class="role">${escapeHtml(role)}</strong><div class="message-content">${renderMarkdown(content)}</div>${progressHtml}`;
}

function renderMarkdown(value) {
  const blocks = [];
  let escaped = escapeHtml(value || "").replace(/```([\s\S]*?)```/g, (_, code) => {
    const token = `@@CODE${blocks.length}@@`;
    blocks.push(`<pre><code>${code.trim()}</code></pre>`);
    return token;
  });

  escaped = escaped
    .replace(/^### (.*)$/gm, "<h3>$1</h3>")
    .replace(/^## (.*)$/gm, "<h2>$1</h2>")
    .replace(/^# (.*)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.*?)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
    .replace(/^- (.*)$/gm, "<li>$1</li>")
    .replace(/\n/g, "<br>");

  escaped = escaped.replace(/(<li>.*?<\/li>(?:<br><li>.*?<\/li>)*)/g, (match) => {
    return `<ul>${match.replace(/<br>/g, "")}</ul>`;
  });

  blocks.forEach((html, index) => {
    escaped = escaped.replace(`@@CODE${index}@@`, html);
  });
  return escaped;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
    return map[char];
  });
}

function shortError(value) {
  return value.length > 700 ? `${value.slice(0, 700)}...` : value;
}

async function recoverInterruptedStream() {
  const recoveryId = localStorage.getItem("aios-active-stream") || activeConversationId;
  if (!recoveryId) return;

  localStorage.removeItem("aios-active-stream");
  try {
    await openConversation(recoveryId);
    await loadConversations();
  } catch (error) {
    console.error("Could not recover interrupted stream", error);
  }
}

async function boot() {
  await loadConversations();
  const recoveryId = localStorage.getItem("aios-active-stream");
  if (recoveryId) {
    await recoverInterruptedStream();
  }
}

boot();
