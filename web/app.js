// tether chat client. One WebSocket, multiple sessions, images, voice notes,
// live render, auto-reconnect. tether runs no LLM: this just sends and renders.

const proto = location.protocol === "https:" ? "wss" : "ws";

const messagesEl = document.getElementById("messages");
const form = document.getElementById("composer");
const input = document.getElementById("command");
const sessionListEl = document.getElementById("session-list");
const sessionTitleEl = document.getElementById("session-title");
const searchEl = document.getElementById("session-search");
const statusDot = document.getElementById("status-dot");
const fileInput = document.getElementById("file-input");
const attachBtn = document.getElementById("attach-btn");
const micBtn = document.getElementById("mic-btn");
const stopBtn = document.getElementById("stop-btn");
const dirPicker = document.getElementById("dir-picker");
const dirInput = document.getElementById("dir-input");
const dirListEl = document.getElementById("dir-list");
const dirInsert = document.getElementById("dir-insert");
const dirClose = document.getElementById("dir-close");
const cmdPicker = document.getElementById("cmd-picker");
const cmdInput = document.getElementById("cmd-input");
const cmdList = document.getElementById("cmd-list");
const cmdInsert = document.getElementById("cmd-insert");
const cmdClose = document.getElementById("cmd-close");
const widgetsEl = document.getElementById("widgets");
const widgetAdd = document.getElementById("widget-add");
const wbCmdList = document.getElementById("wb-cmd-list");
const wbPanel = document.getElementById("widget-builder");
const wbName = document.getElementById("wb-name");
const wbCmd = document.getElementById("wb-cmd");
const wbRead = document.getElementById("wb-read");
const wbFields = document.getElementById("wb-fields");
const wbFull = document.getElementById("wb-full");
const wbClose = document.getElementById("wb-close");
const wbSave = document.getElementById("wb-save");
const wrPanel = document.getElementById("widget-run");
const wrTitle = document.getElementById("wr-title");
const wrFields = document.getElementById("wr-fields");
const wrPreview = document.getElementById("wr-preview");
const wrClose = document.getElementById("wr-close");
const wrRun = document.getElementById("wr-run");
const modalScrim = document.getElementById("modal-scrim");
const newBtn = document.getElementById("new-session");
const menuBtn = document.getElementById("menu-btn");
const sidebar = document.getElementById("sidebar");
const scrim = document.getElementById("scrim");

// Attach a listener only if the element exists. If a stale/cached page is missing
// a newer control, that one listener is skipped instead of throwing and aborting
// the rest of this script (which previously broke unrelated features like /d, /c).
function on(el, type, handler, opts) {
  if (el) el.addEventListener(type, handler, opts);
}

let ws = null;
let sessionId = null;
let sessions = [];
let pendingAttachments = []; // {id, kind, mime} uploaded, not yet sent
let token = localStorage.getItem("tether_token") || "";
let currentTaskId = null;
let dirCurrent = null;
let dirBase = "";
let dirEntries = [];
let allCommands = null;
let widgets = [];
let voiceMode = "browser";
const userTicks = {}; // task_id -> tick element on the user's message bubble

// ---------- rendering ----------
function appendInline(parent, text) {
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(https?:\/\/[^\s]+)/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) {
      parent.appendChild(document.createTextNode(text.slice(last, m.index)));
    }
    const tok = m[0];
    if (tok.startsWith("`")) {
      const c = document.createElement("code");
      c.textContent = tok.slice(1, -1);
      parent.appendChild(c);
    } else if (tok.startsWith("**")) {
      const b = document.createElement("strong");
      b.textContent = tok.slice(2, -2);
      parent.appendChild(b);
    } else {
      const a = document.createElement("a");
      a.href = tok; // http(s) only per regex, safe
      a.textContent = tok;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      parent.appendChild(a);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) {
    parent.appendChild(document.createTextNode(text.slice(last)));
  }
}

function renderMarkdown(text) {
  const frag = document.createDocumentFragment();
  const blocks = text.split("```");
  blocks.forEach((blk, i) => {
    if (i % 2 === 1) {
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = blk.replace(/^\n/, "");
      pre.appendChild(code);
      frag.appendChild(pre);
    } else if (blk) {
      const lines = blk.split("\n");
      lines.forEach((line, j) => {
        appendInline(frag, line);
        if (j < lines.length - 1) frag.appendChild(document.createElement("br"));
      });
    }
  });
  return frag;
}

