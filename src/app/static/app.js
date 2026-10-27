/* Writers Room: the app's page. Plain JavaScript, no build step.
   State lives in S; render() redraws from it; clicks go through data-act. */
"use strict";

const S = {
  view: "home",
  projects: [], recents: [], providers: [],
  project: null, data: null, thread: null,
  chat: null, panel: false, doc: null,
  home: { draft: "", mode: "", menu: false, note: "" },
  draft: "", projectDraft: "", pending: [],
  busy: null, creating: false,
  expanded: {}, tipDismissed: false,
  settings: null, providerInput: {}, providerMsg: {},
  job: null, jobKey: null, trayHidden: false,
  modal: null, toast: "",
  selection: null, explore: false,
  theme: savedTheme(), drawer: false, picker: false, reader: null, files: false,
};

/* ---------- helpers ---------- */

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n || 0).toLocaleString("en-US");
const attr = (o) => Object.entries(o).map(([k, v]) => `data-${k}="${esc(v)}"`).join(" ");

const ICONS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  chat: '<path d="M4 5h16v11H8l-4 4V5z"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/>',
  bulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"/>',
  chev: '<path d="M9 6l6 6-6 6"/>',
  back: '<path d="M15 6l-6 6 6 6"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  clip: '<path d="M21 11l-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L15 7"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  doc: '<path d="M7 3h7l5 5v13H7V3z"/><path d="M14 3v5h5"/>',
  pen: '<path d="M4 20h4L19 9l-4-4L4 16v4z"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/>',
  panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
  sliders: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
  book: '<path d="M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3V4z"/><path d="M5 17a3 3 0 0 1 3-3h10"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  auto: '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/>',
  read: '<path d="M3 5h6a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H3V5z"/><path d="M21 5h-6a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h7V5z"/>',
  down: '<path d="M6 9l6 6 6-6"/>',
};
// Strokes use currentColor so a colour can be a CSS variable and follow the theme.
const ic = (name, size = 18, color = "currentColor", width = 1.9) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor"${color === "currentColor" ? "" : ` style="color:${color}"`} stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
const fmtK = (n) => (n >= 1000 ? `${fmt(Math.round(n / 1000))}K` : fmt(n));

function savedTheme() {
  try { return localStorage.getItem("wr-theme") || "auto"; } catch (e) { return "auto"; }
}
function applyTheme() {
  if (S.theme === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = S.theme;
}

async function api(method, path, params) {
  let url = path;
  const init = { method, headers: { "X-Writers-Room-Token": window.WR_TOKEN } };
  if (method === "GET" && params) url += "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v != null));
  if (method === "POST") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(params || {});
  }
  let res;
  try {
    res = await fetch(url, init);
  } catch (e) {
    throw new Error("The app isn't responding. Is the Writers Room window still open?");
  }
  const data = await res.json().catch(() => ({ error: "The app sent back something unexpected." }));
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}
const get = (p, q) => api("GET", p, q);
const post = (p, b) => api("POST", p, b);

async function streamTurn(params, receive) {
  const response = await fetch("/api/send/stream", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Writers-Room-Token": window.WR_TOKEN },
    body: JSON.stringify(params),
  });
  if (!response.ok) throw new Error((await response.json()).error || "Couldn't start this turn.");
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = "", finished = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n"); buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.kind === "error") throw new Error(event.text);
        receive(event);
        if (event.kind === "done") finished = true;
      }
      if (done) break;
    }
    if (!finished) throw new Error("The connection was interrupted. Reopen this chat to check saved changes before continuing.");
  } finally { reader.releaseLock(); }
}

function updateLive(record) {
  for (const el of document.querySelectorAll("[data-live-chat]")) {
    if (el.dataset.liveChat !== record.id || el.dataset.project !== record.project) continue;
    el.querySelector(".live-phase").textContent = record.turn.phase || "Working…";
    el.querySelector(".live-text").innerHTML = md(record.turn.text || "");
  }
}

let turnPoll = null;
function watchTurn(record) {
  if (!record || record.turn?.state !== "running" || turnPoll) return;
  const pid = record.project, cid = record.id;
  S.busy = { project: pid, chat: cid };
  turnPoll = setInterval(async () => {
    try {
      const current = await get("/api/chat", { project: pid, chat: cid });
      const old = cid === "project" ? S.thread : S.chat;
      if (S.project === pid) {
        if (cid === "project") S.thread = current;
        else if (S.chat?.id === cid) S.chat = current;
      }
      if (current.turn?.state !== "running") {
        clearInterval(turnPoll); turnPoll = null; S.busy = null;
        await refreshProject(); await refreshState(); render();
      } else if (old?.items.length !== current.items.length) { await refreshProject(); render(); }
      else updateLive(current);
    } catch (e) { clearInterval(turnPoll); turnPoll = null; S.busy = null; fail(e); }
  }, 1000);
}

function fail(err) {
  S.toast = err.message || String(err);
  render();
}

