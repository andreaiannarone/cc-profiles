// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Andrea Iannarone
// The page's state, helpers, modal and data loading. Loaded first: the other files use these.

const S = { tab: "projects", profiles: [], projects: [], filter: "issues", q: "",
            mem: { profile: null, project: null, all: false, q: "", list: null, file: null, projects: [] },
            conv: { profile: null, project: null, projects: [], list: null, session: null, view: null, q: "" },
            health: null, plug: { profile: null, data: null, error: null }, ext: { profile: null, skills: null, agents: null, agent: null, mcp: null, conn: null, error: null, skill: null, content: "", files: [], q: "" } };

// ---------- helpers ----------
/** @type {(s: string, el?: ParentNode) => any} */
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const label = id => id === "shared" ? "All profiles" : (S.profiles.find(p => p.id === id)?.label || id);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
// While a panel loads: the logo's two mascots hopping in turn (class spinner too, for code that waits for it to go)
const LOADER = `<span class="spinner loader">${$("header .logo").outerHTML}</span>`;
function badge(id) {
  if (!id) return `<span class="badge b-none">unassigned</span>`;
  if (id === "shared") return `<span class="badge b-shared">All profiles</span>`;
  const i = S.profiles.findIndex(p => p.id === id);
  return `<span class="badge ${i < 0 ? "b-none" : "b-p" + (i % 6)}">${esc(label(id))}</span>`;
}
const basename = p => (p || "").replace(/\/+$/, "").split("/").pop();

async function api(path, body) {
  const r = await fetch(path, { method: body ? "POST" : "GET",
    headers: { "X-Token": TOKEN, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({ error: "Invalid response from the server" }));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
function toast(msg, sub, err) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.setAttribute("role", err ? "alert" : "status");
  t.innerHTML = esc(msg) + (sub ? `<small>${esc(sub)}</small>` : "");
  $("#toasts").append(t);
  setTimeout(() => t.remove(), err ? 9000 : 6000);
}
async function run(fn) {
  try { const r = await fn(); if (r?.message) toast(r.message, r.backup ? "backup: " + r.backup : ""); return r; }
  catch (e) { toast(e.message, "", true); throw e; }
}

// ---------- modal ----------
function modal({ title, sub, body = "", actions = [], cancel = "Cancel" }) {
  return new Promise(resolve => {
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <h2>${esc(title)}</h2>${sub ? `<div class="hint">${sub}</div>` : ""}
      <div class="body">${body}</div>
      <div class="foot">${actions.map((a, i) => a.label ? `<button class="btn ${a.kind || ""}" data-i="${i}">${esc(a.label)}</button>` : "").join("")}
        <button class="btn" data-close>${esc(cancel)}</button></div></div>`;
    const close = v => { bg.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
    const onKey = e => { if (e.key === "Escape") close(null); };
    document.addEventListener("keydown", onKey);
    bg.addEventListener("click", e => {
      if (e.target === bg || /** @type {Element} */ (e.target).hasAttribute("data-close")) return close(null);
      const i = e.target.closest("[data-i]")?.dataset.i;
      if (i !== undefined) close({ action: actions[i].value, el: bg });
      const pick = e.target.closest("[data-pick]");
      if (pick) { const inp = $("input.text", bg); if (inp) { inp.value = pick.dataset.pick; inp.focus(); } }
    });
    document.body.append(bg);
    ($("input, select", bg) || $("[data-i]", bg))?.focus();
  });
}
async function confirmBox(title, sub, okLabel = "Confirm", kind = "primary") {
  const r = await modal({ title, sub, actions: [{ label: okLabel, kind, value: true }] });
  return !!r;
}

// ---------- data ----------
async function loadProfiles() {
  S.profiles = await api("/api/profiles");
  $("#profiles").innerHTML = S.profiles.map(p => `
    <div class="pcard">
      <div class="top"><span class="name">${esc(p.label)}</span>${badge(p.id)}
        ${p.active ? `<span class="live" title="A conversation was written in the last 2 minutes">session open</span>` : ""}</div>
      <div class="acct${p.email ? "" : " none"}">${p.email ? `Signed in as <b>${esc(p.email)}</b>` : "Not signed in"}</div>${p.github ? `<div class="acct">GitHub as <b>${esc(p.github)}</b></div>` : ""}
      <div class="meta"><code>${esc(p.command)}</code> · <code>${esc(p.dir)}</code></div>
      <div class="nums"><div><b>${p.conv}</b><span>conversations</span></div>
        <div><b>${p.projects}</b><span>projects</span></div><div><b>${p.memories}</b><span>memories</span></div></div>
    </div>`).join("") + `<button class="pcard add" data-newprofile>+ New profile</button>`;
}
async function loadProjects() {
  S.projects = await api("/api/projects");
  const n = S.projects.filter(r => r.issues.length).length;
  const c = $("#cnt-projects"); c.hidden = !n; c.textContent = n; syncNav();
}
async function refresh() { await Promise.all([loadProfiles(), loadProjects()]); render(); }
// Folders are renamed and sessions run outside the page: when the tab or the window comes back,
// read the profiles and the projects again, and redraw only what changed. Never under a dialog.
let syncedAt = Date.now(), syncing = false;
async function syncOnReturn() {
  if (document.hidden || syncing || Date.now() - syncedAt < 2000 || $(".modal-bg")) return;
  syncing = true;
  try {
    const before = JSON.stringify(S.projects);
    await Promise.all([loadProfiles(), loadProjects()]);
    if ($(".modal-bg")) return;
    const changed = JSON.stringify(S.projects) !== before;
    if (S.tab === "projects" && changed) {
      const q = document.activeElement?.id === "q" ? $("#q").selectionStart : null;
      renderProjects();
      if (q !== null) { $("#q").focus(); $("#q").setSelectionRange(q, q); }
    }
    if (S.tab === "health" && S.health) await loadHealth(false, true);
    else if (changed) S.health = null;  // checked again when the tab opens
  } catch {} finally { syncing = false; syncedAt = Date.now(); }
}
document.addEventListener("visibilitychange", syncOnReturn);
window.addEventListener("focus", syncOnReturn);
