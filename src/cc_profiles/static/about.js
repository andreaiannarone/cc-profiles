// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Andrea Iannarone
// About, update check, what's new, export, import and plugins, installing Claude Code.

// ---------- about Claude Code ----------
async function openAbout() {
  const bg = document.createElement("div"); bg.className = "drawer-bg";
  const dr = document.createElement("aside"); dr.className = "drawer"; dr.setAttribute("role", "dialog"); dr.setAttribute("aria-modal", "true"); dr.setAttribute("aria-label", "About Claude Code");
  const loading = `<div class="empty">${LOADER} Collecting version, accounts and profile contents…</div>`;
  dr.innerHTML = `<div class="dh"><h2>Claude Code on this computer</h2><button class="btn small" id="ab-update" disabled>Update</button><button class="btn small" id="ab-reload">Refresh</button><button class="btn small" id="ab-close">Close</button></div>
    <div class="db" id="ab-body">${loading}</div>`;
  const close = () => { bg.remove(); dr.remove(); document.removeEventListener("keydown", onKey); $("#about-btn").focus(); };
  const onKey = e => { if (e.key === "Escape") close(); };
  bg.onclick = close; document.addEventListener("keydown", onKey);
  document.body.append(bg, dr);
  $("#ab-close", dr).onclick = close; $("#ab-close", dr).focus();
  syncUpdateButton(dr);
  const load = async () => {
    $("#ab-body", dr).innerHTML = loading;
    try { renderAbout(dr, await api("/api/about")); } catch (e) { $("#ab-body", dr).innerHTML = `<div class="empty">Error: ${esc(e.message)}</div>`; }
  };
  $("#ab-reload", dr).onclick = load; load();
}
function renderAbout(dr, a) {
  const kv = o => `<dl class="kv">${Object.entries(o).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${/disk usage/i.test(k) ? esc(size(v)) : esc(v)}</dd>`).join("")}</dl>`;
  const list = items => items.length ? `<div class="tags">${items.map(x => `<span class="tag">${esc(x)}</span>`).join("")}</div>` : `<span class="hint">none</span>`;
  $("#ab-body", dr).innerHTML = `
    <div class="card"><h3>Claude Code</h3>${kv(a.claude)}
      ${S.cc && !S.cc.installed && S.cc.supported ? `<div style="margin-top:10px"><button class="btn primary" data-install>Install Claude Code…</button></div>` : ""}</div>
    ${a.profiles.map(p => `<div class="card"><h3>${esc(p.label)} ${badge(p.id)} <code class="hint" style="font-weight:400">${esc(p.command)}</code></h3>
      ${kv(p.account)}
      <h4>Usage</h4>${kv(p.usage)}
      <h4>Contents</h4>
      ${Object.entries(p.contents).map(([k, v]) => `<div class="citem"><span class="k">${esc(k)} (${v.length})</span>${list(v)}</div>`).join("")}
      <div class="citem"><span class="k">CLAUDE.md</span><span>${p.claude_md ? "present" : `<span class="hint">not present</span>`}</span></div>
      ${p.shared.length ? `<div class="citem"><span class="k">Shared with ${esc(a.profiles[0].label)}</span>${list(p.shared)}</div>` : ""}
      <h4>Files</h4>${kv({ "Folder": p.dir, "Config": p.config })}
    </div>`).join("")}
    <div class="card"><h3>cc-profiles</h3>${kv(a.app)}
      <div class="upd"><button class="btn small" id="upd-check">Check for updates</button><span class="hint" id="upd-status">Asks PyPI for the latest version.</span></div>
      <label class="check upd"><input type="checkbox" id="upd-auto"${S.upd?.enabled === false ? "" : " checked"}> <span>Check for updates automatically, once a day<br><span class="hint">PyPI sees your IP address; updating still needs your click</span></span></label>
      <div class="upd" id="mac-app" hidden></div>
      ${S.term?.choices?.length > 1 ? `<label class="upd"><span>Open projects in</span><select id="term-pick">${S.term.choices.map(c => `<option${c === S.term.terminal ? " selected" : ""}>${esc(c)}</option>`).join("")}</select></label>` : ""}
      <div class="upd"><button class="btn small" id="ab-news">What's new</button><button class="btn small" id="ab-report">Report a problem…</button></div></div>
    <p class="hint" style="margin:0;text-align:center">© 2026 <a href="https://andreaiannarone.com" target="_blank" rel="noopener">Andrea Iannarone</a></p>`;
  $("#upd-check", dr).onclick = () => checkUpdate(dr);
  if (S.upd?.newer) showUpdate(dr, S.upd);
  $("#upd-auto", dr).onchange = async e => {
    const box = /** @type {HTMLInputElement} */ (e.target);
    try { await run(() => api("/api/update/auto", { enabled: box.checked })); } catch { box.checked = !box.checked; return; }
    loadUpdateStatus();
  };
  $("#ab-news", dr).onclick = () => showWhatsNew();
  $("#ab-report", dr).onclick = () => reportProblem(a);
  loadMacApp(dr);
  const tp = $("#term-pick", dr);
  if (tp) tp.onchange = async () => {
    try { await run(() => api("/api/terminal", { terminal: tp.value })); S.term = await api("/api/terminal"); } catch { tp.value = S.term.terminal; return; }
    if (S.tab === "projects") renderProjects();
  };
}
// The Mac app (macOS only): added or brought up to date with a click, like an update
async function loadMacApp(dr, m) {
  const box = $("#mac-app", dr);
  if (!box) return;
  try { m = m || await api("/api/macapp"); } catch { return; }
  if (!m.supported) return;
  const how = `<a href="https://cc-profiles.andreaia.com/mac-app.html" target="_blank" rel="noopener">How it works</a>`;
  const text = {
    missing: `cc-profiles in a window of its own, in Applications, with its icon in the Dock. ${how}`,
    outdated: `<code>${esc(m.path)}</code> is from another version${m.port && m.port !== Number(location.port) ? ` or uses port ${esc(m.port)}` : ""}. ${how}`,
    current: `<span class="okmark">✓ Mac app in <code>${esc(m.path)}</code></span>: open it from Spotlight, Launchpad or Applications. ${how}`,
    foreign: `<code>${esc(m.path)}</code> exists and was not created by cc-profiles: move it away to add the Mac app. ${how}`,
  }[m.state] || "";
  const label = { missing: "Add Mac app", outdated: "Update Mac app" }[m.state];
  box.innerHTML = `${label ? `<button class="btn small" id="mac-app-add">${label}</button>` : ""}<span class="hint">${text}</span>`;
  box.hidden = false;
  const btn = $("#mac-app-add", box);
  if (btn) btn.onclick = async () => {
    btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> ${label}`;
    let r;
    try { r = await run(() => api("/api/macapp", {})); } catch { btn.disabled = false; btn.textContent = label; return; }
    loadMacApp(dr, r);
  };
}
async function checkUpdate(dr) {
  const st = $("#upd-status", dr), btn = $("#upd-check", dr);
  btn.disabled = true; st.innerHTML = `<span class="spinner"></span> Checking PyPI…`;
  let u;
  try { u = await api("/api/update"); } catch (e) { st.textContent = e.message; btn.disabled = false; return; }
  btn.disabled = false;
  S.upd = { ...(S.upd || {}), ...u }; markUpdate();
  if (!u.newer) { st.innerHTML = `<span class="okmark">✓ cc-profiles ${esc(u.current)} is the latest version.</span>`; return; }
  showUpdate(dr, u);
}
function showUpdate(dr, u) {
  const st = $("#upd-status", dr);
  if (!st) return;  // the panel is still loading
  // the version is told here; the Update button is the one at the top, next to Refresh
  st.innerHTML = `Version <b>${esc(u.latest)}</b> is available (you have ${esc(u.current)}).<br>
    ${u.can_update ? `Click <b>Update</b> at the top.` : `Update it by hand with <code>${esc(u.manual || u.command || "")}</code>, then restart cc-profiles.`}
    <a href="https://cc-profiles.andreaia.com/changelog.html" target="_blank" rel="noopener">What's new</a>`;
}
async function runUpdate(u, dr) {
  if (!(await confirmBox(`Update to ${u.latest}?`,
      `Runs <code>${esc(u.command)}</code>, then restarts cc-profiles: this page reloads by itself. Your profiles, backups and settings are not touched.`, "Update"))) return;
  const st = $("#upd-status", dr);
  if (st) st.innerHTML = `<span class="spinner"></span> Updating to ${esc(u.latest)}…`;
  let r;
  try { r = await api("/api/update", {}); } catch (e) { toast(e.message, "", true); if (st) st.textContent = e.message; return; }
  if (r.retry && st) {  // just released: PyPI's download index is not there yet
    st.innerHTML = `${esc(r.message)} Then click <b>Update</b> at the top again.
      ${r.details ? `<details style="margin-top:6px"><summary>Details</summary><pre class="log">${esc(r.details)}</pre></details>` : ""}`;
    return;
  }
  if (r.message) toast(r.message);
  if (st && !r.restarting) st.textContent = r.message || "";
  if (!r.restarting) return;
  const bg = document.createElement("div"); bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-label="Restarting"><h2>${LOADER} Restarting cc-profiles…</h2><div class="hint">The page reloads as soon as the new version answers.</div></div>`;
  document.body.append(bg);
  await new Promise(res => setTimeout(res, 1500));
  for (let i = 0; i < 60; i++) {  // up to a minute
    try { if ((await fetch("/", { cache: "no-store" })).ok) return location.reload(); } catch {}
    await new Promise(res => setTimeout(res, 1000));
  }
  bg.querySelector(".hint").textContent = "cc-profiles did not come back: start it again with cc-profiles open.";
}

// ---------- automatic update check ----------
// The server asks PyPI at most once a day (unless turned off in About); the page only reads its last answer.
async function loadUpdateStatus() {
  try { S.upd = await api("/api/update/auto"); } catch { return; }
  markUpdate();
  if (!S.upd.newer) return;
  let told = null;
  try { told = localStorage.getItem("cc-profiles.update-notified"); localStorage.setItem("cc-profiles.update-notified", S.upd.latest); } catch {}
  if (told !== S.upd.latest) toast(`cc-profiles ${S.upd.latest} is available`, "Open About (ⓘ) to update");
}
// In the About panel's header, next to Refresh: off and not clickable until a new version is out
function syncUpdateButton(dr) {
  const b = $("#ab-update", dr), u = S.upd, on = !!u?.newer;
  if (!b) return;
  b.disabled = !on;
  b.classList.toggle("update-on", on);
  b.textContent = "Update";
  b.title = !on ? "cc-profiles is up to date" : u.can_update ? `Update to ${u.latest}: runs ${u.command}` : "Shows how to update this copy";
  b.onclick = !on ? null : () => {
    if (u.can_update) return runUpdate(u, dr);
    showUpdate(dr, u);
    $("#upd-status", dr)?.scrollIntoView({ block: "center" });
  };
}
function markUpdate() {
  const ab = $("#ab-update");
  if (ab) syncUpdateButton(ab.closest(".drawer"));
  const b = $("#about-btn"), on = !!S.upd?.newer;
  b.classList.toggle("has-update", on);
  b.title = b.ariaLabel = on ? `About Claude Code on this computer. cc-profiles ${S.upd.latest} is available` : "About Claude Code on this computer";
}

// ---------- what's new, report a problem ----------
// The release notes ship with the app (static/whatsnew.json, from CHANGELOG.md). The page remembers
// the last version it showed: after an update it shows what changed since then, once.
const SEEN_VERSION = "cc-profiles.seen-version";
const vnums = v => ((v || "").match(/^\d+(?:\.\d+)*/)?.[0] || "0").split(".").map(Number);
const isNewer = (a, b) => {
  const x = vnums(a), y = vnums(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  return false;
};
// the few bits of Markdown the changelog uses: `code`, **bold**, *italics*, [links](https://…)
const inlineMd = t => esc(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
  .replace(/(^|[^*\w])\*([^*\s][^*]*)\*(?!\*)/g, "$1<i>$2</i>")
  .replace(/\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
async function checkWhatsNew() {
  let d;
  try { d = await api("/api/whatsnew"); } catch { return; }
  let seen = null;
  try { seen = localStorage.getItem(SEEN_VERSION); localStorage.setItem(SEEN_VERSION, d.version); } catch {}
  if (seen && isNewer(d.version, seen)) showWhatsNew(d, seen);
}
async function showWhatsNew(d, since) {
  if (!d) { try { d = await api("/api/whatsnew"); } catch { return; } }
  const list = (since ? d.releases.filter(r => isNewer(r.version, since)) : d.releases).slice(0, since ? 5 : 3);
  const body = list.length ? list.map(r => `<h3 class="wn-v">${esc(r.version)} <span class="hint">${esc(r.date)}</span></h3>
      ${r.sections.map(sec => `<h4 class="wn-s">${esc(sec.title)}</h4><ul class="wn">${sec.items.map(i => `<li>${inlineMd(i)}</li>`).join("")}</ul>`).join("")}`).join("")
    : `<div class="hint">No release notes in this copy of cc-profiles.</div>`;
  await modal({ title: since ? `Updated to cc-profiles ${d.version}` : "What's new in cc-profiles",
    sub: since ? `What changed since ${esc(since)}.` : `You have version ${esc(d.version)}.`,
    body: `<div class="wn-body">${body}</div><p class="hint wn-more"><a href="https://cc-profiles.andreaia.com/changelog.html" target="_blank" rel="noopener">Every release</a></p>`,
    cancel: "Close" });
}
function reportProblem(a) {
  // GitHub's bug report form, with the versions filled in. Nothing is sent: the browser opens the page.
  const sys = a.app.System || "", os = /^macOS/.test(sys) ? "macOS" : /WSL/.test(sys) ? "Windows (WSL)" : /^Linux/.test(sys) ? "Linux" : "Other";
  const q = new URLSearchParams({ template: "bug_report.yml", version: a.app["cc-profiles"], claude: a.claude.Version, os,
    system: `${sys} · Python ${a.app.Python}` });
  window.open("https://github.com/andreaiannarone/cc-profiles/issues/new?" + q, "_blank", "noopener");
}

// ---------- export, import and plugins ----------
async function exportProfile(id) {
  const p = S.profiles.find(x => x.id === id);
  const res = await modal({ title: `Export ${p.label}`,
    sub: `Saves the profile as a .zip, to import it on another computer with <b>Import profile…</b>. Login credentials are never included: the imported profile logs in on its own.`,
    body: `<div class="form"><label class="check"><input type="checkbox" id="ex-proj"> also include conversations, prompt history and file snapshots</label>
      <div class="hint">Without them the export holds settings, <code>CLAUDE.md</code>, skills, agents, commands, plugins, MCP servers and the general memory.</div></div>`,
    actions: [{ label: "Export", kind: "primary", value: "ok" }] });
  if (!res) return;
  const projects = $("#ex-proj", res.el).checked ? 1 : 0;
  try {
    const name = await download(`/api/profiles/export?id=${encodeURIComponent(id)}&projects=${projects}`, `cc-profiles-${id}.zip`);
    toast(`Exported ${p.label}`, name);
  } catch (e) { toast(e.message, "", true); }
}
// A download needs the token header, so it is fetched and saved from a Blob, not linked.
async function download(path, fallback) {
  const r = await fetch(path, { headers: { "X-Token": TOKEN } });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  const name = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || fallback;
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
  return name;
}
async function importProfile(dropped) {
  const resP = modal({ title: "Import profile",
    sub: "Creates a new profile from a .zip exported by cc-profiles. It is not logged in: run its command and log in with /login.",
    body: `<div class="form"><label class="f">Exported file<input type="file" id="im-file" accept=".zip,application/zip"></label>
      <label class="f">Name<input class="text" id="im-label" placeholder="e.g. Work"></label>
      <label class="f">Id (folder and command)<input class="text" id="im-id" placeholder="e.g. work"></label>
      <div class="hint" id="im-cmd"></div></div>`,
    actions: [{ label: "Import profile", kind: "primary", value: "ok" }] });
  const F = $("#im-file"), L = $("#im-label"), I = $("#im-id");
  const upd = () => { $("#im-cmd").innerHTML = I.value ? `Command <code>claude-${esc(I.value)}</code> · folder <code>~/.claude-${esc(I.value)}</code>` : ""; };
  F.onchange = () => {  // cc-profiles-<id>-<date>.zip: suggest the id and a name
    const m = (F.files[0]?.name || "").match(/^cc-profiles-(.+?)-\d{4}-\d{2}-\d{2}/);
    if (m && !I.value) { I.value = m[1]; L.value = m[1].replace(/-/g, " ").replace(/^./, c => c.toUpperCase()); upd(); }
  };
  I.oninput = upd;
  if (dropped) {  // a .zip dropped on the page or on the Mac app's icon
    const dt = new DataTransfer(); dt.items.add(dropped); F.files = dt.files; F.onchange(new Event("change"));
  }
  const res = await resP;
  if (!res) return;
  const file = $("#im-file", res.el).files[0];
  if (!file) return toast("Pick the .zip of an exported profile", "", true);
  const q = `label=${encodeURIComponent($("#im-label", res.el).value)}&id=${encodeURIComponent($("#im-id", res.el).value)}`;
  try {
    await run(async () => {
      const r = await fetch("/api/profiles/import?" + q, { method: "POST", body: file, headers: { "X-Token": TOKEN, "Content-Type": "application/zip" } });
      const j = await r.json().catch(() => ({ error: "Invalid response from the server" }));
      if (!r.ok) throw new Error(j.error || r.statusText);
      return j;
    });
  } catch { return; }
  await refresh(); loadSharing();
}

async function loadPlugins(pid) {
  const x = S.plug;
  x.profile = pid || x.profile || S.profiles[0]?.id;
  x.data = null; x.error = null; renderPlugins();
  try { x.data = await api("/api/plugins?profile=" + x.profile); }
  catch (e) { x.error = e.message === "Not found" ? "This page is newer than the running cc-profiles server. Stop it and start it again." : e.message; }
  renderPlugins();
}
// What a mod does, read from its source by the server: a description, not a guarantee.
function modLines(m) {
  const does = [...m.features, ...m.commands.map(c => "/" + c)];
  return `<div class="m">${does.length ? `Adds: ${esc(does.join(", "))}` : "Adds nothing on screen"}${m.events.length ? ` · hooks: ${esc(m.events.map(e => e.label).join(", "))}` : ""}</div>
    ${m.reach.length ? `<div class="m reach">Can reach: ${esc(m.reach.join(", "))}</div>` : ""}`;
}
function renderPlugins() {
  if (S.tab !== "plugins") return;
  const x = S.plug, d = x.data;
  const seg = `<div class="seg" style="max-width:360px">${S.profiles.map(p => `<button data-plugprof="${p.id}" class="${x.profile === p.id ? "on" : ""}">${esc(p.label)}</button>`).join("")}</div>`;
  const head = `<div class="toolbar">${seg}<span class="hint">Install and remove plugins with <code>/plugin</code> in Claude Code; here you see them and turn them on or off.</span></div>`;
  if (x.error) $("#main").innerHTML = `${head}<div class="empty">${esc(x.error)}</div>`;
  else if (!d) $("#main").innerHTML = `${head}<div class="empty">${LOADER} Loading plugins…</div>`;
  else $("#main").innerHTML = `${head}
    <div class="ext-head" style="margin-top:0"><h2>Plugins</h2><span class="hint"><code>${esc(d.dir)}</code> · ${plural(d.plugins.length, "plugin", "plugins")}${d.shared ? ` · <span class="shared-note">${esc(d.shared)}: a change here applies there too</span>` : ""}</span></div>
    <div class="table">${d.plugins.map((g, i) => `<div class="prow plug-row"><div class="txt">
        <div class="t">${esc(g.plugin)}${g.mod ? ` <span class="badge b-none" data-mod title="A plugin of function hooks: it changes Claude Code itself">mod</span>` : ""} <span class="badge b-none">${esc(g.marketplace || "no marketplace")}</span>${g.version ? ` <span class="badge b-none">${esc(g.version)}</span>` : ""}${g.is_installed ? "" : ` <span class="badge b-warn">not installed</span>`}</div>
        <div class="m">${g.installed ? `installed ${esc(g.installed)}` : ""}${g.scopes.length ? ` · ${esc(g.scopes.join(", "))}` : ""}${g.projects.length ? ` · ${g.projects.map(esc).join(", ")}` : ""}${g.path ? ` · <code>${esc(g.path)}</code>` : ""}</div>
        ${g.mod ? modLines(g.mod) : ""}
        <div class="m">${g.enabled == null ? "not set in the settings: Claude Code's default" : `${g.enabled ? "enabled" : "disabled"} in ${g.source === "local" ? "settings.local.json" : "settings.json"}`}</div></div>
      <div class="acts">${g.is_installed && g.scopes.includes("user") && S.profiles.length > 1 ? `<button class="btn small" data-plugcopy="${i}">Copy to…</button>` : ""}
      <label class="switch" title="${g.enabled ? "Enabled" : "Disabled"}"><input type="checkbox" data-plugsw="${i}" ${g.enabled ? "checked" : ""} aria-label="Enable ${esc(g.name)}"><span></span></label></div></div>`).join("")
      || `<div class="empty">No plugins in this profile. Install them with <code>/plugin</code> in Claude Code.</div>`}</div>
    <div class="ext-head"><h2>Marketplaces</h2><span class="hint">where Claude Code finds plugins to install</span></div>
    <div class="mlist">${d.marketplaces.map(m => `<div><b>${esc(m.name)}</b> · <code>${esc(m.source)}</code>${m.updated ? ` · updated ${esc(m.updated)}` : ""}</div>`).join("") || `<div>None.</div>`}</div>`;
  document.querySelectorAll("[data-plugprof]").forEach(b => b.onclick = () => loadPlugins(b.dataset.plugprof));
  document.querySelectorAll("[data-plugcopy]").forEach(b => b.onclick = async () => {
    const g = d.plugins[b.dataset.plugcopy];
    const to = await pickProfile(`Copy ${g.plugin} to…`, `Its files, its marketplace and its entry in <code>installed_plugins.json</code> are copied as <code>/plugin</code> would install them, and it is enabled there from the next Claude Code session. The files that change go to the backup first.${g.mod?.reach.length ? ` <span class="reach">This mod can reach: ${esc(g.mod.reach.join(", "))}.</span>` : ""}`, x.profile, "Copy");
    if (!to) return;
    try { await run(() => api("/api/plugins/copy", { profile: x.profile, plugin: g.name, to })); } catch {}
    loadPlugins();
  });
  document.querySelectorAll("[data-plugsw]").forEach(cb => cb.onchange = async () => {
    const g = d.plugins[cb.dataset.plugsw], on = cb.checked;
    if (!(await confirmBox(`${on ? "Enable" : "Disable"} ${g.plugin}?`,
        `Saved in <code>${g.source === "local" ? "settings.local.json" : "settings.json"}</code> as <code>enabledPlugins</code>${d.shared ? `; plugins are ${esc(d.shared)}` : ""}. It applies from the next Claude Code session; the file goes to the backup first.`, on ? "Enable" : "Disable"))) { cb.checked = !on; return; }
    try { await run(() => api("/api/plugins/enable", { profile: x.profile, plugin: g.name, enabled: on })); } catch {}
    loadPlugins();
  });
}

// ---------- installing Claude Code ----------
async function loadClaudeStatus() {
  try { S.cc = await api("/api/claude/status"); } catch { return; }
  const c = S.cc, el = $("#notice");
  if (c.job?.running) el.innerHTML = `<div class="notice">${LOADER}<div class="txt"><b>Installing Claude Code…</b><span>${esc(c.job.method)}</span></div><button class="btn" data-install-log>Show</button></div>`;
  else if (!c.installed) el.innerHTML = `<div class="notice"><div class="txt"><b>Claude Code is not installed on this computer</b>
      <span>Without it profiles cannot be used: login, sessions and health checks do not work.</span></div>
      ${c.supported ? `<button class="btn primary" data-install>Install Claude Code…</button>` : `<span class="hint">Installing from here is supported on macOS and Linux.</span>`}</div>`;
  else if (!c.in_path) el.innerHTML = `<div class="notice"><div class="txt"><b>Claude Code is installed, but your terminal cannot find it</b>
      <span>It is in <code>${esc(c.path)}</code>. Add this line to your shell startup file (e.g. <code>~/.zshrc</code>) and open a new terminal: <code>export PATH="$HOME/.local/bin:$PATH"</code></span></div></div>`;
  else el.innerHTML = "";
}
async function installClaude() {
  const c = S.cc || await api("/api/claude/status");
  const first = c.methods.find(m => m.available);
  if (!first) return toast("No install method is available on this computer.", "", true);
  const res = await modal({ title: "Install Claude Code",
    sub: `Official commands from the Claude Code documentation. You need an internet connection; after installing, log in with a Pro, Max, Team or Enterprise account.`,
    body: c.methods.map(m => `<label class="method ${m.available ? "" : "off"}">
        <span class="top"><input type="radio" name="im" value="${m.id}" ${m.id === first.id ? "checked" : ""} ${m.available ? "" : "disabled"}> ${esc(m.label)}</span>
        <code>${esc(m.command)}</code>
        <span class="hint">${esc(m.available ? m.note : m.why)}</span></label>`).join(""),
    actions: [{ label: "Install", kind: "primary", value: "ok" }] });
  if (!res) return;
  const method = res.el.querySelector('input[name="im"]:checked').value;
  try { await run(() => api("/api/claude/install", { method })); } catch { return; }
  showInstallLog();
}
async function showInstallLog() {
  const bg = document.createElement("div"); bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal" role="dialog" aria-modal="true" style="width:min(720px,100%)"><h2 id="il-title"><span class="spinner"></span> Installing…</h2>
    <div class="body"><pre class="log" id="il-log" aria-live="polite"></pre><div id="il-result"></div></div>
    <div class="foot"><button class="btn" id="il-close">Close</button></div></div>`;
  document.body.append(bg);
  let stop = false;
  const close = () => { stop = true; bg.remove(); loadClaudeStatus(); };
  $("#il-close", bg).onclick = close;
  while (!stop) {
    const c = await api("/api/claude/status").catch(() => null);
    if (!c) break;
    const log = $("#il-log", bg); log.textContent = c.job.lines.join("\n"); log.scrollTop = log.scrollHeight;
    if (!c.job.running) {
      S.cc = c;
      const ok = c.job.code === 0 && c.installed;
      $("#il-title", bg).textContent = ok ? "Claude Code installed" : "Installation failed";
      $("#il-result", bg).innerHTML = ok
        ? `<div class="okmark">✓ Version ${esc(c.version)} in <code>${esc(c.path)}</code>.</div>
           <div class="hint" style="margin-top:6px">Open a new terminal and run <code>claude</code>: it asks you to log in the first time.${c.in_path ? "" : " Your terminal cannot find it yet: add <code>export PATH=\"$HOME/.local/bin:$PATH\"</code> to your shell startup file."}</div>`
        : `<div class="danger-box">The command ended with code ${esc(c.job.code)}${c.job.code === 0 ? ", but Claude Code does not show up as installed" : ""}. Check the log above; the official guide covers the common errors: code.claude.com/docs/en/troubleshoot-install</div>`;
      break;
    }
    await new Promise(r => setTimeout(r, 1000));
  }
  refresh();
}
