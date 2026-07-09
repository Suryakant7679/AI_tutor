let activeConversationId = null;
let lastAssistantText = "";
let recognition = null;
let speechSynthesisSupported = "speechSynthesis" in window;
let streamController = null;
let selectedFiles = [];

const messages = document.querySelector("#messages");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const conversationList = document.querySelector("#conversation-list");
const newChat = document.querySelector("#new-chat");
const voiceInputButton = document.querySelector("#voice-input");
const voiceOutputButton = document.querySelector("#voice-output");
const cancelStreamButton = document.querySelector("#cancel-stream");
const themeSelect = document.querySelector("#theme-select");
const fileInput = document.querySelector("#file-input");
const dropZone = document.querySelector("#drop-zone");
const attachmentCount = document.querySelector("#attachment-count");
const artifactList = document.querySelector("#artifact-list");
const refreshArtifacts = document.querySelector("#refresh-artifacts");
const providerMode = document.querySelector("#provider-mode");
const compactMode = document.querySelector("#compact-mode");
const profileName = document.querySelector("#profile-name");
const profileRole = document.querySelector("#profile-role");
const workspaceName = document.querySelector("#workspace-name");
const workspaceFocus = document.querySelector("#workspace-focus");
const notificationList = document.querySelector("#notification-list");
const mobileTools = document.querySelector("#mobile-tools");
const toolsToggle = document.querySelector("#tools-toggle");
const closeTools = document.querySelector("#close-tools");
const sidebarToggle = document.querySelector("#sidebar-toggle");
const emptyState = document.querySelector("#empty-state");

function applyTheme(theme) {
  const resolvedTheme = theme === "dark" ? "dark" : "light";
  document.body.setAttribute("data-theme", resolvedTheme);
  if (themeSelect) {
    themeSelect.value = resolvedTheme;
  }
  localStorage.setItem("aios-theme", resolvedTheme);
}

const savedTheme = localStorage.getItem("aios-theme");
applyTheme(savedTheme || "dark");

if (themeSelect) {
  themeSelect.addEventListener("change", (event) => {
    applyTheme(event.target.value);
  });
}

loadPreferences();

if (fileInput) {
  fileInput.addEventListener("change", () => {
    addSelectedFiles(Array.from(fileInput.files || []));
    fileInput.value = "";
  });
}

if (dropZone) {
  ["dragenter", "dragover"].forEach((name) => {
    dropZone.addEventListener(name, (event) => {
      event.preventDefault();
      dropZone.classList.add("dragging");
    });
  });

  ["dragleave", "drop"].forEach((name) => {
    dropZone.addEventListener(name, () => dropZone.classList.remove("dragging"));
  });

  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    addSelectedFiles(Array.from(event.dataTransfer.files || []));
  });
}

refreshArtifacts.addEventListener("click", loadArtifacts);
mobileTools.addEventListener("click", () => document.body.classList.toggle("tools-open"));
toolsToggle.addEventListener("click", () => document.body.classList.toggle("tools-open"));
closeTools.addEventListener("click", () => document.body.classList.remove("tools-open"));
sidebarToggle.addEventListener("click", () => document.body.classList.toggle("sidebar-open"));

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
});

[providerMode, compactMode, profileName, profileRole, workspaceName, workspaceFocus].forEach((control) => {
  control.addEventListener("change", savePreferences);
  control.addEventListener("input", savePreferences);
});

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
  let content = input.value.trim();
  if (!content && selectedFiles.length) {
    content = "Please review the attached files.";
  }
  if (!content) return;

  input.value = "";
  input.style.height = "auto";
  input.disabled = true;
  setComposerBusy(true);
  const attachments = selectedFiles.slice();
  selectedFiles = [];
  updateAttachmentCount();
  appendMessage("user", attachments.length ? `${content}\n\n${fileSummary(attachments)}` : content);
  const pending = appendMessage("assistant", "");
  setMessageProcessing(pending, "Preparing request");
  streamController = new AbortController();
  cancelStreamButton.hidden = false;

  try {
    const uploadedArtifacts = attachments.length ? await uploadFiles(attachments) : [];
    if (uploadedArtifacts.length) {
      notify("Uploads ready", `${uploadedArtifacts.length} artifact(s) attached to this message.`);
      await loadArtifacts();
    }
    const enrichedContent = buildChatContent(content, uploadedArtifacts);
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: activeConversationId, message: enrichedContent, stream: true }),
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
    notify("Reply complete", "The assistant response finished streaming.");
  } catch (error) {
    if (error.name === "AbortError") {
      updateMessage(pending, `${lastAssistantText || "Response"}\n\n[Response stopped.]`);
      await recoverInterruptedStream();
      notify("Stream stopped", "The current response was cancelled.");
    } else {
      updateMessage(pending, `Error: ${shortError(error.message || "Could not reach the local AIOS server.")}`);
      await recoverInterruptedStream();
      notify("Chat error", shortError(error.message || "Could not reach the local AIOS server."));
    }
  } finally {
    input.disabled = false;
    setComposerBusy(false);
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
  activeConversationId = null;
  messages.innerHTML = "";
  selectedFiles = [];
  updateAttachmentCount();
  updateEmptyState();
  localStorage.removeItem("aios-active-stream");
  input.value = "";
  input.style.height = "auto";
  input.focus();
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
  updateEmptyState();
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
          setMessageProcessing(pending, progressText || "Preparing stream", provider);
        } else if (event.type === "progress") {
          progressText = event.message || event.stage || "";
          if (assistantText) {
            updateMessage(pending, assistantText, provider, progressText, true);
          } else {
            setMessageProcessing(pending, progressText, provider);
          }
        } else if (event.type === "delta") {
          assistantText += event.content || "";
          updateMessage(pending, assistantText, provider, progressText, true);
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
  updateEmptyState();
  return article;
}