function md(text) {
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
    .replace(/(^|\W)_([^_\s][^_]*)_(?=\W|$)/g, "$1<em>$2</em>");
  const out = [];
  let list = null, para = [];
  const flush = () => {
    if (para.length) out.push(`<p>${para.map(inline).join("<br>")}</p>`);
    para = [];
    if (list) { out.push(`</${list}>`); list = null; }
  };
  for (const raw of String(text || "").split("\n")) {
    const line = raw.replace(/\s+$/, "");
    let m;
    if (!line.trim()) { flush(); continue; }
    if ((m = line.match(/^(#{1,4})\s+(.*)$/))) { flush(); out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`); continue; }
    if ((m = line.match(/^\s*([-*]|\d+\.)\s+(.*)$/))) {
      if (para.length) { out.push(`<p>${para.map(inline).join("<br>")}</p>`); para = []; }
      const kind = /\d/.test(m[1]) ? "ol" : "ul";
      if (list !== kind) {
        if (list) out.push(`</${list}>`);
        out.push(kind === "ol" ? `<ol start="${parseInt(m[1], 10)}">` : "<ul>");
        list = kind;
      }
      out.push(`<li>${inline(m[2])}</li>`);
      continue;
    }
    if (list && /^\s{2,}/.test(raw)) { out[out.length - 1] = out[out.length - 1].replace(/<\/li>$/, "<br>" + inline(line.trim()) + "</li>"); continue; }
    if (list) { out.push(`</${list}>`); list = null; }
    para.push(line);
  }
  flush();
  return out.join("");
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new Error(`Couldn't read ${file.name}.`));
    reader.readAsDataURL(file);
  });
}

/* ---------- data ---------- */

async function refreshState() {
  const state = await get("/api/state");
  S.projects = state.projects;
  S.recents = state.recents;
  S.providers = state.providers;
}

async function loadProject(pid, book) {
  const [data, thread] = await Promise.all([
    get("/api/project", { project: pid, book }),
    get("/api/chat", { project: pid, chat: "project" }),
  ]);
  S.project = pid;
  S.data = data;
  S.thread = thread;
  S.expanded[pid] = true;
  watchJob(data.build);
  watchTurn(thread);
}

async function refreshProject() {
  if (!S.project) return;
  const pid = S.project, book = S.data?.book.folder;
  const data = await get("/api/project", { project: pid, book });
  if (S.project !== pid || S.data?.book.folder !== book) return;
  S.data = data;
  const doc = S.doc;
  if (doc?.path && !doc.editing) {
    try {
      const content = await get("/api/file", { project: pid, path: doc.path });
      if (S.project === pid && S.doc === doc && !doc.editing) doc.data = content;
    } catch (e) { if (S.doc === doc && !doc.editing) S.doc = null; }
  }
}

/* ---------- build progress ---------- */

let pollTimer = null;
function watchJob(job) {
  if (!job) return;
  const changed = !S.job || S.job.state !== job.state;
  S.job = job;
  S.jobKey = { project: S.project, book: job.book };
  if (job.state === "running") {
    S.trayHidden = false;
    if (!pollTimer) pollTimer = setInterval(pollJob, 2000);
  } else if (changed && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollJob() {
  if (!S.jobKey) return;
  try {
    const job = await get("/api/build", S.jobKey);
    const before = S.job;
    S.job = job;
    const progressed = !before || before.results.length !== job.results.length || before.state !== job.state;
    if (job.state !== "running") {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    if (progressed) {
      await refreshProject();
      if (job.state !== "running") {
        if (S.view === "chat" && S.chat) S.chat = await get("/api/chat", { project: S.chat.project, chat: S.chat.id });
        if (S.view === "project") S.thread = await get("/api/chat", { project: S.project, chat: "project" });
        await refreshState();
      }
    }
    render();
  } catch (e) { /* keep polling quietly */ }
}

/* ---------- actions ---------- */

const ACT = {
  async home() { S.view = "home"; S.home.note = ""; render(); focus("home-composer"); },
  async go(d) {
    S.view = d.view; S.reader = null;
    if (d.view === "settings") S.settings = await get("/api/settings").catch((e) => (fail(e), null));
    render();
  },
  async newProject() { S.view = "home"; S.home.menu = true; S.home.note = ""; render(); focus("home-composer"); },
  toggleMenu() { S.home.menu = !S.home.menu; render(); },
  pickMode(d) { S.home.mode = d.mode; S.home.menu = false; render(); focus("home-composer"); },
  clearMode() { S.home.mode = ""; render(); },
  chipDraft(d) { S.home.draft = d.text; if (d.mode) S.home.mode = d.mode; render(); focus("home-composer"); },
  async sendHome() {
    const idea = S.home.draft.trim();
    if (!idea) { S.home.note = "Type an idea first, even a single line."; return render(); }
    if (!S.providers.length) { S.home.note = "Connect a model provider first. It takes a minute, in Settings."; return render(); }
    S.creating = true; render();
    try {
      const res = await post("/api/projects", { idea, kind: S.home.mode || "book", defer: true });
      S.home = { draft: "", mode: "", menu: false, note: "" };
      await refreshState();
      await loadProject(res.project);
      S.view = "project"; S.doc = null;
      S.creating = false; S.projectDraft = idea;
      await ACT.startChat();
    } catch (e) { S.toast = e.message; }
    S.creating = false; render();
  },
  async toggleProject(d) { S.expanded[d.project] = !S.expanded[d.project]; render(); },
  async openProject(d) {
    S.selection = null; S.reader = null;
    try { await loadProject(d.project); S.view = "project"; S.doc = null; S.files = false; S.projectDraft = S.projectDraft || ""; } catch (e) { return fail(e); }
    render();
  },
  async switchBook(d) {
    S.selection = null;
    try { S.data = await get("/api/project", { project: S.project, book: d.book }); S.doc = null; } catch (e) { return fail(e); }
    render();
  },
  async openChat(d) {
    try {
      const chat = await get("/api/chat", { project: d.project, chat: d.chat });
      if (S.project !== d.project || !S.data) await loadProject(d.project);
      S.chat = chat; S.view = "chat"; S.panel = false; S.doc = null; S.draft = ""; S.reader = null;
      S.selection = null; watchTurn(chat);
    } catch (e) { return fail(e); }
    render(); focus("composer");
  },
  async newChat(d) {
    try {
      const chat = await post("/api/chats", { project: d.project });
      await loadProject(d.project);
      S.chat = chat; S.view = "chat"; S.panel = false; S.doc = null;
      S.selection = null;
      await refreshState();
    } catch (e) { return fail(e); }
    render(); focus("composer");
  },
  async send(d) {
    if (S.busy) return;
    const inThread = d.where === "thread";
    const text = (inThread ? S.projectDraft : S.draft).trim();
    if (!text && !S.pending.length) return;
    const cid = inThread ? "project" : S.chat.id;
    let record = inThread ? S.thread : S.chat;
    const previousTurn = record.turn?.id;
    const pid = S.project, book = S.data?.book.folder, selection = S.selection, explore = S.explore;
    record.items = record.items.concat([{ kind: "user", id: "tmp", text, files: S.pending.map((p) => p.name) }]);
    const attachments = S.pending;
    if (inThread) S.projectDraft = ""; else S.draft = "";
    S.pending = [];
    S.selection = null;
    S.busy = { chat: cid, project: S.project };
    render();
    let started = false;
    const place = () => {
      if (S.thread?.id === cid && (S.thread.project === pid || S.thread.project === record.project)) S.thread = record;
      if (S.chat?.id === cid && (S.chat.project === pid || S.chat.project === record.project)) S.chat = record;
    };
    try {
      await streamTurn({ project: pid, chat: cid, text, attachments, book, selection, explore }, (event) => {
        if (event.kind === "started" || event.kind === "done") {
          record = event.record; started = true; place(); render();
        } else if (event.kind === "text") {
          record.turn.text += event.text; updateLive(record);
        } else if (event.kind === "phase") {
          record.turn.phase = event.text; record.turn.text = ""; updateLive(record);
        } else if (event.kind === "item") {
          record.items.push(event.item); record.turn.text = ""; place(); render();
          if (S.project === pid && event.item.file) refreshProject().then(render).catch(() => {});
        }
      });
      if (S.project === pid) {
        if (record.project !== pid) { S.doc = null; S.selection = null; }
        S.project = record.project;
        if (S.data?.book.folder === book && record.book !== book) {
          S.data = await get("/api/project", { project: S.project, book: record.book });
          S.doc = null; S.selection = null;
        }
        await refreshProject();
      }
      await refreshState();
    } catch (e) {
      try {
        const recovered = await get("/api/chat", { project: pid, chat: cid });
        if (recovered.turn?.id && recovered.turn.id !== previousTurn) {
          record = recovered; started = true; place();
        }
      } catch (_) { /* Keep the last visible state if the server is unavailable. */ }
      if (!started) {
        record.items = record.items.filter((i) => i.id !== "tmp");
        if (inThread) S.projectDraft = text; else S.draft = text;
        S.pending = attachments; S.selection = selection;
      }
      S.toast = e.message;
    }
    S.busy = null;
    if (record.turn?.state === "running") watchTurn(record);
    render();
    focus(inThread ? "project-composer" : "composer");
  },
  async stopChat(d) {
    await post("/api/chat/stop", { project: d.project, chat: d.chat });
    const record = d.chat === "project" ? S.thread : S.chat;
    if (record?.turn) { record.turn.phase = "Stopping… Completed changes will be kept."; updateLive(record); }
  },
  clearSelection() { S.selection = null; render(); },
  async forgetAttachment(d) {
    const record = await post("/api/chat/attachment/remove", { project: S.project, chat: d.chat, path: d.path });
    if (d.chat === "project") S.thread = record; else S.chat = record;
    render();
  },
  passage(d) {
    if (!S.selection) return;
    S.reader = null;
    const requests = { discuss: "Let's discuss this passage.", alternatives: "Suggest three alternatives for this passage; don't change the file yet.", revise: "Revise this passage: " };
    S.explore = d.intent !== "revise";
    if (S.view === "chat") S.draft = requests[d.intent]; else S.projectDraft = requests[d.intent];
    render(); focus(S.view === "chat" ? "composer" : "project-composer");
  },
  async quick(d) {
    if (S.view === "chat") { S.draft = d.text; return ACT.send({ where: "chat" }); }
    S.projectDraft = d.text; return ACT.startChat();
  },
  async startChat() {
    const text = S.projectDraft.trim();
    if (!text && !S.pending.length) return focus("project-composer");
    try {
      const chat = await post("/api/chats", { project: S.project });
      S.chat = chat; S.view = "chat"; S.panel = false; S.doc = null; S.reader = null; S.files = false;
      S.draft = text; S.projectDraft = "";
      await refreshState();
    } catch (e) { return fail(e); }
    return ACT.send({ where: "chat" });
  },
  showProjectFiles() { S.files = true; S.doc = null; render(); },
  hideProjectFiles() { S.files = false; S.doc = null; render(); },
  attach() { pickFiles("attach"); },
  removePending(d) { S.pending.splice(Number(d.index), 1); render(); },
  async undo(d) {
    try {
      const record = await post("/api/undo", { project: S.project, chat: d.chat, item: d.item });
      if (d.chat === "project") S.thread = record; else S.chat = record;
      await refreshProject();
    } catch (e) { return fail(e); }
    render();
  },
  async approve(d) {
    try {
      const job = await post("/api/build", { project: S.project, book: d.book, which: d.which, chat: d.chat, item: d.item });
      if (d.chat === "project") S.thread = await get("/api/chat", { project: S.project, chat: "project" });
      else S.chat = await get("/api/chat", { project: S.project, chat: d.chat });
      watchJob(job);
      await refreshProject();
    } catch (e) { return fail(e); }
    render();
  },
  async decline(d) {
    try {
      const record = await post("/api/build/decline", { project: S.project, chat: d.chat, item: d.item });
      if (d.chat === "project") S.thread = record; else S.chat = record;
    } catch (e) { return fail(e); }
    render();
  },
  async buildAsk(d) {
    try {
      const est = await get("/api/estimate", { project: S.project, book: S.data.book.folder, which: d.which });
      S.modal = { kind: "build", which: d.which, ...est };
    } catch (e) { return fail(e); }
    render();
  },
  async buildGo() {
    const which = S.modal.which;
    S.modal = null;
    const cid = S.view === "chat" && S.chat ? S.chat.id : "project";
    try {
      const job = await post("/api/build", { project: S.project, book: S.data.book.folder, which, chat: cid });
      watchJob(job);
      await refreshProject();
    } catch (e) { return fail(e); }
    render();
  },
  async stopBuild() {
    try { S.job = await post("/api/build/stop", S.jobKey); } catch (e) { return fail(e); }
    render();
  },
  hideTray() { S.trayHidden = true; render(); },
  closeModal() { S.modal = null; render(); },
  closeToast() { S.toast = ""; render(); },
  togglePanel() { S.panel = !S.panel; if (!S.panel) S.doc = null; render(); },
  closePanel() { S.panel = false; S.doc = null; render(); },
  showFiles() { S.doc = null; render(); },
  async openFile(d) {
    try { S.doc = { path: d.path, data: await get("/api/file", { project: S.project, path: d.path }) }; } catch (e) { return fail(e); }
    S.panel = true; S.files = true; render();
  },
  openEmptyChapter(d) { S.doc = { empty: Number(d.number), title: d.title }; S.panel = true; render(); },
  editDoc() { S.doc.editing = true; S.doc.text = S.doc.data.text; render(); focus("doc-editor"); },
  cancelEdit() { S.doc.editing = false; render(); },
  async saveDoc() {
    try {
      S.doc.data = await post("/api/file", { project: S.project, path: S.doc.path, text: S.doc.text, version: S.doc.data.version });
      S.doc.editing = false;
      await refreshProject();
    } catch (e) { return fail(e); }
    render();
  },
  addReference(d) { pickFiles("ref", d.scope); },
  async removeReference(d) {
    try { S.data = await post("/api/reference/remove", { project: S.project, path: d.path, book: S.data.book.folder }); } catch (e) { return fail(e); }
    render();
  },
  async reviewCall(d) {
    const point = S.doc.data.points.find((p) => String(p.number) === d.number);
    const ideas = S.doc.data.kind === "ideas";
    const calls = ideas
      ? { agree: "Use the pick.", disagree: "Not now.", own: "Something else (in the chat)." }
      : { agree: "Agreed.", disagree: "Disagreed: keep it as it is.", own: "My own fix (in the chat)." };
    try { S.doc.data = await post("/api/review/call", { project: S.project, path: S.doc.path, number: Number(d.number), call: calls[d.call] }); } catch (e) { return fail(e); }
    const message = ideas ? `Idea ${d.number} ("${point.title}"): ` : `Point ${d.number} of the review ("${point.title}"): `;
    if (d.call === "agree") return ACT.quick({ text: message + (ideas ? "let's go with your pick. Please add it to the plan." : "I agree. Please make the suggested change.") });
    if (d.call === "own") {
      if (S.view === "chat") S.draft = message + "instead, "; else S.projectDraft = message + "instead, ";
      render(); return focus(S.view === "chat" ? "composer" : "project-composer");
    }
    render();
  },
  async exportBook() {
    try {
      const res = await post("/api/export", { project: S.project, book: S.data.book.folder });
      const blob = new Blob([res.text], { type: "text/markdown" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${S.data.book.title}.md`;
      a.click();
      await refreshProject();
    } catch (e) { return fail(e); }
    render();
  },
  dismissTip() { S.tipDismissed = true; render(); },
  toggleDrawer() { S.drawer = !S.drawer; render(); },
  cycleTheme() {
    S.theme = { auto: "light", light: "dark", dark: "auto" }[S.theme] || "auto";
    try { localStorage.setItem("wr-theme", S.theme); } catch (e) { /* the choice lasts this visit only */ }
    applyTheme(); render();
  },
  togglePicker() { S.picker = !S.picker; render(); },
  async setEffort(d) {
    try { S.settings = await post("/api/settings/effort", { role: d.role, effort: d.effort }); } catch (e) { return fail(e); }
    render();
  },
  async readChapter(d) {
    try { S.reader = { path: d.path, data: await get("/api/file", { project: S.project, path: d.path }) }; } catch (e) { return fail(e); }
    S.selection = null; render();
    const scroller = document.querySelector(".reader-scroll");
    if (scroller) scroller.scrollTop = 0;
  },
  closeReader() { S.reader = null; S.selection = null; render(); },
  async connect(d) {
    const p = S.settings.providers.find((x) => x.key === d.backend);
    try {
      if (p.connected && !S.providerInput[d.backend]) {
        S.settings = await post("/api/settings/key", { backend: d.backend, value: "" });
        S.providerMsg[d.backend] = { ok: true, text: "Disconnected." };
      } else {
        const value = (S.providerInput[d.backend] || "").trim();
        if (!value) { S.providerMsg[d.backend] = { ok: false, text: p.kind === "address" ? "Enter the address your local server runs on." : "Paste a key first." }; return render(); }
        S.providerMsg[d.backend] = { ok: true, text: "Checking…" }; render();
        S.settings = await post("/api/settings/key", { backend: d.backend, value });
        const check = await post("/api/settings/check", { backend: d.backend });
        S.providerMsg[d.backend] = { ok: check.ok, text: check.message };
        S.providerInput[d.backend] = "";
      }
      await refreshState();
    } catch (e) { S.providerMsg[d.backend] = { ok: false, text: e.message }; }
    render();
  },
  async setRole(d) {
    try { S.settings = await post("/api/settings/role", { role: d.role, backend: d.backend, model: d.model }); } catch (e) { return fail(e); }
    render();
  },
  async setPress(d) {
    const body = {}; body[d.field] = Number(d.value);
    try { S.settings = await post("/api/settings/press", body); } catch (e) { return fail(e); }
    render();
  },
  async helpTry(d) {
    const card = HELP[Number(d.index)];
    if (card.home !== undefined) { S.view = "home"; S.home.draft = card.home; render(); return focus("home-composer"); }
    if (card.open) return ACT.openProject({ project: S.projects[0].id });
    const target = S.projects[0];
    if (!target) { S.view = "home"; S.home.draft = card.ask; render(); return focus("home-composer"); }
    await ACT.openProject({ project: target.id });
    S.projectDraft = card.ask; render(); focus("project-composer");
  },
};

function focus(id) {
  setTimeout(() => {
    const el = document.getElementById(id);
    if (el) { el.focus(); if (el.setSelectionRange) el.setSelectionRange(el.value.length, el.value.length); }
  }, 0);
}

function pickFiles(purpose, scope) {
  const input = document.getElementById("file-input");
  input.value = "";
  input.onchange = async () => {
    for (const file of input.files) {
      try {
        const data = await readFile(file);
        if (purpose === "attach") {
          S.pending.push({ ...await post("/api/attachment", { name: file.name, data }), scope: "chat" });
        } else {
          S.data = await post("/api/reference", { project: S.project, scope, book: S.data.book.folder, name: file.name, data });
        }
      } catch (e) { S.toast = e.message; }
    }
    render();
  };
  input.click();
}

/* ---------- views ---------- */

function sidebar() {
  const nav = (act, icon, label, on, extra = {}) =>
    `<button type="button" class="nav-btn ${on ? "on" : ""}" ${attr({ act, ...extra })}>${icon}${label}</button>`;
  const inChat = S.view === "chat" && S.chat;
  const projects = S.projects.map((p) => {
    const open = !!S.expanded[p.id];
    const here = (S.view === "project" || S.view === "chat") && S.project === p.id;
    const chats = open ? `<div class="side-chats">
      ${p.chats.map((c) => `<button type="button" class="side-chat ${inChat && S.chat.id === c.id && S.chat.project === p.id ? "on" : ""}" ${attr({ act: "openChat", project: p.id, chat: c.id })}>${esc(c.title)}</button>`).join("")}
      <button type="button" class="side-chat add" ${attr({ act: "newChat", project: p.id })}>${ic("plus", 12, "currentColor", 2.6)} New chat</button>
    </div>` : "";
    return `<div><div class="side-project ${here ? "on" : ""}">
      <button type="button" class="icon-btn" aria-expanded="${open}" aria-label="${open ? "Hide" : "Show"} chats in ${esc(p.title)}" ${attr({ act: "toggleProject", project: p.id })}><span style="display:inline-flex;transform:rotate(${open ? 90 : 0}deg);transition:transform .15s">${ic("chev", 14, "currentColor", 2.2)}</span></button>
      <button type="button" class="side-row" ${attr({ act: "openProject", project: p.id })}>${ic("folder", 16, "var(--accent)", 1.8)}<span class="name">${esc(p.title)}</span><span class="muted" style="font-size:12px">${p.chats.length || ""}</span></button>
    </div>${chats}</div>`;
  }).join("");
  const recents = S.recents.slice(0, 12).map((r) =>
    `<button type="button" class="recent ${inChat && S.chat.id === r.id ? "on" : ""}" ${attr({ act: "openChat", project: r.project, chat: r.id })}><span class="t">${esc(r.title)}</span><span class="muted" style="font-size:12px">${esc(r.projectTitle)}</span></button>`).join("");
  const count = S.providers.length;
  const themeName = { auto: "match the system", light: "light", dark: "dark" }[S.theme];
  const summary = count === 0 ? "No model provider yet" : count === 1 ? `${S.providers[0].name} connected` : `${count} providers connected`;
  const tip = count === 0 && !S.tipDismissed && S.view !== "settings"
    ? `<div class="tip" role="note"><span style="flex:1">Connect a provider to start.</span><button type="button" class="go" ${attr({ act: "go", view: "settings" })}>Connect</button><button type="button" class="icon-btn" style="width:24px;height:24px;color:var(--tray-muted)" aria-label="Dismiss" ${attr({ act: "dismissTip" })}>${ic("x", 10, "currentColor", 2.8)}</button></div>` : "";
  return `<nav class="side" aria-label="Writers Room">
    <div class="brand">${ic("book", 20, "currentColor", 1.8)}Writers Room</div>
    <div class="nav">
      <button type="button" class="nav-btn" ${attr({ act: "home" })}><span class="plus">${ic("plus", 14, "currentColor", 2.4)}</span><b>New chat</b></button>
      ${nav("go", ic("chat"), "Chats", S.view === "chats", { view: "chats" })}
      ${nav("go", ic("folder"), "Projects", S.view === "projects" || S.view === "project", { view: "projects" })}
      ${nav("go", ic("bulb"), "Writing help", S.view === "help", { view: "help" })}
    </div>
    <div class="side-scroll">
      <div class="side-head"><span class="label">Projects</span><button type="button" class="icon-btn" style="margin-left:auto" aria-label="New project" ${attr({ act: "newProject" })}>${ic("plus", 14, "currentColor", 2.4)}</button></div>
      ${projects || '<span class="muted" style="font-size:13px;padding:2px 10px 6px">No projects yet.</span>'}
      <div style="height:14px"></div>
      <span class="label" style="padding:0 10px 6px">Recents</span>
      ${recents || '<span class="muted" style="font-size:13px;padding:0 10px">Your chats will show up here.</span>'}
    </div>
    ${tip}
    <div class="side-foot">
      <button type="button" class="settings-btn ${S.view === "settings" ? "on" : ""}" ${attr({ act: "go", view: "settings" })}>
        <span class="avatar">You</span><span style="flex:1;min-width:0;display:flex;flex-direction:column"><b style="font-size:13px">Settings</b><span class="muted" style="font-size:12px">${esc(summary)}</span></span>${ic("sliders", 18, "currentColor", 1.8)}
      </button>
      <button type="button" class="icon-btn" style="margin-right:10px" title="Theme: ${esc(themeName)}" aria-label="Theme: ${esc(themeName)}. Change theme" ${attr({ act: "cycleTheme" })}>${ic(S.theme === "light" ? "sun" : S.theme === "dark" ? "moon" : "auto", 18, "currentColor", 1.9)}</button>
    </div>
  </nav>`;
}

function mobileBar() {
  return `<header class="mobile-bar">
    <button type="button" class="icon-btn" aria-label="Menu" aria-expanded="${S.drawer}" ${attr({ act: "toggleDrawer" })}>${ic("menu", 20, "currentColor", 2)}</button>
    <span class="brand" style="padding:0">${ic("book", 18, "currentColor", 1.8)}Writers Room</span>
  </header>${S.drawer ? `<div class="drawer-back" ${attr({ act: "toggleDrawer" })}></div>` : ""}`;
}

function homeView() {
  const h = S.home;
  const menu = h.menu ? `<div class="menu" role="menu" aria-label="Start a new project">
      <button type="button" role="menuitem" ${attr({ act: "pickMode", mode: "book" })}><b style="font-size:14px">New book</b><span class="muted" style="font-size:12px">One story, start to finish.</span></button>
      <button type="button" role="menuitem" ${attr({ act: "pickMode", mode: "series" })}><b style="font-size:14px">New series</b><span class="muted" style="font-size:12px">Several books sharing a world. Each book keeps its own characters and outline.</span></button>
    </div>` : "";
  const chip = h.mode ? `<span class="mode-chip">${h.mode === "series" ? "New series" : "New book"}<button type="button" aria-label="Remove" ${attr({ act: "clearMode" })}>${ic("x", 10, "currentColor", 2.8)}</button></span>` : "";
  const latest = S.projects[0];
  const chips = [
    latest ? `<button type="button" class="chip" ${attr({ act: "openProject", project: latest.id })}>Continue ${esc(latest.title)}</button>` : "",
    `<button type="button" class="chip" ${attr({ act: "chipDraft", mode: "series", text: "A series about a radio station on a storm-cut island, three books, each one a different winter." })}>Plan a series</button>`,
    `<button type="button" class="chip" ${attr({ act: "chipDraft", text: "Here's my rough outline:\n1. She arrives.\n2. Something is wrong.\n3. …" })}>Paste an outline</button>`,
  ].join("");
  const placeholder = h.mode === "series" ? "Describe your series: the world, the people, where it goes across books…" : "Describe an idea, paste your notes, or anything you have…";
  return `<div class="home"><div class="home-inner">
    <h1>What are we writing today?</h1>
    <div class="composer-box">
      <label for="home-composer" class="sr">Describe an idea</label>
      <textarea id="home-composer" rows="3" placeholder="${esc(placeholder)}" data-model="home.draft" data-enter="sendHome">${esc(h.draft)}</textarea>
      <div class="composer-row">
        <button type="button" class="square" style="margin-left:-4px" aria-label="Start a new book or series" aria-haspopup="menu" aria-expanded="${h.menu}" ${attr({ act: "toggleMenu" })}>${ic("plus", 16, "currentColor", 2.2)}</button>
        ${chip}${menu}
        <button type="button" class="send" aria-label="Start" ${attr({ act: "sendHome" })}>${ic("arrow", 18, "currentColor", 2.2)}</button>
      </div>
    </div>
    ${h.note ? `<p class="home-note">${esc(h.note)}</p>` : ""}
    <div class="chips">${chips}</div>
  </div></div>`;
}

function projectsView() {
  const cards = S.projects.map((p) => `<button type="button" class="project-card" ${attr({ act: "openProject", project: p.id })}>
    ${ic("folder", 22, "var(--accent)", 1.8)}<b style="font-size:17px">${esc(p.title)}</b>
    <span class="muted" style="font-size:13px">${esc(p.kind)}</span>
    <span class="muted" style="margin-top:auto;font-size:12px">${p.chapters} chapter${p.chapters === 1 ? "" : "s"} written · ${p.chats.length} chat${p.chats.length === 1 ? "" : "s"}</span>
  </button>`).join("");
  return `<div class="scroll"><div class="page">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap"><h1 class="big">Projects</h1>
      <button type="button" class="btn" style="margin-left:auto" ${attr({ act: "newProject" })}>${ic("plus", 16, "currentColor", 2.2)} New project</button></div>
    <p class="lead">Each book or series is a project: its plan, chapters and every chat about it, in one place.</p>
    ${cards ? `<div class="grid">${cards}</div>` : '<p class="lead">No projects yet. Start one from the home page with an idea, even a single line.</p>'}
  </div></div>`;
}

function chatsView() {
  const rows = S.recents.map((r) => `<button type="button" class="row" ${attr({ act: "openChat", project: r.project, chat: r.id })}>
    <span class="grow"><b style="font-size:15px">${esc(r.title)}</b><span class="snip">${esc(r.projectTitle)} · ${esc(r.snippet)}</span></span>
    <span class="muted" style="font-size:12px;white-space:nowrap">${esc((r.updated || "").slice(0, 10))}</span></button>`).join("");
  return `<div class="scroll"><div class="page narrow">
    <h1 class="big">Chats</h1>
    ${rows ? `<div class="rows">${rows}</div>` : '<p class="lead">No chats yet. Each project page has its own ongoing chat too.</p>'}
  </div></div>`;
}

function shortPath(path) {
  return String(path).replace(/^books\/(\d+)-[^/]+\//, (_, n) => (S.data && S.data.isSeries ? `Book ${Number(n)} · ` : ""));
}

function changeHtml(item) {
  if (item.before == null && item.after == null) return "";
  const before = String(item.before || "").split("\n"), after = String(item.after || "").split("\n");
  let start = 0, end = 0;
  while (start < Math.min(before.length, after.length) && before[start] === after[start]) start++;
  while (end < Math.min(before.length, after.length) - start && before[before.length - 1 - end] === after[after.length - 1 - end]) end++;
  const excerpt = (lines) => (start > 2 ? "…\n" : "") + lines.slice(Math.max(0, start - 2), end > 2 ? lines.length - end + 2 : lines.length).join("\n") + (end > 2 ? "\n…" : "");
  return `<details class="change-view" data-change-id="${esc(item.id)}"><summary>Compare changes</summary>
    <div class="change-columns"><section><b>Before</b><pre class="change-before">${esc(item.before == null ? "New file" : excerpt(before))}</pre></section>
    <section><b>After</b><pre class="change-after">${esc(item.after == null ? "File removed" : excerpt(after))}</pre></section></div></details>`;
}

function liveHtml(record) {
  if (record.turn?.state !== "running") return "";
  return `<div class="live-turn" data-live-chat="${esc(record.id)}" data-project="${esc(record.project)}">
    <div class="live-status"><span class="live-phase" role="status">${esc(record.turn.phase || "Working…")}</span>
    <button type="button" class="btn ghost small" ${attr({ act: "stopChat", project: record.project, chat: record.id })}>Stop</button></div>
    <div class="said live-text">${md(record.turn.text || "")}</div></div>`;
}

function itemsHtml(record) {
  if (!record) return "";
  const cid = record.id;
  const out = [];
  let run = [];
  const flush = () => {
    if (run.length === 1) out.push(itemHtml(run[0], cid));
    else if (run.length > 1) {
      const files = [...new Set(run.map((m) => shortPath(m.file)))];
      const names = files.slice(0, 3).join(", ") + (files.length > 3 ? ` and ${files.length - 3} more` : "");
      out.push(`<details class="activity-group" data-group-id="${esc(run[0].id)}"><summary>${ic("pen", 15, "var(--accent)", 2)}
        <span>Made ${run.length} changes</span><span class="muted names">${esc(names)}</span></summary>
        <div class="activity-list">${run.map((m) => itemHtml(m, cid)).join("")}</div></details>`);
    }
    run = [];
  };
  for (const m of record.items) {
    if (m.kind === "activity") { run.push(m); continue; }
    flush();
    out.push(itemHtml(m, cid));
  }
  flush();
  if (record.turn?.state === "running") out.push(liveHtml(record));
  else if (S.busy && S.busy.chat === cid && S.busy.project === record.project) {
    out.push(`<div class="thinking"><span class="dots"><span></span><span></span><span></span></span> Reading your files and thinking…</div>`);
  }
  return out.join("");
}

function itemHtml(m, cid) {
  if (m.kind === "user") {
    const scopes = { message: "this message only", chat: "kept in chat", book: "book reference", series: "series reference" };
    const names = m.attachments?.length ? m.attachments.map(a => `${a.name} · ${scopes[a.scope]}`).join(", ") : (m.files || []).join(", ");
    return `<div class="bubble-wrap">${names ? `<span class="files-line">${ic("clip", 13)} ${esc(names)}</span>` : ""}
      ${m.selection ? `<blockquote class="passage-quote"><b>${esc(shortPath(m.selection.path))}</b><br>${esc(m.selection.text)}</blockquote>` : ""}
      ${m.explore ? '<span class="muted">Just exploring</span>' : ""}${m.text ? `<div class="bubble">${esc(m.text)}</div>` : ""}</div>`;
  }
  if (m.kind === "assistant") return `<div class="said">${m.incomplete ? '<p class="muted">Partial reply · interrupted</p>' : ""}${md(m.text)}</div>`;
  if (m.kind === "activity") {
    const canView = /\.(md|txt)$/.test(m.file);
    const canUndo = m.before != null || m.after != null;
    return `<div class="activity ${m.undone ? "undone" : ""}">${ic("pen", 16, "var(--accent)", 2)}
      <div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:3px">
        <div class="what">${m.undone ? "Undid" : esc(m.verb)} <span class="mono" style="color:var(--ink)">${esc(shortPath(m.file))}</span></div>
        <div class="text">${esc(m.text)}</div></div>
      <div style="display:flex;gap:2px;flex:none">
        ${canView ? `<button type="button" class="link" ${attr({ act: "openFile", path: m.file })}>View</button>` : ""}
        ${canUndo ? `<button type="button" class="link" ${attr({ act: "undo", chat: cid, item: m.id })}>${m.undone ? "Redo" : "Undo"}</button>` : ""}
      </div>${changeHtml(m)}</div>`;
  }
  if (m.kind === "approval") {
    const resolved = m.status === "approved" ? "Building. Progress shows at the bottom right." : m.status === "declined" ? "Not now. Ask whenever you're ready." : "";
    return `<div class="approval"><div style="display:flex;gap:10px;align-items:flex-start">${ic("layers", 18, "var(--accent)", 2)}
      <div style="display:flex;flex-direction:column;gap:3px"><b style="font-size:15px">${esc(m.title)}</b><span class="muted" style="font-size:13px;line-height:1.5">${esc(m.detail)}</span></div></div>
      ${m.status === "pending" ? `<div style="display:flex;gap:8px;flex-wrap:wrap;padding-left:28px">
        <button type="button" class="btn" ${attr({ act: "approve", chat: cid, item: m.id, book: m.book, which: m.which })}>Build</button>
        <button type="button" class="btn ghost" ${attr({ act: "decline", chat: cid, item: m.id })}>Not now</button></div>`
        : `<span class="muted" style="padding-left:28px;font-size:13px">${esc(resolved)}</span>`}
    </div>`;
  }
  if (m.kind === "review" || m.kind === "ideas") {
    const text = m.kind === "ideas"
      ? "Fresh ideas are ready. Go through them one at a time: use the pick, skip it, or choose something else."
      : "A second opinion is ready. Go through it point by point: agree, disagree, or make your own fix.";
    return `<div class="result">${ic("doc", 16, "var(--accent)", 2)}<span style="flex:1;font-size:14px">${text}</span>
      <button type="button" class="link" ${attr({ act: "openFile", path: m.file })}>Open</button></div>`;
  }
  if (m.kind === "result") {
    return `<div class="result">${ic("check", 16, "var(--accent)", 2.6)}<span style="flex:1;font-size:14px;line-height:1.45">${esc(m.text)}</span>
      ${m.report ? `<button type="button" class="link" ${attr({ act: "openFile", path: m.report })}>View report</button>` : ""}</div>`;
  }
  return "";
}

function pendingHtml() {
  if (!S.pending.length) return "";
  return `<div class="pending">${S.pending.map((a, i) => `<span class="attach"><b>${esc(a.name)}</b><span class="muted">about ${fmt(a.tokens)} tokens</span>
    <label>Keep in <select data-attachment-scope="${i}" aria-label="Where to keep ${esc(a.name)}">
      ${[["chat", "This chat (planning only)"], ["message", "This message only"], ["book", "Book reference"], ["series", "Series reference"]].map(([v, label]) => `<option value="${v}" ${a.scope === v ? "selected" : ""}>${label}</option>`).join("")}</select></label>
    <button type="button" class="icon-btn" style="width:26px;height:26px" aria-label="Remove ${esc(a.name)}" ${attr({ act: "removePending", index: i })}>${ic("x", 12, "currentColor", 2.6)}</button></span>`).join("")}</div>`;
}

function composer(id, model, placeholder, where) {
  const busy = !!S.busy;
  const record = where === "thread" ? S.thread : S.chat;
  const references = record?.attachments || [];
  return `<div class="session-controls"><label><input type="checkbox" data-explore ${S.explore ? "checked" : ""}> Just exploring · leave files unchanged</label>
    ${references.length ? `<details><summary>References in this chat (${references.length})</summary>${references.map(a => `<div class="chat-reference"><button type="button" class="link" ${attr({ act: "openFile", path: a.path })}>${esc(a.name)}</button><button type="button" class="link" ${busy ? "disabled" : ""} ${attr({ act: "forgetAttachment", chat: record.id, path: a.path })}>Remove from context</button></div>`).join("")}</details>` : ""}</div>
    ${S.selection ? `<div class="selected-passage"><b>Selected in ${esc(shortPath(S.selection.path))}</b><blockquote>${esc(S.selection.text)}</blockquote><button type="button" class="link" ${attr({ act: "clearSelection" })}>Clear selection</button></div>` : ""}
    <div class="bar">
    <label for="${id}" class="sr">Message</label>
    <button type="button" class="icon-btn" style="width:38px;height:38px" aria-label="Attach a file" ${attr({ act: "attach" })}>${ic("clip")}</button>
    <textarea id="${id}" rows="1" placeholder="${esc(placeholder)}" data-model="${model}" data-enter="send" data-where="${where}">${esc(model === "draft" ? S.draft : S.projectDraft)}</textarea>
    <button type="button" class="send" aria-label="Send" ${busy ? "disabled" : ""} ${attr({ act: "send", where })}>${ic("arrow", 18, "currentColor", 2.2)}</button>
  </div>${modelLine()}`;
}

function chatRole() {
  return S.settings?.roles?.find((r) => r.key === "studio_chat");
}

function modelLine() {
  const role = chatRole();
  if (!role) return "";
  const current = role.options.find((o) => o.backend === role.current.backend && o.model === role.current.model);
  const parts = [current ? current.label : role.current.model];
  if (role.effort) parts.push(`${role.effort[0].toUpperCase() + role.effort.slice(1)} effort`);
  if (role.web) parts.push("Web");
  return `<div class="composer-meta"><span class="muted">The room's chat model</span>
    <div style="position:relative;margin-left:auto;min-width:0">
      <button type="button" class="model-btn" aria-haspopup="true" aria-expanded="${S.picker}" ${attr({ act: "togglePicker" })}><span>${esc(parts.join(" · "))}</span>${ic("down", 14, "currentColor", 2.2)}</button>
      ${S.picker ? pickerHtml(role) : ""}</div></div>`;
}

function pickerHtml(role) {
  const models = role.options.map((o) => `<button type="button" class="pill ${o.backend === role.current.backend && o.model === role.current.model ? "on" : ""}" ${attr({ act: "setRole", role: role.key, backend: o.backend, model: o.model })}>${esc(o.label)}</button>`).join("");
  const efforts = role.efforts.length ? `<span class="label">Reasoning effort</span><div class="pills">
      ${[["", "Default"], ...role.efforts.map((e) => [e, e[0].toUpperCase() + e.slice(1)])].map(([value, label]) => `<button type="button" class="pill ${role.effort === value ? "on" : ""}" ${attr({ act: "setEffort", role: role.key, effort: value })}>${esc(label)}</button>`).join("")}</div>
      <span class="hint" style="padding:0">Higher effort thinks longer before each reply: better on hard questions, slower and costlier.</span>` : "";
  return `<div class="picker" role="dialog" aria-label="Chat model">
    <span class="label">Model</span><div class="pills">${models || '<span class="hint" style="padding:0">Connect a provider in Settings.</span>'}</div>
    ${efforts}
    <button type="button" class="link" style="align-self:flex-start;padding-left:0" ${attr({ act: "go", view: "settings" })}>Every role in Settings</button></div>`;
}

function quickChips() {
  return `<div class="chips" style="justify-content:flex-start">
    <button type="button" class="chip" ${attr({ act: "quick", text: "Where are we? What's written and what's next?" })}>Where are we?</button>
  </div>`;
}

const shortDate = (iso) => {
  const day = iso ? new Date(iso) : null;
  return day && !isNaN(day) ? day.toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "";
};

function projectView() {
  const d = S.data;
  if (!d) return "";
  const books = d.isSeries && d.books.length > 1
    ? `<div class="pills">${d.books.map((b) => `<button type="button" class="pill ${b.folder === d.book.folder ? "on" : ""}" ${attr({ act: "switchBook", book: b.folder })}>Book ${b.number} · ${esc(b.title)}</button>`).join("")}</div>` : "";
  const project = S.projects.find((p) => p.id === d.id);
  const chats = (project ? project.chats : []).slice();
  if (S.thread?.items?.length) chats.push({ id: "project", title: "Project chat", updated: S.thread.updated || "" });
  chats.sort((a, b) => String(b.updated).localeCompare(String(a.updated)));
  const recents = chats.map((c) => `<button type="button" class="recent-row" ${attr({ act: "openChat", project: d.id, chat: c.id })}>
      <span class="t">${esc(c.title)}</span><span class="muted">${esc(shortDate(c.updated))}</span></button>`).join("");
  return `<div class="scroll"><div class="project-home">
    <nav class="crumbs" aria-label="Breadcrumb"><button type="button" class="link muted" ${attr({ act: "go", view: "projects" })}>Projects</button><span class="muted" aria-hidden="true">/</span><span>${esc(d.title)}</span></nav>
    <h1 class="project-title">${esc(d.title)}</h1>
    ${books}
    ${S.selection ? `<div class="selected-passage"><b>Selected in ${esc(shortPath(S.selection.path))}</b><blockquote>${esc(S.selection.text)}</blockquote><button type="button" class="link" ${attr({ act: "clearSelection" })}>Clear selection</button></div>` : ""}
    <div class="composer-box">
      <label for="project-composer" class="sr">Start a new chat in ${esc(d.title)}</label>
      <textarea id="project-composer" rows="2" placeholder="${esc(`New chat in ${d.title}`)}" data-model="projectDraft" data-enter="startChat">${esc(S.projectDraft)}</textarea>
      <div class="composer-row">
        <button type="button" class="square" style="margin-left:-4px" aria-label="Attach a file" ${attr({ act: "attach" })}>${ic("clip", 16, "currentColor", 2)}</button>
        <button type="button" class="send" aria-label="Start the chat" ${S.busy ? "disabled" : ""} ${attr({ act: "startChat" })}>${ic("arrow", 18, "currentColor", 2.2)}</button>
      </div>
    </div>
    ${pendingHtml()}
    ${modelLine()}
    <section class="recents" aria-label="Recent chats"><span class="label">Recents</span>
      ${recents || '<p class="muted" style="margin:0;font-size:14px;line-height:1.55">No chats yet. Start one above: plan a scene, ask for a review, or say you\'re stuck.</p>'}</section>
  </div></div>`;
}

/* The project page's right column: one line per part of the book. */
function projectOverview() {
  const d = S.data;
  const job = bookJob(d);
  const written = d.chapters.filter((c) => c.state !== "missing").length;
  const next = d.chapters.find((c) => c.state === "missing");
  const refs = d.reference.reduce((n, r) => n + r.files.length, 0);
  const notes = d.reviews.length + (d.ideas || []).length + d.runs.length;
  const row = (icon, label, meta, action, act) => `<div class="ov-row">${ic(icon, 18, "var(--muted)", 1.8)}
    <span class="ov-label">${esc(label)}</span><span class="muted ov-meta">${esc(meta)}</span>
    ${action ? `<button type="button" class="link" ${attr(act)}>${esc(action)}</button>` : ""}</div>`;
  const building = job && job.state === "running";
  return `<aside class="overview" aria-label="About this project">
    ${row("doc", "Plan", d.isSeries ? `book ${d.book.number}` : "bible, characters, outline", "View", { act: "showProjectFiles" })}
    ${row("clip", "Reference", refs ? `${refs} file${refs === 1 ? "" : "s"}` : "", "Add", { act: "addReference", scope: d.reference[0].scope })}
    ${row("book", "Manuscript", d.chapters.length ? `${written} of ${d.chapters.length} chapters` : "no chapters yet",
      building ? "" : next ? "Build" : written ? "View" : "", building ? {} : next ? { act: "buildAsk", which: "next" } : { act: "showProjectFiles" })}
    ${row("layers", "Notes", notes ? `${notes}` : "", notes ? "View" : "", { act: "showProjectFiles" })}
    <span class="muted ov-foot">${building ? esc(buildStatus(d, job)) + " · " : ""}${esc(d.kind)} · ${fmt(d.words)} words · whole book ${fmtK(d.context.tokens)} of ${fmtK(d.context.limit)} tokens</span>
  </aside>`;
}

function chatView() {
  const c = S.chat;
  if (!c) return "";
  return `<div class="convo">
    <div class="chat-head">
      <button type="button" class="link muted" style="font-size:14px" ${attr({ act: "openProject", project: c.project })}>${esc(S.data ? S.data.title : "")}</button>
      <span class="muted" aria-hidden="true">/</span>
      <b style="font-size:14px;padding:0 6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.title)}</b>
      <button type="button" class="btn ghost small" style="margin-left:auto" aria-pressed="${S.panel}" ${attr({ act: "togglePanel" })}>${ic("panel", 16, "currentColor", 1.8)} Files</button>
    </div>
    <div class="msgs"><div class="msgs-inner">${itemsHtml(c)}</div></div>
    <div class="composer-wrap"><div class="composer-inner">
      ${quickChips()}
      ${pendingHtml()}
      ${composer("composer", "draft", "Talk about your story…", "chat")}
    </div></div>
  </div>`;
}

function fileRow(act, label, meta, extra, right = "") {
  return `<button type="button" class="file-row" ${attr({ act, ...extra })}>${ic("doc", 16, "var(--muted)", 1.8)}
    <span class="grow"><span class="name">${esc(label)}</span>${meta ? `<span class="muted" style="font-size:12px">${esc(meta)}</span>` : ""}</span>${right}</button>`;
}

function filesPanel() {
  const d = S.data;
  const groups = d.groups.map((g) => `<div class="group">
    <div class="group-head"><span class="label">${esc(g.label)}</span><span class="muted" style="margin-left:auto;font-size:12px">${esc(g.status)}</span></div>
    ${g.hint ? `<span class="hint">${esc(g.hint)}</span>` : ""}
    ${g.files.map((f) => fileRow("openFile", f.label, "", { path: f.path })).join("") || '<span class="hint">Nothing yet.</span>'}
  </div>`).join("");
  const refs = d.reference.map((r) => `<div class="group">
    <div class="group-head"><span class="label">${esc(r.label)}</span>
      <button type="button" class="link" style="margin-left:auto;font-size:12px" ${attr({ act: "addReference", scope: r.scope })}>${ic("plus", 12, "currentColor", 2.6)} Add files</button></div>
    <span class="hint">${esc(r.hint)}</span>
    ${r.files.map((f) => `<div style="display:flex;align-items:flex-start;gap:2px">${fileRow("openFile", f.name, `${f.size} · about ${fmt(f.tokens)} tokens per call`, { path: f.path }, f.warn ? "" : "")}
      <button type="button" class="icon-btn" style="height:36px" aria-label="Remove ${esc(f.name)} from reference" ${attr({ act: "removeReference", path: f.path })}>${ic("x", 12, "currentColor", 2.6)}</button></div>
      ${f.warn ? `<span class="hint warn">${esc(f.warn)}</span>` : ""}`).join("") || '<span class="hint">Nothing here yet.</span>'}
  </div>`).join("");
  const job = bookJob(d);
  const running = job && job.state === "running";
  const written = d.chapters.filter((c) => c.state !== "missing").length;
  const next = d.chapters.find((c) => c.state === "missing");
  const status = buildStatus(d, job);
  const chapters = d.chapters.map((c) => {
    const building = running && job.current === c.number;
    const icon = building ? `<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" style="color:var(--accent)"><circle cx="12" cy="12" r="6" fill="currentColor"/></svg>`
      : c.state !== "missing" ? ic("check", 16, "var(--accent)", 2.6) : `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" style="color:var(--faint)" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="7"/></svg>`;
    const meta = building ? "building" : c.words ? fmt(c.words) : "";
    const flag = c.state === "outline changed" ? '<span class="state warn">outline changed</span>' : c.state === "plan changed" ? '<span class="state" title="Built before later changes to the bible or characters">plan changed</span>' : "";
    const extra = c.state === "missing" ? { act: "openEmptyChapter", number: c.number, title: c.title } : { act: "openFile", path: c.path };
    return `<button type="button" class="file-row" style="padding:8px" ${attr(extra)}>${icon}
      <span style="flex:1;min-width:0;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${c.number}. ${esc(c.title || "Untitled")}</span>${flag}
      <span class="muted" style="font-size:12px;font-variant-numeric:tabular-nums">${meta}</span></button>`;
  }).join("");
  return `
    <div class="group" style="gap:6px"><span class="label" style="padding:0 8px">Context</span><div style="padding:0 8px;display:flex;flex-direction:column;gap:6px">${contextHtml()}</div></div>
    ${groups}
    <div style="display:flex;flex-direction:column;gap:14px">${refs}
      <span class="hint">${d.referenceTokens ? `Every chat and build reads about ${fmt(d.referenceTokens)} tokens of reference.` : "Add canon notes, research or a style sample (.md, .txt or .docx)."}</span></div>
    <div class="group" style="gap:6px"><span class="label" style="padding:0 8px">Build${d.isSeries ? ` · Book ${d.book.number}` : ""}</span>
      <div class="build-box"><span style="font-size:14px;line-height:1.45">${esc(status)}</span>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button type="button" class="btn small" ${running || !next ? "disabled" : ""} ${attr({ act: "buildAsk", which: "next" })}>Build next chapter</button>
          <button type="button" class="btn ghost small" ${running || !next ? "disabled" : ""} ${attr({ act: "buildAsk", which: "all" })}>Build all remaining</button></div>
        <div class="muted" style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:12px">${esc(d.defaults)}
          <button type="button" class="link" style="font-size:12px;padding:4px 6px" ${attr({ act: "go", view: "settings" })}>Change</button></div>
      </div></div>
    <div class="group"><span class="label" style="padding:0 8px 4px">Manuscript · ${written} of ${d.chapters.length} · ${fmt(d.words)} words</span>
      ${chapters || '<span class="hint">Chapters appear here once the outline has "## Chapter 1" sections.</span>'}</div>
    <div class="group"><div class="group-head"><span class="label">Notes</span></div>
      ${d.reviews.length || (d.ideas || []).length || d.runs.length || written ? "" : '<span class="hint">Build reports appear here. For a review or ideas, ask in a chat.</span>'}
      ${d.reviews.map((r) => fileRow("openFile", "Review · " + r.name.replace(/^review_|\.md$/g, ""), "", { path: r.path })).join("")}
      ${(d.ideas || []).map((r) => fileRow("openFile", "Ideas · " + r.name.replace(/^ideas_|\.md$/g, ""), "", { path: r.path })).join("")}
      ${d.runs.map((r) => fileRow("openFile", "Build report · " + r.name, "", { path: r.path })).join("")}
      ${written ? `<button type="button" class="link" style="align-self:flex-start" ${attr({ act: "exportBook" })}>Export the whole book</button>` : ""}
    </div>
`;
}

function bookJob(d) {
  return S.job && S.jobKey && S.jobKey.project === d.id && S.job.book === d.book.folder ? S.job : null;
}

function buildStatus(d, job) {
  const written = d.chapters.filter((c) => c.state !== "missing").length;
  const next = d.chapters.find((c) => c.state === "missing");
  if (job && job.state === "running") return `Building chapter ${job.current || job.numbers[job.results.length]}…`;
  if (!d.chapters.length) return "The outline has no chapters yet. Plan a few in the chat first.";
  return `${written} of ${d.chapters.length} chapters written.` + (next ? ` Next up: chapter ${next.number}${next.title ? ", " + next.title : ""}.` : " Every outlined chapter is written.");
}

function contextHtml() {
  const c = S.data?.context;
  if (!c) return "";
  const share = c.tokens / c.limit;
  const long = c.tokens > c.long;
  return `<div class="meter-row"><span class="muted">Every message and build sends the whole book</span><b>${fmtK(c.tokens)} / ${fmtK(c.limit)}</b></div>
    <div class="meter" role="meter" aria-label="Book size against the limit" aria-valuemin="0" aria-valuemax="${c.limit}" aria-valuenow="${c.tokens}"><span class="${long ? "long" : ""}" style="width:${Math.max(1, Math.min(100, Math.round(share * 100)))}%"></span></div>
    ${long ? `<span class="hint warn" style="padding:0">Past about ${fmtK(c.long)} tokens, models read less reliably. Story-so-far notes for finished books help.</span>` : ""}`;
}

/* The right rail beside a chat, like Cowork's: context, build, what changed. */
function rail() {
  const c = S.chat, d = S.data;
  if (!c || !d) return "";
  const job = bookJob(d);
  const running = job && job.state === "running";
  const next = d.chapters.find((x) => x.state === "missing");
  const changed = new Map();
  for (const m of c.items) if (m.kind === "activity" && !m.undone) changed.set(m.file, m);
  const outputs = c.items.filter((m) => m.kind === "review" || m.kind === "ideas" || (m.kind === "result" && m.report));
  const order = ["drafting", "critiquing", "revising"];
  const stages = running ? `<div class="stages light">${order.map((s, i) => `<span class="${i === order.indexOf(job.step) ? "on" : i < order.indexOf(job.step) ? "past" : ""}">${s[0].toUpperCase() + s.slice(1)}</span>`).join("")}</div>` : "";
  const label = (m) => (m.kind === "ideas" ? "Fresh ideas" : m.kind === "review" ? "Second opinion" : "Build report");
  return `<aside class="rail" aria-label="This chat">
    <section class="rail-card"><span class="label">Context</span>${contextHtml()}</section>
    <section class="rail-card"><span class="label">Build${d.isSeries ? ` · Book ${d.book.number}` : ""}</span>
      <span style="font-size:13px;line-height:1.45">${esc(buildStatus(d, job))}</span>${stages}
      ${!running && next ? `<button type="button" class="btn small" style="align-self:flex-start" ${attr({ act: "buildAsk", which: "next" })}>Build next chapter</button>` : ""}</section>
    <section class="rail-card"><div style="display:flex;align-items:baseline"><span class="label">Changes</span><span class="muted" style="margin-left:auto;font-size:12px">${changed.size ? `${changed.size} file${changed.size === 1 ? "" : "s"}` : ""}</span></div>
      ${changed.size ? [...changed.values()].map((m) => fileRow("openFile", shortPath(m.file), m.text, { path: m.file })).join("") : '<span class="hint" style="padding:0">Nothing changed in this chat yet.</span>'}</section>
    ${outputs.length ? `<section class="rail-card"><span class="label">Outputs</span>${outputs.map((m) => fileRow("openFile", label(m), shortPath(m.file || m.report), { path: m.file || m.report })).join("")}</section>` : ""}
    <button type="button" class="link" style="align-self:flex-start" ${attr({ act: "togglePanel" })}>${ic("panel", 14, "currentColor", 1.8)} All project files</button>
  </aside>`;
}

/* A chapter, wide and centred, for reading rather than working on. */
function readerView() {
  const r = S.reader;
  const written = (S.data?.chapters || []).filter((c) => c.state !== "missing");
  const at = written.findIndex((c) => c.path === r.path);
  const step = (c, text) => (c ? `<button type="button" class="btn ghost small" ${attr({ act: "readChapter", path: c.path })}>${text}</button>` : "<span></span>");
  const selected = S.selection?.path === r.path;
  const prev = written[at - 1], next = written[at + 1];
  return `<div class="scroll reader-scroll">
    <div class="reader-head">
      <button type="button" class="btn ghost small" ${attr({ act: "closeReader" })}>${ic("back", 14, "currentColor", 2.2)} Back</button>
      <span class="muted" style="font-size:13px">${esc(S.data.title)} · ${fmt(r.data.words)} words</span>
      <span class="hint" id="passage-hint" style="margin-left:auto;padding:0">${selected ? "Passage selected" : "Highlight a passage to work on it."}</span>
      ${[["discuss", "Discuss"], ["alternatives", "Alternatives"], ["revise", "Revise"]].map(([intent, text]) => `<button type="button" class="btn ghost small" data-passage-action ${selected ? "" : "disabled"} ${attr({ act: "passage", intent })}>${text}</button>`).join("")}
    </div>
    <article class="reader" id="passage-document">${md(r.data.text)}</article>
    ${prev || next ? `<nav class="reader-nav" aria-label="Chapters">${step(prev, prev ? `← Chapter ${prev.number}` : "")}${step(next, next ? `Chapter ${next.number} →` : "")}</nav>` : ""}
  </div>`;
}

function reviewHtml(data) {
  const text = data.text;
  const labels = data.kind === "ideas" ? ["Use the pick", "Not now", "Something else"] : ["Agree", "Disagree", "My own fix"];
  const first = text.search(/^###\s*\d+\./m);
  const intro = first > 0 ? text.slice(0, first) : "";
  const lastPoint = [...text.matchAll(/^###\s*\d+\..*$/gm)].pop();
  let tail = "";
  if (lastPoint) {
    const after = text.slice(lastPoint.index + lastPoint[0].length);
    const t = after.search(/^##\s/m);
    tail = t >= 0 ? after.slice(t) : "";
  }
  const points = data.points.map((p) => `<div class="point">
    <b style="font-size:15px">${p.number}. ${esc(p.title)}</b>
    <div class="body doc" style="font-size:14px">${md(p.body)}</div>
    ${p.call ? `<span class="call">Your call: ${esc(p.call)}</span>` : `<div style="display:flex;gap:6px;flex-wrap:wrap">
      <button type="button" class="btn small" ${attr({ act: "reviewCall", number: p.number, call: "agree" })}>${labels[0]}</button>
      <button type="button" class="btn ghost small" ${attr({ act: "reviewCall", number: p.number, call: "disagree" })}>${labels[1]}</button>
      <button type="button" class="btn ghost small" ${attr({ act: "reviewCall", number: p.number, call: "own" })}>${labels[2]}</button></div>`}
  </div>`).join("");
  return `<div class="doc">${md(intro)}</div><div style="display:flex;flex-direction:column;gap:12px">${points}</div><div class="doc">${md(tail)}</div>`;
}

function docPanel() {
  const doc = S.doc;
  if (doc.empty) {
    return `<p style="margin:0;font-size:14px;line-height:1.55" class="muted">Chapter ${doc.empty}${doc.title ? ": " + esc(doc.title) : ""} isn't written yet.</p>
      <button type="button" class="btn" style="align-self:flex-start" ${attr({ act: "buildAsk", which: doc.empty })}>Build this chapter</button>`;
  }
  const data = doc.data;
  if (doc.editing) {
    return `<label for="doc-editor" class="sr">Edit ${esc(doc.path)}</label>
      <textarea id="doc-editor" class="editor" data-model="doc.text">${esc(doc.text)}</textarea>
      <div style="display:flex;gap:8px"><button type="button" class="btn" ${attr({ act: "saveDoc" })}>Save</button><button type="button" class="btn ghost" ${attr({ act: "cancelEdit" })}>Cancel</button></div>
      <span class="hint" style="padding:0">Your edits win: the chat re-reads every file before it changes anything.</span>`;
  }
  const isChapter = /manuscript\/chapter_\d+\.md$/.test(doc.path);
  const number = isChapter ? Number(doc.path.match(/chapter_(\d+)/)[1]) : null;
  const actions = [
    data.editable ? `<button type="button" class="btn ghost small" ${attr({ act: "editDoc" })}>${ic("pen", 14, "currentColor", 2)} Edit</button>` : "",
    isChapter ? `<button type="button" class="btn ghost small" ${attr({ act: "readChapter", path: doc.path })}>${ic("read", 14, "currentColor", 2)} Read</button>` : "",
    isChapter ? `<button type="button" class="btn ghost small" ${attr({ act: "buildAsk", which: number })}>Rebuild</button>` : "",
  ].join("");
  const body = data.points ? reviewHtml(data) : `<div class="doc" id="passage-document">${md(data.text)}</div>`;
  const selected = S.selection?.path === doc.path;
  return `${actions ? `<div style="display:flex;gap:8px;flex-wrap:wrap">${actions}</div>` : ""}
    ${!data.points ? `<div class="passage-actions"><span class="hint" id="passage-hint">${selected ? "Passage selected" : "Highlight a passage to work on it together."}</span>
      <div>${[["discuss", "Discuss"], ["alternatives", "Suggest alternatives"], ...(data.editable ? [["revise", "Revise"]] : [])].map(([intent, label]) => `<button type="button" class="btn ghost small" data-passage-action ${selected ? "" : "disabled"} ${attr({ act: "passage", intent })}>${label}</button>`).join("")}</div></div>` : ""}${body}
    ${isChapter ? '<span class="hint" style="padding:0">To change this chapter, describe what you want in the chat ("make the ending colder"), or edit it yourself. Earlier versions are kept.</span>' : ""}`;
}

function panel() {
  if (!S.data) return "";
  let title = "Project files", desc = S.data.title, body;
  if (S.doc) {
    if (S.doc.empty) { title = `Chapter ${S.doc.empty}`; desc = "Not written yet"; }
    else { title = S.doc.path.split("/").pop(); desc = S.doc.path.split("/").slice(0, -1).join("/") + (S.doc.data.words ? ` · ${fmt(S.doc.data.words)} words` : ""); }
    body = docPanel();
  } else {
    body = filesPanel();
  }
  return `<aside class="panel" aria-label="Project files">
    <div class="panel-head">
      ${S.doc ? `<button type="button" class="icon-btn" aria-label="All files" ${attr({ act: "showFiles" })}>${ic("back", 18, "currentColor", 2)}</button>`
        : S.view === "project" ? `<button type="button" class="icon-btn" aria-label="Back to the project" ${attr({ act: "hideProjectFiles" })}>${ic("back", 18, "currentColor", 2)}</button>` : ""}
      <div class="titles"><b>${esc(title)}</b><span class="muted" style="font-size:12px">${esc(desc)}</span></div>
      ${S.view === "chat" ? `<button type="button" class="icon-btn" aria-label="Close files" ${attr({ act: "closePanel" })}>${ic("x", 18, "currentColor", 2)}</button>` : ""}
    </div>
    <div class="panel-body">${body}</div>
  </aside>`;
}

function settingsView() {
  const st = S.settings;
  if (!st) return `<div class="scroll"><div class="page narrow"><h1 class="big">Settings</h1><p class="lead">Loading…</p></div></div>`;
  const providers = st.providers.map((p) => {
    const msg = S.providerMsg[p.key];
    const status = p.connected ? "Connected" : "Not connected";
    return `<div class="card provider">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><b style="font-size:16px">${esc(p.name)}</b>
        ${p.recommended ? '<span class="badge">Recommended</span>' : ""}<span class="status-pill ${p.connected ? "ok" : ""}" style="margin-left:auto">${status}</span></div>
      <span class="muted" style="font-size:14px;line-height:1.5">${esc(p.blurb)}</span>
      <label class="sr" for="provider-${esc(p.key)}">${p.kind === "address" ? "Server address" : "API key"} for ${esc(p.name)}</label>
      <div class="key-row">
        <input id="provider-${esc(p.key)}" type="${p.kind === "address" ? "text" : "password"}" autocomplete="off"
          placeholder="${esc(p.connected ? (p.kind === "address" ? p.address : `Saved key ${p.masked}`) : (p.kind === "address" ? "http://localhost:11434/v1" : "Paste your API key"))}"
          data-model="providerInput.${esc(p.key)}" value="${esc(S.providerInput[p.key] || "")}">
        <button type="button" class="btn ghost" ${attr({ act: "connect", backend: p.key })}>${p.connected ? "Disconnect" : p.kind === "address" ? "Connect" : "Check key"}</button>
      </div>
      ${msg ? `<span style="font-size:13px" class="${msg.ok ? "" : "warn"}">${esc(msg.text)}</span>` : ""}
      ${p.env ? `<span class="hint" style="padding:0">Saved on this computer in .env as ${esc(p.env)}.</span>` : ""}
    </div>`;
  }).join("");
  const roles = st.roles.map((r) => `<div class="role">
    <div><b style="font-size:15px">${esc(r.label)}</b> <span class="muted" style="font-size:13px">${esc(r.blurb)}</span></div>
    <div class="pills">${r.options.map((o) => `<button type="button" class="pill ${o.backend === r.current.backend && o.model === r.current.model ? "on" : ""}" ${attr({ act: "setRole", role: r.key, backend: o.backend, model: o.model })}>${esc(o.label)} · ${esc(o.provider)}</button>`).join("")}</div>
    ${!r.options.length ? '<span class="warn" style="font-size:12px">Connect a provider above to choose a model.</span>' : !r.available ? `<span class="warn" style="font-size:12px">Currently set to ${esc(r.current.model)} on ${esc(r.current.backend)}, which isn't connected. Pick one above.</span>` : ""}
  </div>`).join("");
  const pill = (field, value, label, on) => `<button type="button" class="pill ${on ? "on" : ""}" ${attr({ act: "setPress", field, value })}>${label}</button>`;
  return `<div class="scroll"><div class="page narrow">
    <h1 class="big">Settings</h1>
    <p class="lead">Connect at least one model provider. Your keys stay on this computer.</p>
    <div style="display:flex;flex-direction:column;gap:12px">${providers}</div>
    <h2 class="sub" style="font-size:18px">Who does what</h2>
    <p class="lead" style="font-size:14px;margin-top:-14px">Every call sends the whole book, so pick models with large context windows (about 1M tokens).</p>
    <div class="card" style="padding:4px 18px">${roles}</div>
    <h2 class="sub" style="font-size:18px">Building chapters</h2>
    <div class="card" style="padding:4px 18px">
      <div class="role"><div><b style="font-size:15px">Revision rounds</b> <span class="muted" style="font-size:13px">Critique-and-revise passes after each draft. One is usually best.</span></div>
        <div class="pills">${[0, 1, 2].map((n) => pill("revision_rounds", n, n === 0 ? "Draft only" : n === 1 ? "1 round" : "2 rounds", st.press.revision_rounds === n)).join("")}</div></div>
      <div class="role"><div><b style="font-size:15px">Chapter length</b> <span class="muted" style="font-size:13px">Used when the outline doesn't say.</span></div>
        <div class="pills">${[2000, 3000, 4000].map((n) => pill("default_chapter_words", n, `About ${fmt(n)} words`, st.press.default_chapter_words === n)).join("")}</div></div>
    </div>
  </div></div>`;
}

const HELP = [
  { kind: "Getting started", title: "Start with whatever you have", body: "A single line, a character, a scene you can picture. You don't need a plan, and \"not sure yet\" is a fine answer: some things only show up on the page.", tryLabel: "Start a book", home: "" },
  { kind: "Shape", title: "The whole story in eight lines", body: "Fill in these openers (Kenn Adams's Story Spine, made famous by Pixar). If you can, you have a beginning, a middle that builds, and an ending. Leave lines blank and discover them later.", example: "Once upon a time…\nEvery day…\nBut one day…\nBecause of that… (three times)\nUntil finally…\nAnd ever since then…", tryLabel: "Fill it in with me", home: "Help me fill in the eight-line story spine for my idea: " },
  { kind: "Shape", title: "Six questions worth answering, eventually", body: "Who do we follow and what do they want? What is in the way? What happens if they fail? Do they change? How should it feel? Roughly where does it end up?", tryLabel: "Work through them", home: "Ask me the six questions, a couple at a time, about my idea: " },
  { kind: "Shape", title: "Aim the trouble at the flaw", body: "If a character believes something that isn't true, or has a habit that holds them back, aim the obstacles at it. Then the events that drive the plot are the ones that make them change, or refuse to.", example: "Mara thinks she's safer alone, so the storm strands her with the one person she can't stand.", tryLabel: "Connect plot and character", ask: "Does my plot test what my main character gets wrong?" },
  { kind: "Momentum", title: "\"But\" and \"therefore\", not \"and then\"", body: "Each event should happen because of the last one, or despite it. \"This happens, and then that\" is a list; \"this, therefore that, but then this\" is a story.", example: "She finds the boat, therefore she searches the cove, but the rope was cut.", tryLabel: "Check my outline", ask: "Check my outline for any \"and then\" links between chapters." },
  { kind: "Momentum", title: "Promises, progress, payoff", body: "Early on, a book makes promises: a mystery, a romance, a rivalry, a danger. Readers keep turning pages while those promises move forward, and finish happy when they pay off. List them under \"The threads\" at the top of your outline so none get lost.", tryLabel: "What have I promised?", ask: "Which promises has my book made so far, and where do they pay off? Add any missing ones to the threads list." },
  { kind: "Momentum", title: "Wins come with a catch", body: "When a character tries something, the most interesting results are \"yes, but\" (they get it, and it costs them) or \"no, and\" (they fail, and things get worse). Too many clean wins and the tension drains away.", example: "Yes, she keeps the lamp lit, but the storm wrecks the radio.\nNo, Jonah won't talk, and now his father knows she's asking.", tryLabel: "Make my middle harder", ask: "Where could my middle use a \"yes, but\" or a \"no, and\"?" },
  { kind: "Chapters", title: "What changed?", body: "The one useful test for a chapter: what is different at the end than at the start? A new fact, a changed relationship, a decision, a loss, a belief that cracks. If nothing changed, it is probably part of its neighbour.", tryLabel: "Test my chapters", ask: "Does every chapter in my outline change something?" },
  { kind: "Purpose", title: "Everything matters to someone", body: "For any character, place or event, ask what it changes, reveals or makes harder for someone we care about. Small answers count, and \"it's fun\" counts too. A subplot earns its place by running into the main story. Ask it when rereading, not while drafting.", tryLabel: "Find loose threads", ask: "Is anything in my plan not pulling its weight yet?" },
  { kind: "On the page", title: "Make it concrete", body: "A named thing, a specific sound, an exact gesture beats a general feeling. Let characters talk instead of summarising them. Let us inside the viewpoint character: what they notice, think and decide. Show the moment and trust the reader; don't label the emotion afterwards.", example: "\"Her coffee had gone cold an hour ago\" carries more than \"she was tired\"." },
  { kind: "Working with the room", title: "Getting the most from your co-writer", body: "Talk naturally and change your mind freely; the files keep up. Edit any file yourself whenever you like. Ask the chat for a second opinion before building (a new chat keeps it separate), then build two or three chapters one at a time before building the rest. Nothing is lost: every old version is kept." },
];

function helpView() {
  const cards = HELP.map((c, i) => {
    const canTry = c.home !== undefined || c.ask;
    return `<div class="card help-card"><span class="label" style="color:var(--accent)">${esc(c.kind)}</span>
      <b style="font-size:17px">${esc(c.title)}</b><span style="font-size:14px;line-height:1.55">${esc(c.body)}</span>
      ${c.example ? `<pre>${esc(c.example)}</pre>` : ""}
      ${canTry ? `<button type="button" class="link" style="align-self:flex-start;margin-top:auto" ${attr({ act: "helpTry", index: i })}>${esc(c.tryLabel)} ${ic("arrow", 14, "currentColor", 2.2)}</button>` : ""}</div>`;
  }).join("");
  return `<div class="scroll"><div class="page">
    <h1 class="big">Writing help</h1>
    <p class="lead">Lenses, not rules. Use what helps and ignore the rest; your own story always wins. Your co-writer knows all of these too, so just ask.</p>
    <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(300px,1fr))">${cards}</div>
  </div></div>`;
}

function tray() {
  const job = S.job;
  if (!job || S.trayHidden) return "";
  if (job.state === "running") {
    const order = ["drafting", "critiquing", "revising"];
    const at = order.indexOf(job.step);
    const stages = order.map((s, i) => `<span class="${i === at ? "on" : i < at ? "past" : ""}">${s[0].toUpperCase() + s.slice(1)}</span>`).join("");
    const done = job.results.length;
    return `<div class="tray" role="status">
      <div style="display:flex;align-items:baseline;gap:8px"><b style="font-size:14px">Building chapter ${job.current || job.numbers[done]}</b><span style="margin-left:auto;font-size:12px;color:var(--tray-muted)">${done + 1} of ${job.numbers.length}</span></div>
      <div class="stages">${stages}</div>
      <div style="display:flex;gap:8px;align-items:center"><button type="button" ${job.stopping ? "disabled" : ""} ${attr({ act: "stopBuild" })}>${job.stopping ? "Stopping after this chapter" : "Stop after this chapter"}</button>
        <button type="button" class="plain" ${attr({ act: "hideTray" })}>Hide</button></div>
    </div>`;
  }
  const title = job.state === "failed" ? "The build stopped" : job.state === "stopped" ? "Stopped" : "Build finished";
  const detail = job.state === "failed" ? job.error : `${job.results.length} chapter(s) · ${job.usage || ""}`;
  const report = job.report || "";
  return `<div class="tray" role="status"><b style="font-size:14px">${esc(title)}</b><span style="font-size:13px;line-height:1.45;color:var(--tray-muted)">${esc(detail)}</span>
    <div style="display:flex;gap:8px">${report && job.state !== "failed" ? `<button type="button" ${attr({ act: "openFile", path: report })}>View report</button>` : ""}<button type="button" class="plain" ${attr({ act: "hideTray" })}>Dismiss</button></div></div>`;
}

function modal() {
  if (!S.modal) return "";
  const m = S.modal;
  return `<div class="modal-back"><div class="modal" role="dialog" aria-modal="true" aria-label="${esc(m.title)}">
    <b style="font-size:17px">${esc(m.title)}</b><span class="muted" style="font-size:14px;line-height:1.5">${esc(m.detail)}</span>
    <span class="muted" style="font-size:13px;line-height:1.5">Each chapter is drafted, then critiqued by a second model and revised (${esc(S.data ? S.data.defaults : "")}), then saved. You can keep planning while it runs.</span>
    <div style="display:flex;gap:8px;justify-content:flex-end"><button type="button" class="btn ghost" ${attr({ act: "closeModal" })}>Cancel</button><button type="button" class="btn" ${attr({ act: "buildGo" })}>Build</button></div>
  </div></div>`;
}

function render() {
  const openChanges = [...document.querySelectorAll("details[data-change-id][open]")].map(el => el.dataset.changeId);
  const keep = {};
  const openGroups = [...document.querySelectorAll("details[data-group-id][open]")].map(el => el.dataset.groupId);
  for (const sel of [".panel", ".rail", ".scroll", ".side-scroll", ".msgs"]) {
    const el = document.querySelector(sel);
    if (el) keep[sel] = el.scrollTop;
  }
  const active = document.activeElement && document.activeElement.id;
  const caret = active && document.activeElement.selectionStart;
  const views = { home: homeView, projects: projectsView, chats: chatsView, project: projectView, chat: chatView, settings: settingsView, help: helpView };
  const app = document.getElementById("app");
  app.className = "wr-app" + (S.drawer ? " drawer-open" : "");
  const reading = S.reader && S.data && (S.view === "project" || S.view === "chat");
  const side = reading ? ""
    : S.view === "project" ? (S.doc || S.files ? panel() : projectOverview())
    : S.view === "chat" ? (S.panel ? panel() : rail()) : "";
  app.innerHTML = mobileBar() + sidebar()
    + `<main class="main">${reading ? readerView() : (views[S.view] || homeView)()}</main>`
    + side
    + tray() + modal()
    + (S.toast ? `<div class="toast" role="alert"><span style="flex:1">${esc(S.toast)}</span><button type="button" aria-label="Dismiss" ${attr({ act: "closeToast" })}>✕</button></div>` : "")
    + (S.creating ? `<div class="overlay-busy"><div class="thinking" style="font-size:16px"><span class="dots"><span></span><span></span><span></span></span> Setting up your project and reading your idea. This can take a minute…</div></div>` : "");
  for (const [sel, top] of Object.entries(keep)) {
    const el = document.querySelector(sel);
    if (el && sel !== ".msgs") el.scrollTop = top;
  }
  if (active) {
    const el = document.getElementById(active);
    if (el) { el.focus(); if (caret != null && el.setSelectionRange) el.setSelectionRange(caret, caret); }
  }
  for (const ta of document.querySelectorAll(".bar textarea")) autosize(ta);
  for (const el of document.querySelectorAll("details[data-change-id]")) el.open = openChanges.includes(el.dataset.changeId);
  for (const el of document.querySelectorAll("details[data-group-id]")) el.open = openGroups.includes(el.dataset.groupId);
}

function autosize(ta) {
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
}

/* ---------- events ---------- */

function setPath(path, value) {
  const keys = path.split(".");
  let obj = S;
  while (keys.length > 1) obj = obj[keys.shift()];
  obj[keys[0]] = value;
}

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-act]");
  if (!el || el.disabled) return;
  const fn = ACT[el.dataset.act];
  if (!fn) return;
  e.preventDefault();
  if (S.drawer && el.dataset.act !== "toggleDrawer") S.drawer = false;
  if (S.picker && !["togglePicker", "setRole", "setEffort"].includes(el.dataset.act)) S.picker = false;
  Promise.resolve(fn(el.dataset, el)).catch(fail);
});

document.addEventListener("input", (e) => {
  const el = e.target;
  if (el.dataset && el.dataset.model) {
    setPath(el.dataset.model, el.value);
    if (el.closest(".bar")) autosize(el);
  }
});

document.addEventListener("change", (e) => {
  if (e.target.matches("[data-attachment-scope]")) S.pending[Number(e.target.dataset.attachmentScope)].scope = e.target.value;
  if (e.target.matches("[data-explore]")) S.explore = e.target.checked;
});

document.addEventListener("selectionchange", () => {
  const selection = window.getSelection(), doc = document.getElementById("passage-document");
  const source = S.reader || S.doc;
  if (!doc || !selection || selection.isCollapsed || !doc.contains(selection.anchorNode) || !doc.contains(selection.focusNode) || !source?.data) return;
  const text = selection.toString().trim();
  if (!text) return;
  S.selection = { path: source.path, version: source.data.version, text };
  for (const button of document.querySelectorAll("[data-passage-action]")) button.disabled = false;
  document.getElementById("passage-hint").textContent = "Passage selected";
});

document.addEventListener("keydown", (e) => {
  const el = e.target;
  if (e.key === "Escape") {
    if (S.modal) { S.modal = null; render(); }
    else if (S.picker) { S.picker = false; render(); }
    else if (S.drawer) { S.drawer = false; render(); }
    else if (S.home.menu) { S.home.menu = false; render(); }
    else if (S.reader) { S.reader = null; render(); }
    return;
  }
  if (e.key === "Enter" && !e.shiftKey && el.dataset && el.dataset.enter && !e.isComposing) {
    e.preventDefault();
    if (S.busy && el.dataset.enter === "send") return;
    Promise.resolve(ACT[el.dataset.enter]({ where: el.dataset.where })).catch(fail);
  }
});

(async function start() {
  applyTheme();
  try {
    await refreshState();
    S.settings = await get("/api/settings");
    if (!S.providers.length) S.view = "settings";
  } catch (e) { S.toast = e.message; }
  render();
  focus("home-composer");
})();