function addMessage(role, content, attachments, taskId) {
  const el = document.createElement("div");
  el.className = `msg msg-${role}`;
  for (const a of attachments || []) {
    if (a.kind === "image") {
      const img = document.createElement("img");
      img.src = a.url || `/attachment/${a.id}`;
      img.className = "att-image";
      el.appendChild(img);
    } else if (a.kind === "audio") {
      const audio = document.createElement("audio");
      audio.src = a.url || `/attachment/${a.id}`;
      audio.controls = true;
      el.appendChild(audio);
    }
  }
  if (content) {
    if (role === "routine") {
      el.appendChild(renderMarkdown(content));
    } else {
      const span = document.createElement("span");
      span.textContent = content;
      el.appendChild(span);
    }
  }
  if (role === "user") {
    const ticks = document.createElement("span");
    ticks.className = "ticks";
    ticks.textContent = "✓"; // sent / stored
    el.appendChild(ticks);
    if (taskId) userTicks[taskId] = ticks;
  }
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  maybeNotify(role, content);
}

function maybeNotify(role, content) {
  if (role !== "routine") return;
  if (document.visibilityState === "visible") return;
  if (window.Notification && Notification.permission === "granted") {
    new Notification("tether", { body: content?.slice(0, 120) || "reply", icon: "/icon.svg" });
  }
}

// ---------- sessions ----------
function renderSessions() {
  const q = (searchEl.value || "").toLowerCase();
  sessionListEl.replaceChildren();
  for (const s of sessions) {
    if (q && !(s.title || "").toLowerCase().includes(q)) continue;
    const li = document.createElement("li");
    li.className = "session-item" + (s.id === sessionId ? " active" : "");
    const name = document.createElement("span");
    name.className = "session-name";
    name.textContent = s.title || "Chat";
    name.addEventListener("click", () => switchSession(s.id));
    name.addEventListener("dblclick", () => renameSession(s.id, s.title));
    const del = document.createElement("button");
    del.className = "session-del";
    del.type = "button";
    del.textContent = "×";
    del.title = "Delete chat";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteSession(s.id);
    });
    li.appendChild(name);
    li.appendChild(del);
    sessionListEl.appendChild(li);
  }
  const current = sessions.find((s) => s.id === sessionId);
  sessionTitleEl.textContent = current ? current.title || "tether" : "tether";
}

function switchSession(sid) {
  sessionId = sid;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "subscribe", payload: { session_id: sid } }));
  }
  hydrate(sid);
  renderSessions();
  closeSidebar();
}

async function hydrate(sid) {
  try {
    const res = await fetch(`/api/sessions/${sid}/messages?limit=300`);
    const msgs = await res.json();
    messagesEl.replaceChildren();
    for (const m of msgs) addMessage(m.role, m.content, m.attachments, m.task_id);
  } catch (e) {
    /* live frames still arrive */
  }
}

async function newSession() {
  const res = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "New chat" }),
  });
  const s = await res.json();
  switchSession(s.id);
}