function updateMessage(article, content, provider = "", progress = "", isStreaming = false) {
  const role = provider ? `assistant via ${provider}` : "assistant";
  article.classList.toggle("streaming", isStreaming);
  article.classList.remove("processing");
  article.innerHTML = messageHtml(role, content, progress, isStreaming);
  messages.scrollTop = messages.scrollHeight;
  if (role.startsWith("assistant")) {
    lastAssistantText = content;
  }
  updateEmptyState();
}

function setMessageProcessing(article, status, provider = "") {
  const role = provider ? `assistant via ${provider}` : "assistant";
  article.classList.add("processing");
  article.classList.remove("streaming");
  article.innerHTML = processingHtml(role, status);
  messages.scrollTop = messages.scrollHeight;
  updateEmptyState();
}

function updateEmptyState() {
  emptyState.hidden = Boolean(messages.children.length);
}

function messageHtml(role, content, progress = "", isStreaming = false) {
  const cursor = isStreaming ? '<span class="stream-cursor"></span>' : "";
  const progressHtml = progress ? `<div class="stream-progress">${escapeHtml(progress)}</div>` : "";
  return `<strong class="role">${escapeHtml(role)}</strong><div class="message-content">${renderMarkdown(content)}${cursor}</div>${progressHtml}`;
}

function processingHtml(role, status) {
  const progressHtml = `<div class="stream-progress">${escapeHtml(status || "Processing")}</div>`;
  return `<strong class="role">${escapeHtml(role)}</strong><div class="message-content"><span class="typing-dots"><span></span><span></span><span></span></span></div>${progressHtml}`;
}

function renderMarkdown(value) {
  const blocks = [];
  let escaped = escapeHtml(value || "").replace(/```(\w+)?\n?([\s\S]*?)```/g, (_, language, code) => {
    const token = `@@CODE${blocks.length}@@`;
    blocks.push(`<pre><code data-language="${escapeHtml(language || "text")}">${highlightCode(code.trim(), language || "")}</code></pre>`);
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

function highlightCode(code, language) {
  let highlighted = escapeHtml(code);
  highlighted = highlighted.replace(/(&quot;.*?&quot;|&#039;.*?&#039;)/g, '<span class="syntax-string">$1</span>');
  const keywordSets = {
    py: "def|class|return|import|from|if|elif|else|for|while|try|except|with|as|True|False|None",
    python: "def|class|return|import|from|if|elif|else|for|while|try|except|with|as|True|False|None",
    js: "function|const|let|var|return|import|export|if|else|for|while|try|catch|await|async|new",
    javascript: "function|const|let|var|return|import|export|if|else|for|while|try|catch|await|async|new",
    json: "true|false|null",
  };
  const pattern = keywordSets[String(language).toLowerCase()];
  if (pattern) {
    highlighted = highlighted.replace(new RegExp(`\\b(${pattern})\\b`, "g"), '<span class="syntax-keyword">$1</span>');
  }
  return highlighted;
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

function addSelectedFiles(files) {
  selectedFiles = [...selectedFiles, ...files].slice(0, 8);
  updateAttachmentCount();
  if (files.length) {
    notify("Files selected", `${files.length} file(s) ready to attach.`);
  }
}

function updateAttachmentCount() {
  attachmentCount.textContent = selectedFiles.length ? `${selectedFiles.length} file${selectedFiles.length === 1 ? "" : "s"}` : "";
}

function fileSummary(files) {
  return files.map((file) => `- ${file.name} (${formatBytes(file.size)})`).join("\n");
}

async function uploadFiles(files) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  const response = await fetch("/api/uploads", { method: "POST", body: formData });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Upload failed.");
  }
  return payload.artifacts || [];
}

function buildChatContent(content, artifacts) {
  const profile = loadJson("aios-profile", {});
  const workspace = loadJson("aios-workspace", {});
  const parts = [content];
  if (profile.name || profile.role) {
    parts.push(`User profile: ${[profile.name, profile.role].filter(Boolean).join(" - ")}`);
  }
  if (workspace.name || workspace.focus) {
    parts.push(`Workspace: ${[workspace.name, workspace.focus].filter(Boolean).join(" - ")}`);
  }
  if (artifacts.length) {
    parts.push(
      "Attached artifacts:\n" +
        artifacts
          .map((item) => {
            const preview = item.preview ? `\nPreview:\n${item.preview.slice(0, 1200)}` : "";
            return `- ${item.filename} (${item.category}, ${formatBytes(item.size)})${preview}`;
          })
          .join("\n")
    );
  }
  return parts.join("\n\n");
}

async function loadArtifacts() {
  const response = await fetch("/api/uploads");
  const payload = await response.json();
  renderArtifacts(payload.artifacts || []);
}

function renderArtifacts(artifacts) {
  artifactList.innerHTML = "";
  if (!artifacts.length) {
    artifactList.innerHTML = '<div class="artifact"><small>No artifacts yet.</small></div>';
    return;
  }
  artifacts.slice(0, 12).forEach((item) => {
    const card = document.createElement("article");
    card.className = "artifact";
    const url = `/api/uploads/${item.id}/content`;
    const preview =
      item.category === "image"
        ? `<img src="${url}" alt="${escapeHtml(item.filename)}" />`
        : item.category === "audio"
          ? `<audio src="${url}" controls></audio>`
          : item.category === "pdf"
            ? `<a href="${url}" target="_blank" rel="noreferrer">Open PDF</a>`
            : item.preview
              ? `<small>${escapeHtml(item.preview.slice(0, 160))}</small>`
              : "";
    card.innerHTML = `<strong>${escapeHtml(item.filename)}</strong><small>${item.category} - ${formatBytes(item.size)}</small>${preview}`;
    artifactList.appendChild(card);
  });
}

function loadPreferences() {
  const settings = loadJson("aios-settings", {});
  const profile = loadJson("aios-profile", {});
  const workspace = loadJson("aios-workspace", {});
  providerMode.value = settings.providerMode || "auto";
  compactMode.checked = Boolean(settings.compactMode);
  profileName.value = profile.name || "";
  profileRole.value = profile.role || "";
  workspaceName.value = workspace.name || "";
  workspaceFocus.value = workspace.focus || "";
  document.body.classList.toggle("compact", compactMode.checked);
}

function savePreferences() {
  localStorage.setItem("aios-settings", JSON.stringify({ providerMode: providerMode.value, compactMode: compactMode.checked }));
  localStorage.setItem("aios-profile", JSON.stringify({ name: profileName.value.trim(), role: profileRole.value.trim() }));
  localStorage.setItem("aios-workspace", JSON.stringify({ name: workspaceName.value.trim(), focus: workspaceFocus.value.trim() }));
  document.body.classList.toggle("compact", compactMode.checked);
}

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || "null") || fallback;
  } catch {
    return fallback;
  }
}

function notify(title, detail) {
  const notices = loadJson("aios-notifications", []);
  notices.unshift({ title, detail, createdAt: new Date().toLocaleTimeString() });
  localStorage.setItem("aios-notifications", JSON.stringify(notices.slice(0, 8)));
  renderNotifications();
}

function renderNotifications() {
  const notices = loadJson("aios-notifications", []);
  notificationList.innerHTML = notices.length
    ? notices.map((item) => `<div class="notice"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.createdAt)} - ${escapeHtml(item.detail)}</small></div>`).join("")
    : '<div class="notice"><small>No notifications yet.</small></div>';
}

function setComposerBusy(isBusy) {
  if (fileInput) {
    fileInput.disabled = isBusy;
  }
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
  await loadArtifacts();
  renderNotifications();
  updateEmptyState();
  const recoveryId = localStorage.getItem("aios-active-stream");
  if (recoveryId) {
    await recoverInterruptedStream();
  }
}

boot();