async function renameSession(sid, currentTitle) {
  const title = prompt("Rename chat:", currentTitle || "");
  if (!title) return;
  await fetch(`/api/sessions/${sid}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

async function deleteSession(sid) {
  if (!confirm("Delete this chat?")) return;
  await fetch(`/api/sessions/${sid}`, { method: "DELETE" });
  if (sid === sessionId) {
    const next = sessions.find((s) => s.id !== sid);
    if (next) switchSession(next.id);
  }
}

// ---------- attachments ----------
async function uploadFile(file, kind) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("kind", kind);
  const res = await fetch("/upload", { method: "POST", body: fd });
  if (!res.ok) {
    addMessage("system", `upload failed (${res.status})`);
    return null;
  }
  return res.json();
}

on(attachBtn, "click", () => fileInput.click());
on(fileInput, "change", async () => {
  const file = fileInput.files[0];
  fileInput.value = "";
  if (!file) return;
  const att = await uploadFile(file, "image");
  if (att) {
    pendingAttachments.push(att);
    addMessage("system", `attached: ${file.name}`);
  }
});

// ---------- voice notes ----------
let recorder = null;
let recChunks = [];
let recognition = null;
let recTranscript = "";

on(micBtn, "click", async () => {
  if (recorder && recorder.state === "recording") {
    recorder.stop();
    if (recognition) recognition.stop();
    micBtn.classList.remove("recording");
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recChunks = [];
    recTranscript = "";
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => recChunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(recChunks, { type: recorder.mimeType || "audio/webm" });
      const file = new File([blob], "voice.webm", { type: blob.type });
      const att = await uploadFile(file, "audio");
      if (!att) return;
      const text = voiceMode === "browser" ? recTranscript.trim() : "";
      if (!text) addMessage("system", "voice note sent, transcribing...");
      ws.send(
        JSON.stringify({
          type: "user_message",
          payload: { text, attachment_ids: [att.id] },
        }),
      );
    };
    recorder.start();
    micBtn.classList.add("recording");
    // live client-side transcription only when the server uses voice = browser;
    // for whisper the server transcribes the uploaded audio.
    if (voiceMode === "browser") {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (SR) {
        recognition = new SR();
        recognition.continuous = true;
        recognition.interimResults = false;
        recognition.onresult = (e) => {
          for (let i = e.resultIndex; i < e.results.length; i++) {
            recTranscript += e.results[i][0].transcript + " ";
          }
        };
        recognition.start();
      }
    }
  } catch (e) {
    addMessage("system", "microphone unavailable");
  }
});

// ---------- send ----------
on(form, "submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if ((!text && pendingAttachments.length === 0) || !ws || ws.readyState !== WebSocket.OPEN) {
    return;
  }
  ws.send(
    JSON.stringify({
      type: "user_message",
      payload: { text, attachment_ids: pendingAttachments.map((a) => a.id) },
    }),
  );
  input.value = "";
  pendingAttachments = [];
  if (window.Notification && Notification.permission === "default") {
    Notification.requestPermission();
  }
});

// ---------- sidebar (mobile) ----------
function openSidebar() {
  sidebar.classList.add("open");
  scrim.classList.add("show");
}
function closeSidebar() {
  sidebar.classList.remove("open");
  scrim.classList.remove("show");
}
on(menuBtn, "click", openSidebar);
on(scrim, "click", closeSidebar);
on(newBtn, "click", newSession);
on(searchEl, "input", renderSessions);

// ---------- widgets (clickable command buttons) ----------
function widgetHeaders(extra) {
  const h = extra ? { ...extra } : {};
  if (token) h["X-Tether-Token"] = token;
  return h;
}

function sendWidget(command) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "user_message", payload: { text: command } }));
  }
}

async function deleteWidget(id) {
  if (!confirm("Delete this widget?")) return;
  await fetch(`/api/widgets/${id}`, { method: "DELETE", headers: widgetHeaders() });
}

function renderWidgets() {
  widgetsEl.replaceChildren();
  for (const w of widgets) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "widget";
    const nAsk = (w.params || []).length;
    btn.title = nAsk ? `${w.command}\n(asks for ${nAsk} input(s))` : w.command;
    const label = document.createElement("span");
    label.textContent = w.name;
    if (nAsk) {
      const badge = document.createElement("span");
      badge.className = "wbadge";
      badge.textContent = nAsk;
      badge.title = `${nAsk} input(s) to fill on click`;
      label.append(" ", badge);
    }
    const edit = document.createElement("span");
    edit.className = "we";
    edit.textContent = "✎";
    edit.title = "Edit widget";
    edit.addEventListener("click", (e) => {
      e.stopPropagation();
      openBuilder(w);
    });
    const del = document.createElement("span");
    del.className = "wx";
    del.textContent = "×";
    del.title = "Delete widget";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteWidget(w.id);
    });
    btn.append(label, edit, del);
    btn.addEventListener("click", () => runWidget(w));
    widgetsEl.appendChild(btn);
  }
  // the "+ Add" button is static markup (pinned, always visible), wired below.
}

renderWidgets();

// ---------- widget builder (form from a command's --help) ----------
let wbEditId = null; // widget being edited, or null when creating a new one
let wbEditWidget = null; // the widget being edited (for its existing params)
let wbBase = ""; // command whose --help is currently shown
let wbControls = []; // {type:'pos'|'opt', flag, metavar, takesValue, el, askEl}
let wbParams = []; // ask-on-click params collected from the form
let wbFullDirty = false; // user edited the command box by hand

function firstToken(s) {
  return (s || "").trim().split(/\s+/)[0] || "";
}

function shQuote(v) {
  if (v === "") return "''";
  if (/^[\w./:=@%+-]+$/.test(v)) return v;
  return "'" + v.replace(/'/g, "'\\''") + "'";
}

// Fill the command box's autocomplete with the available commands (same list as
// /c). Built once, lazily, so the add form suggests your commands as you type.
async function populateCmdDatalist() {
  if (!wbCmdList || wbCmdList.childElementCount) return;
  const cmds = await loadCommands();
  const frag = document.createDocumentFragment();
  for (const c of cmds) {
    const o = document.createElement("option");
    o.value = c;
    frag.appendChild(o);
  }
  wbCmdList.replaceChildren(frag);
}

function openBuilder(widget) {
  closeDirPicker();
  closeCmdPicker();
  closeRunDialog();
  populateCmdDatalist();
  wbControls = [];
  wbParams = [];
  wbFields.replaceChildren();
  if (widget) {
    wbEditId = widget.id;
    wbEditWidget = widget;
    wbName.value = widget.name;
    wbFull.value = widget.command;
    wbCmd.value = firstToken(widget.command);
    wbFullDirty = true; // keep their command until they re-read parameters
  } else {
    wbEditId = null;
    wbEditWidget = null;
    wbName.value = "";
    wbFull.value = input.value.trim();
    wbCmd.value = firstToken(input.value.trim());
    wbFullDirty = !!wbFull.value;
  }
  wbBase = "";
  modalScrim.hidden = false;
  wbPanel.hidden = false;
  (wbName.value || !wbCmd.value ? wbName : wbCmd).focus();
}

function closeBuilder() {
  wbPanel.hidden = true;
  if (wrPanel.hidden) modalScrim.hidden = true;
}

function requestHelp() {
  const base = firstToken(wbCmd.value);
  if (!base) return;
  wbBase = base;
  wbControls = [];
  wbFields.replaceChildren();
  const note = document.createElement("div");
  note.className = "wb-note";
  note.textContent = `reading ${base} --help ...`;
  wbFields.appendChild(note);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "help_request", payload: { command: base } }));
  }
}

function stripFences(t) {
  return (t || "").replace(/^```[^\n]*\n?/, "").replace(/\n?```\s*$/, "").trim();
}

// Best-effort parse of argparse / click style --help into positionals + options.
function parseHelp(raw) {
  const lines = stripFences(raw).split("\n");
  const positionals = [];
  const options = [];
  let section = "";
  let last = null; // last entry, for wrapped help continuation lines
  const optHead = /^(options|optional arguments|flags)\s*:?\s*$/i;
  const posHead = /^(positional arguments|arguments)\s*:?\s*$/i;
  for (const rawLine of lines) {
    const line = rawLine.replace(/\s+$/, "");
    if (!line.trim()) {
      last = null;
      continue;
    }
    const t = line.trim();
    if (optHead.test(t)) {
      section = "opt";
      last = null;
      continue;
    }
    if (posHead.test(t)) {
      section = "pos";
      last = null;
      continue;
    }
    const m = line.match(/^(\s*)(\S.*)$/);
    const indent = m[1].length;
    const body = m[2];
    if (indent > 0 && /^-/.test(body)) {
      const sp = body.search(/\s{2,}/);
      const spec = sp >= 0 ? body.slice(0, sp) : body;
      const help = sp >= 0 ? body.slice(sp).trim() : "";
      const flags = spec.match(/-{1,2}[A-Za-z0-9][\w-]*/g) || [];
      if (!flags.length) continue;
      const rest = spec.replace(/-{1,2}[A-Za-z0-9][\w-]*/g, "").replace(/,/g, " ").trim();
      const opt = { flags, takesValue: !!rest, help };
      opt.metavar = rest ? rest.replace(/^=/, "").trim().split(/\s+/)[0] : "";
      const dm = help.match(/[[(]default:?\s*([^\])]+)[\])]/i);
      if (dm) opt.def = dm[1].trim().replace(/^["']|["']$/g, "");
      options.push(opt);
      last = opt;
      if (!section) section = "opt";
    } else if (section === "pos" && indent > 0) {
      const sp = body.search(/\s{2,}/);
      const name = (sp >= 0 ? body.slice(0, sp) : body).trim();
      const help = sp >= 0 ? body.slice(sp).trim() : "";
      if (/^[A-Za-z0-9_{<[]/.test(name)) {
        const pos = { name, help };
        positionals.push(pos);
        last = pos;
      }
    } else if (last && indent >= 2) {
      last.help = (last.help + " " + body.trim()).trim();
    }
  }
  return { positionals, options };
}

function longFlag(flags) {
  return flags.find((f) => f.startsWith("--")) || flags[0];
}

function paramKey(used, base) {
  let k = (base || "arg").replace(/^-+/, "").replace(/\W+/g, "_").toLowerCase();
  if (!k) k = "arg";
  let name = k;
  let i = 2;
  while (used.has(name)) name = `${k}_${i++}`;
  used.add(name);
  return name;
}

// Build the command from the form. A field marked "ask on click" becomes a
// {{key}} placeholder plus a param entry (its current value is the default);
// everything else is baked in literally.
function assembleFull() {
  const parts = [wbBase];
  const params = [];
  const used = new Set();
  for (const c of wbControls) {
    if (c.type !== "opt") continue;
    if (c.takesValue) {
      if (c.askEl && c.askEl.checked) {
        const key = paramKey(used, c.flag);
        parts.push(c.flag, `{{${key}}}`);
        params.push({
          key,
          label: c.flag + (c.metavar ? ` ${c.metavar}` : ""),
          default: c.el.value.trim(),
        });
      } else {
        const v = c.el.value.trim();
        if (v) parts.push(c.flag, shQuote(v));
      }
    } else if (c.el.checked) {
      parts.push(c.flag);
    }
  }
  for (const c of wbControls) {
    if (c.type !== "pos") continue;
    if (c.askEl && c.askEl.checked) {
      const key = paramKey(used, c.name);
      parts.push(`{{${key}}}`);
      params.push({ key, label: c.name, default: c.el.value.trim() });
    } else {
      const v = c.el.value.trim();
      if (v) parts.push(shQuote(v));
    }
  }
  wbFull.value = parts.join(" ");
  wbParams = params;
  wbFullDirty = false;
}

function codeLabel(text, suffix) {
  const code = document.createElement("code");
  code.textContent = text;
  const out = [code];
  if (suffix) out.push(document.createTextNode(suffix));
  return out;
}

function askToggle(onChange) {
  const wrap = document.createElement("label");
  wrap.className = "wb-ask";
  const box = document.createElement("input");
  box.type = "checkbox";
  const txt = document.createElement("span");
  txt.textContent = "ask on click";
  wrap.append(box, txt);
  box.addEventListener("change", onChange);
  return { wrap, box };
}

// A value field (positional or value-option): label, help, then the input next
// to an "ask on click" toggle. When ask is on, the value is the click default.
function valueField(labelNodes, helpText, placeholder, defVal) {
  const wrap = document.createElement("div");
  wrap.className = "wb-field";
  const label = document.createElement("span");
  label.className = "wb-label";
  label.append(...labelNodes);
  wrap.appendChild(label);
  if (helpText) {
    const h = document.createElement("span");
    h.className = "wb-help";
    h.textContent = helpText;
    wrap.appendChild(h);
  }
  const row = document.createElement("div");
  row.className = "wb-inputrow";
  const inp = document.createElement("input");
  inp.type = "text";
  inp.placeholder = placeholder;
  if (defVal) inp.value = defVal;
  inp.addEventListener("input", assembleFull);
  const ask = askToggle(() => {
    inp.placeholder = ask.box.checked ? "default (optional)" : placeholder;
    assembleFull();
  });
  row.append(inp, ask.wrap);
  wrap.appendChild(row);
  wbFields.appendChild(wrap);
  return { inp, askBox: ask.box };
}

function renderFields(spec) {
  wbControls = [];
  wbFields.replaceChildren();
  if (!spec.positionals.length && !spec.options.length) {
    const note = document.createElement("div");
    note.className = "wb-note";
    note.textContent =
      "Could not read parameters from --help. Type the full command below.";
    wbFields.appendChild(note);
    return;
  }
  for (const p of spec.positionals) {
    const f = valueField(codeLabel(p.name), p.help, p.name, "");
    wbControls.push({ type: "pos", name: p.name, el: f.inp, askEl: f.askBox });
  }
  for (const o of spec.options) {
    const flag = longFlag(o.flags);
    if (["--help", "-h", "--version"].includes(flag)) continue;
    if (o.takesValue) {
      const f = valueField(
        codeLabel(o.flags.join(", "), o.metavar ? " " + o.metavar : ""),
        o.help,
        o.metavar || "value",
        o.def || "",
      );
      wbControls.push({
        type: "opt",
        flag,
        metavar: o.metavar,
        takesValue: true,
        el: f.inp,
        askEl: f.askBox,
      });
    } else {
      const wrap = document.createElement("div");
      wrap.className = "wb-field wb-flag";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.addEventListener("change", assembleFull);
      const label = document.createElement("span");
      label.className = "wb-label";
      label.append(...codeLabel(o.flags.join(", ")));
      wrap.append(box, label);
      wbFields.appendChild(wrap);
      wbControls.push({ type: "opt", flag, takesValue: false, el: box });
    }
  }
  assembleFull();
}

function onHelpResult(p) {
  if (wbPanel.hidden || p.command !== wbBase) return;
  if (!p.ok) {
    wbControls = [];
    wbFields.replaceChildren();
    const note = document.createElement("div");
    note.className = "wb-note";
    note.textContent =
      p.error === "no routine connected"
        ? "No routine is connected, so parameters can't be read. Type the full command below."
        : `Could not read parameters (${p.error || "error"}). Type the full command below.`;
    wbFields.appendChild(note);
    return;
  }
  renderFields(parseHelp(p.text));
}

// One param per distinct {{key}} in the command, so hand-edited placeholders in
// the command box also become click-time inputs. Labels/defaults are reused from
// the form's collected params and, when editing, the widget's existing params.
function deriveParams(command, known) {
  const keys = [
    ...new Set([...command.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1])),
  ];
  const byKey = {};
  for (const p of known || []) byKey[p.key] = p;
  return keys.map((k) => byKey[k] || { key: k, label: k, default: "" });
}

async function saveBuilder() {
  const name = wbName.value.trim();
  const command = wbFull.value.trim();
  if (!name || !command) {
    wbName.focus();
    return;
  }
  const known = {};
  for (const p of (wbEditWidget && wbEditWidget.params) || []) known[p.key] = p;
  for (const p of wbParams) known[p.key] = p;
  const params = deriveParams(command, Object.values(known));
  const url = wbEditId ? `/api/widgets/${wbEditId}` : "/api/widgets";
  await fetch(url, {
    method: wbEditId ? "PUT" : "POST",
    headers: widgetHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ name, command, params }),
  });
  closeBuilder();
  // server broadcasts the updated list -> renderWidgets()
}

// ---------- widget run dialog (fill ask-on-click params, then send) ----------
let wrWidget = null;
let wrInputs = {};

function fillCommand(widget, values) {
  let cmd = widget.command;
  for (const p of widget.params || []) {
    const raw = (values[p.key] || "").trim();
    cmd = cmd.split(`{{${p.key}}}`).join(shQuote(raw || p.default || ""));
  }
  return cmd;
}

function updateRunPreview() {
  const values = {};
  for (const p of wrWidget.params) values[p.key] = wrInputs[p.key].value;
  wrPreview.textContent = fillCommand(wrWidget, values);
}

function openRunDialog(widget) {
  closeDirPicker();
  closeCmdPicker();
  closeBuilder();
  wrWidget = widget;
  wrInputs = {};
  wrTitle.textContent = widget.name;
  wrFields.replaceChildren();
  for (const p of widget.params) {
    const wrap = document.createElement("div");
    wrap.className = "wb-field";
    const label = document.createElement("span");
    label.className = "wb-label";
    label.append(...codeLabel(p.label || p.key));
    if (p.required) {
      const star = document.createElement("span");
      star.className = "req-star";
      star.textContent = " *";
      star.title = "required";
      label.appendChild(star);
    }
    const inp = document.createElement("input");
    inp.type = "text";
    inp.value = p.default || "";
    inp.placeholder = (p.label || p.key) + (p.required ? "  (required)" : "");
    inp.addEventListener("input", () => {
      inp.classList.remove("invalid");
      updateRunPreview();
    });
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        runFilled();
      }
    });
    wrap.append(label, inp);
    wrFields.appendChild(wrap);
    wrInputs[p.key] = inp;
  }
  modalScrim.hidden = false;
  wrPanel.hidden = false;
  updateRunPreview();
  const first = wrFields.querySelector("input");
  if (first) first.focus();
}

function closeRunDialog() {
  wrPanel.hidden = true;
  if (wbPanel.hidden) modalScrim.hidden = true;
}

// A required field left empty blocks the run: mark it, focus the first offender.
function validateRun() {
  let firstBad = null;
  for (const p of (wrWidget && wrWidget.params) || []) {
    if (!p.required) continue;
    const inp = wrInputs[p.key];
    if (inp && !inp.value.trim()) {
      inp.classList.add("invalid");
      if (!firstBad) firstBad = inp;
    }
  }
  if (firstBad) {
    firstBad.focus();
    return false;
  }
  return true;
}

function runFilled() {
  if (!wrWidget) return;
  if (!validateRun()) return;
  sendWidget(wrPreview.textContent);
  closeRunDialog();
}

// Click a widget: fill its inputs first if it has any, else send straight away.
function runWidget(widget) {
  if (widget.params && widget.params.length) openRunDialog(widget);
  else sendWidget(widget.command);
}

on(wrClose, "click", closeRunDialog);
on(wrRun, "click", runFilled);
on(modalScrim, "click", () => {
  closeBuilder();
  closeRunDialog();
});

on(widgetAdd, "click", () => openBuilder(null));
on(wbRead, "click", requestHelp);
on(wbCmd, "keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    requestHelp();
  }
});
on(wbFull, "input", () => {
  wbFullDirty = true;
});
on(wbClose, "click", closeBuilder);
on(wbSave, "click", saveBuilder);

// ---------- task status ----------
function addStatus(text) {
  const el = document.createElement("div");
  el.className = "msg msg-status";
  el.textContent = "· " + text;
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addRetry(taskId) {
  const el = document.createElement("div");
  el.className = "msg msg-status";
  el.textContent = "task needs attention ";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "retry-btn";
  btn.textContent = "Retry";
  btn.addEventListener("click", () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "redispatch", payload: { task_id: taskId } }));
    }
  });
  el.appendChild(btn);
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function handleTaskStatus(p) {
  const active = ["ready", "claimed", "running"].includes(p.state);
  if (active) {
    currentTaskId = p.task_id;
    stopBtn.hidden = false;
  } else if (p.task_id === currentTaskId) {
    currentTaskId = null;
    stopBtn.hidden = true;
  }
  const tick = userTicks[p.task_id];
  if (tick) {
    if (p.state === "ready") {
      tick.textContent = "✓";
    } else if (p.state === "claimed" || p.state === "running") {
      tick.textContent = "✓✓";
    } else if (p.state === "completed") {
      tick.textContent = "✓✓";
      tick.classList.add("done");
    } else if (p.state === "needs_attention" || p.state === "failed") {
      tick.textContent = "!";
      tick.classList.add("warn");
    }
  }
  if (p.state === "needs_attention") addRetry(p.task_id);
}

on(stopBtn, "click", () => {
  if (currentTaskId && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "cancel", payload: { task_id: currentTaskId } }));
  }
});

// ---------- directory picker (/d): type a path or click to navigate ----------
let dirDebounce = null;

function dirParent(p) {
  const i = p.lastIndexOf("/");
  return i <= 0 ? "/" : p.slice(0, i + 1);
}

async function fetchDirs(path) {
  const headers = token ? { "X-Tether-Token": token } : {};
  const url = path ? `/api/dirs?path=${encodeURIComponent(path)}` : "/api/dirs";
  const res = await fetch(url, { headers });
  return res.ok ? res.json() : null;
}

async function refreshDirList() {
  const v = dirInput.value || "/";
  let listDir;
  let filter;
  if (v.endsWith("/")) {
    listDir = v;
    filter = "";
  } else {
    listDir = dirParent(v);
    filter = v.slice(listDir.length);
  }
  const d = await fetchDirs(listDir);
  dirListEl.replaceChildren();
  if (!d) {
    dirEntries = [];
    const none = document.createElement("li");
    none.className = "dir-item dir-up";
    none.textContent = "(keep typing a valid path...)";
    dirListEl.appendChild(none);
    return;
  }
  dirCurrent = d.path;
  const base = d.path.replace(/\/$/, "");
  dirBase = base;
  dirEntries = d.dirs;
  if (d.parent) {
    const up = document.createElement("li");
    up.className = "dir-item dir-up";
    up.textContent = ".. (up)";
    up.addEventListener("click", () => {
      dirInput.value = d.parent.replace(/\/$/, "") + "/";
      dirInput.focus();
      refreshDirList();
    });
    dirListEl.appendChild(up);
  }
  const fl = filter.toLowerCase();
  for (const name of d.dirs) {
    if (fl && !name.toLowerCase().includes(fl)) continue;
    const li = document.createElement("li");
    li.className = "dir-item";
    li.textContent = name + "/";
    li.addEventListener("click", () => {
      dirInput.value = base + "/" + name + "/";
      dirInput.focus();
      refreshDirList();
    });
    dirListEl.appendChild(li);
  }
}

async function openDirPicker() {
  closeCmdPicker();
  if (!dirInput.value) {
    const d = await fetchDirs(null);
    if (d) dirInput.value = d.path.replace(/\/$/, "") + "/";
  }
  dirPicker.hidden = false;
  await refreshDirList();
  dirInput.focus();
}

function closeDirPicker() {
  dirPicker.hidden = true;
}

on(dirInput, "input", () => {
  clearTimeout(dirDebounce);
  dirDebounce = setTimeout(refreshDirList, 150);
});

function dirCommonPrefix(names) {
  if (!names.length) return "";
  let pre = names[0];
  for (const s of names) {
    while (pre && !s.toLowerCase().startsWith(pre.toLowerCase())) {
      pre = pre.slice(0, -1);
    }
    if (!pre) return "";
  }
  return pre;
}

// Tab = autocomplete the partial folder name; Enter = use/insert the folder.
on(dirInput, "keydown", async (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    insertCurrentDir();
    return;
  }
  if (e.key !== "Tab") return;
  e.preventDefault();
  clearTimeout(dirDebounce);
  await refreshDirList(); // sync dirEntries/dirBase to the current input
  const v = dirInput.value || "/";
  const filter = v.endsWith("/") ? "" : v.slice(dirParent(v).length);
  const fl = filter.toLowerCase();
  const starts = dirEntries.filter((n) => n.toLowerCase().startsWith(fl));
  const matches = starts.length
    ? starts
    : dirEntries.filter((n) => n.toLowerCase().includes(fl));
  if (!matches.length) return;
  if (matches.length === 1) {
    dirInput.value = dirBase + "/" + matches[0] + "/";
    await refreshDirList();
  } else {
    const cp = dirCommonPrefix(matches);
    if (cp.length > filter.length) {
      dirInput.value = dirBase + "/" + cp;
      await refreshDirList();
    }
  }
});

function insertCurrentDir() {
  const path = (dirInput.value || "").replace(/\/$/, "");
  if (!path) return;
  input.value = input.value.replace(/\/d\s*$/i, path + " ");
  closeDirPicker();
  input.focus();
}

on(dirClose, "click", closeDirPicker);
on(dirInsert, "click", insertCurrentDir);

on(input, "input", () => {
  if (/(^|\s)\/d$/i.test(input.value)) openDirPicker();
  else if (/(^|\s)\/c$/i.test(input.value)) openCmdPicker();
});

// ---------- command picker (/c) ----------
async function loadCommands() {
  if (allCommands) return allCommands;
  const headers = token ? { "X-Tether-Token": token } : {};
  const res = await fetch("/api/commands", { headers });
  allCommands = res.ok ? (await res.json()).commands : [];
  return allCommands;
}

function renderCmdList() {
  const f = (cmdInput.value || "").toLowerCase();
  const matches = (allCommands || []).filter((c) => c.toLowerCase().startsWith(f));
  cmdList.replaceChildren();
  for (const name of matches.slice(0, 300)) {
    const li = document.createElement("li");
    li.className = "dir-item";
    li.textContent = name;
    li.addEventListener("click", () => {
      cmdInput.value = name;
      insertCurrentCmd();
    });
    cmdList.appendChild(li);
  }
}

function insertCurrentCmd() {
  const cmd = (cmdInput.value || "").trim();
  if (!cmd) return;
  // prefix with "$ " so the runner treats it as a command; plain prose is not run
  input.value = input.value.replace(/\/c\s*$/i, "$ " + cmd + " ");
  closeCmdPicker();
  input.focus();
}

function closeCmdPicker() {
  cmdPicker.hidden = true;
}

async function openCmdPicker() {
  closeDirPicker();
  cmdInput.value = "";
  await loadCommands();
  cmdPicker.hidden = false;
  renderCmdList();
  cmdInput.focus();
}

on(cmdInput, "input", renderCmdList);
on(cmdClose, "click", closeCmdPicker);
on(cmdInsert, "click", insertCurrentCmd);

on(cmdInput, "keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    insertCurrentCmd();
    return;
  }
  if (e.key !== "Tab") return;
  e.preventDefault();
  const f = (cmdInput.value || "").toLowerCase();
  const matches = (allCommands || []).filter((c) => c.toLowerCase().startsWith(f));
  if (!matches.length) return;
  if (matches.length === 1) {
    cmdInput.value = matches[0];
  } else {
    const cp = dirCommonPrefix(matches);
    if (cp.length > cmdInput.value.length) cmdInput.value = cp;
  }
  renderCmdList();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeDirPicker();
    closeCmdPicker();
    closeBuilder();
    closeRunDialog();
  }
});

// ---------- websocket ----------
function connect() {
  ws = new WebSocket(`${proto}://${location.host}/ws/ui`);

  ws.addEventListener("open", () => {
    statusDot.classList.add("online");
    ws.send(JSON.stringify({ type: "hello", payload: { token } }));
  });

  ws.addEventListener("message", (ev) => {
    const f = JSON.parse(ev.data);
    const p = f.payload || {};
    if (f.type === "welcome") {
      sessions = p.sessions || [];
      voiceMode = p.voice || "browser";
      widgets = p.widgets || [];
      if (!sessionId) sessionId = p.session_id;
      renderSessions();
      renderWidgets();
      hydrate(sessionId);
    } else if (f.type === "sessions") {
      sessions = p.sessions || [];
      renderSessions();
    } else if (f.type === "widgets") {
      widgets = p.widgets || [];
      renderWidgets();
    } else if (f.type === "help_result") {
      onHelpResult(p);
    } else if (f.type === "message_appended") {
      if (!f.session_id || f.session_id === sessionId) {
        addMessage(p.role, p.content, p.attachments, p.task_id);
      }
    } else if (f.type === "task_status") {
      if (!f.session_id || f.session_id === sessionId) handleTaskStatus(p);
    } else if (f.type === "error" && p.code === "unauthorized") {
      const t = prompt("tether access token:");
      if (t) {
        localStorage.setItem("tether_token", t);
        token = t;
      }
    }
  });

  ws.addEventListener("close", () => {
    statusDot.classList.remove("online");
    setTimeout(connect, 1500);
  });
}

connect();

// No service worker. /sw.js is now a one-time kill switch that removes any worker
// a previous version registered; we never register one here, so assets are always
// served fresh from the network (no more stale-cache surprises).
