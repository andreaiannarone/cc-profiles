// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Andrea Iannarone
// Profiles and sharing, a GitHub account per profile, profile by folder.

// ---------- profiles and sharing ----------
// After a change the tab is redrawn in place: the loader only shows the first time, and the page
// keeps its scroll position, as in Settings.
async function loadSharing() {
  if (!S.sharing) renderSharing();
  const [sharing, shell, github] = await Promise.all([api("/api/sharing"), api("/api/shell").catch(() => null),
    api("/api/github").catch(() => null)]);
  S.sharing = sharing; S.shell = shell; S.github = github;
  const y = window.scrollY;
  renderSharing();
  window.scrollTo(0, y);
}
function renderSharing() {
  if (S.tab !== "profiles") return;
  if (!S.sharing) { $("#main").innerHTML = `<div class="empty">${LOADER}</div>`; return; }
  const src = S.profiles[0];
  $("#main").innerHTML = `
    <div class="toolbar"><span class="hint">A shared item is a link to the folder of <b>${esc(src.label)}</b>, the source profile: install or edit it once and every profile gets it.</span>
      <button class="btn" data-pimport style="margin-left:auto">Import profile…</button>
      <button class="btn" id="ptemplates">Templates…</button>
      <button class="btn primary" data-newprofile>New profile</button></div>
    <div class="section-title">Your profiles</div>
    <div class="table">${S.profiles.map(p => `<div class="prow"><div class="txt">
        <div class="t">${esc(p.label)} ${badge(p.id)} ${p.primary ? `<span class="badge b-none">source</span>` : ""}
          ${p.active ? `<span class="live" style="margin-left:0">session open</span>` : ""}</div>
        <div class="acct${p.email ? "" : " none"}">${p.email ? `Signed in as <b>${esc(p.email)}</b>` : "Not signed in"}</div>${p.github ? `<div class="acct">GitHub as <b>${esc(p.github)}</b></div>` : ""}
        <div class="m"><code>${esc(p.command)}</code> · <code>${esc(p.dir)}</code> · ${plural(p.conv, "conversation", "conversations")} · ${plural(p.projects, "project", "projects")} · ${plural(p.memories, "memory", "memories")}</div></div>
      <div class="acts"><button class="btn small" data-pext="${p.id}" data-ext="skills">Skills</button><button class="btn small" data-pext="${p.id}" data-ext="mcp">MCP</button><button class="btn small" data-pexport="${p.id}">Export…</button><button class="btn small" data-pedit="${p.id}">Edit</button>
        ${p.primary ? "" : `<button class="btn small danger" data-pdel="${p.id}">Delete</button>`}</div></div>`).join("")}</div>
    <div class="section-title">Sharing</div>
    <div class="health">${S.sharing.map(p => `<div class="hcard"><h2>${esc(p.label)} <span class="hint" style="font-weight:400">shares from ${esc(p.source)}</span></h2>
      ${p.items.map(it => `<div class="share">
        <div class="txt"><b>${esc(it.item)}</b><div>${esc(it.desc)}${it.shared ? "" : it.own ? " · own copy" : " · not present"}
          ${it.only_own.length ? `<br><span class="issue">only here: ${it.only_own.slice(0, 6).map(esc).join(", ")}${it.only_own.length > 6 ? "…" : ""}</span>` : ""}</div></div>
        <label class="switch" title="${it.shared ? "Shared" : "Separate"}"><input type="checkbox" data-share="${esc(it.item)}" data-prof="${p.id}" ${it.shared ? "checked" : ""} aria-label="Share ${esc(it.item)}"><span></span></label>
      </div>`).join("")}</div>`).join("") || `<div class="empty">There is only one profile: create a second one to share.</div>`}</div>
    ${byFolderHtml()}
    ${githubHtml()}`;
  $("#ptemplates").onclick = manageTemplates;
  wireByFolder();
  wireGithub();
  document.querySelectorAll("[data-share]").forEach(cb => cb.onchange = async () => {
    const p = S.sharing.find(x => x.id === cb.dataset.prof), it = p.items.find(x => x.item === cb.dataset.share);
    const on = cb.checked;
    const sub = on
      ? `${esc(p.label)} will use <code>${esc(it.item)}</code> from ${esc(p.source)}.` + (it.own ? ` Its current copy goes to the backup${it.only_own.length ? `, including <b>${plural(it.only_own.length, "item", "items")} ${esc(p.source)} does not have</b>: ${it.only_own.slice(0, 8).map(esc).join(", ")}` : ""}.` : "")
      : `${esc(p.label)} gets its own copy of <code>${esc(it.item)}</code>: from then on, changes no longer flow between profiles.`;
    let plan = null;
    try { plan = await api(`/api/sharing/preview?profile=${encodeURIComponent(p.id)}&item=${encodeURIComponent(it.item)}&shared=${on ? 1 : 0}`); } catch {}
    if (!(await confirmBox(on ? "Share?" : "Separate?", sub + (plan ? planDetails(plan.items, esc(p.source)) : ""), on ? "Share" : "Separate"))) { cb.checked = !on; return; }
    try { await run(() => api("/api/sharing", { profile: p.id, item: it.item, shared: on })); } catch {}
    loadSharing();
  });
}
const SHARE_NEW = ["skills", "plugins", "agents", "commands", "CLAUDE.md", "settings.json"];

// ---------- a GitHub account per profile ----------
// Every profile has its own GitHub CLI folder; the menu picks which signed-in account is active there.
// The table is a draft, as in Settings: changes are marked and saved together with Save changes.
S.ghDraft = {};
const ghVal = (p, k) => (S.ghDraft[p.id] && k in S.ghDraft[p.id]) ? S.ghDraft[p.id][k] : (p[k] || "");
const ghChanged = p => ["user", "name", "email"].some(k => ghVal(p, k) !== (p[k] || ""));
function githubHtml() {
  const g = S.github;
  if (!g) return "";
  const src = esc(S.profiles[0].label);
  const account = p => {
    if (p.shared) return `<span class="hint">the account of ${src}: its <code>settings.json</code> is shared</span>`;
    if (!p.set_up) return `<button class="btn small" data-ghsetup="${p.id}">Give it its own folder</button>`;
    const cur = ghVal(p, "user");
    const users = [...new Set([...(p.user ? [p.user] : []), ...g.accounts])];
    return `<select data-ghacc="${p.id}" aria-label="GitHub account of ${esc(p.label)}">
      ${cur ? "" : `<option value="" selected disabled>not signed in</option>`}
      ${users.map(u => `<option value="${esc(u)}" ${u === cur ? "selected" : ""}>${esc(u)}</option>`).join("")}
      <option value="+">Another account…</option></select>`;
  };
  const rows = g.profiles.map(p => `<tr data-ghrow="${p.id}" class="${ghChanged(p) ? "changed" : ""}"><td>${esc(p.label)}</td><td>${account(p)}</td>
      <td class="path"><code>${esc(p.dir)}</code>${p.default ? ` <span class="hint">(also your terminal)</span>` : ""}</td>
      <td><div class="ghid"><input class="text" data-ghname="${p.id}" value="${esc(ghVal(p, "name"))}" placeholder="Name: your git config" aria-label="Commit name in ${esc(p.label)}">
        <input class="text" data-ghemail="${p.id}" value="${esc(ghVal(p, "email"))}" placeholder="Email" title="For example ${esc(ghVal(p, "user") || "you")}@users.noreply.github.com" aria-label="Commit email in ${esc(p.label)}"></div></td></tr>`).join("");
  return `<h2 class="section-title">GitHub</h2>
    <div class="ext-head" style="margin-top:0"><span class="hint">Each profile has its own GitHub CLI folder: <code>gh</code> and <code>git push</code> in its Claude Code sessions use the account picked here, and its commits carry the name and email written here (empty: your git config). Tokens stay in the system keychain.</span></div>
    ${g.gh ? "" : `<div class="notice"><div class="txt"><b>The GitHub CLI is not installed</b><span>Install it with <code>brew install gh</code>, then sign in with <code>gh auth login</code>.</span></div></div>`}
    ${g.git_uses_gh === false ? `<div class="notice"><div class="txt"><b>git push ignores the profile's account</b><span>git does not ask <code>gh</code> for GitHub passwords. Run <code>gh auth setup-git</code> once in a terminal.</span></div>
      <button class="btn small" data-copy="gh auth setup-git">Copy command</button></div>` : ""}
    <div class="table ghtable"><table><thead><tr><th>Profile</th><th>GitHub account</th><th>Folder</th><th>Commits by</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="savebar" id="gh-bar" hidden><span id="gh-count"></span><span class="grow"></span><button class="btn" id="gh-cancel">Cancel</button><button class="btn primary" id="gh-save">Save changes</button></div>
    ${githubAccountsHtml()}`;
}
function ghMark() {
  const g = S.github; if (!g) return;
  const changed = g.profiles.filter(ghChanged);
  document.querySelectorAll("[data-ghrow]").forEach(r => r.classList.toggle("changed", changed.some(p => p.id === r.dataset.ghrow)));
  const bar = $("#gh-bar"); if (!bar) return;
  bar.hidden = !changed.length;
  $("#gh-count").textContent = plural(changed.length, "profile changed", "profiles changed");
}
window.addEventListener("beforeunload", e => { if (S.github?.profiles.some(ghChanged)) { e.preventDefault(); e.returnValue = ""; } });
async function copyCommand(text, btn) {
  try { await navigator.clipboard.writeText(text); btn.textContent = "Copied"; setTimeout(() => { btn.textContent = "Copy command"; }, 1500); }
  catch { toast("Copy it by hand: " + text, "", true); }
}
async function githubPost(path, body) {
  try { await run(() => api(path, body)); } catch {}
  await refresh(); loadSharing();
}
// The accounts signed in on this computer, whichever folder they are in
function githubAccountsHtml() {
  const g = S.github, list = g.account_list || [];
  const rows = list.map(a => `<tr><td><b>${esc(a.user)}</b></td>
      <td>${a.used_by.length ? a.used_by.map(esc).join(", ") : `<span class="hint">no profile</span>`}</td>
      <td class="path">${a.folders.map(f => `<code>${esc(f)}</code>`).join(" · ")}</td>
      <td class="acts">${a.insecure ? `<span class="badge b-warn" title="Its token is written in hosts.yml, not in the keychain: other profiles cannot use it">token in hosts.yml</span>`
        : a.used_by.length ? `<button class="btn small" disabled title="In use: connect another account to ${esc(a.used_by.join(", "))} first">Remove…</button>`
        : `<button class="btn small danger" data-ghremove="${esc(a.user)}">Remove…</button>`}</td></tr>`).join("");
  return `<div class="ext-head"><h2>Accounts</h2><span class="hint">Every GitHub account signed in on this computer. A new one is added in <code>${esc(g.accounts_dir)}</code>, so no profile changes: connect it to a profile above.</span>
      <button class="btn" id="gh-addacc">Add account…</button></div>
    <div class="table ghtable">${rows ? `<table><thead><tr><th>Account</th><th>Used by</th><th>Folders</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
      : `<div class="empty">No GitHub account is signed in yet: add one.</div>`}</div>`;
}
function signInAnother(p) {
  return signInModal(`Another GitHub account for ${p.label}`,
    `Sign in once in a terminal: the account becomes the active one in <code>${esc(p.dir)}</code>, and every other profile can pick it from its menu too.${p.default ? " Your terminal uses it as well." : ""}`,
    (p.default ? "" : `GH_CONFIG_DIR=${p.dir} `) + "gh auth login");
}
async function signInModal(title, sub, cmd) {
  const resP = modal({ title, sub,
    body: `<div class="form"><div class="cmdrow"><pre class="log" id="gh-cmd">${esc(cmd)}</pre><button class="btn small" id="gh-copy">Copy command</button></div>
      <div class="hint">The token goes to the system keychain; cc-profiles only reads the user's name.</div></div>`,
    actions: [{ label: "I signed in, refresh", kind: "primary", value: "ok" }], cancel: "Close" });
  $("#gh-copy").onclick = e => copyCommand(cmd, e.target);
  await resP;
  await refresh(); loadSharing();
}
function wireGithub() {
  const g = S.github;
  if (!g) return;
  const prof = id => g.profiles.find(x => x.id === id);
  document.querySelectorAll("[data-copy]").forEach(b => b.onclick = () => copyCommand(b.dataset.copy, b));
  document.querySelectorAll("[data-ghsetup]").forEach(b => b.onclick = () => githubPost("/api/github/setup", { profile: b.dataset.ghsetup }));
  $("#gh-addacc")?.addEventListener("click", () => signInModal("Add a GitHub account",
    `Sign in once in a terminal, in <code>${esc(g.accounts_dir)}</code>: no profile changes account. Then connect it to the profiles you want.`,
    `GH_CONFIG_DIR=${g.accounts_dir} gh auth login`));
  document.querySelectorAll("[data-ghremove]").forEach(b => b.onclick = async () => {
    const a = g.account_list.find(x => x.user === b.dataset.ghremove);
    const logout = `gh auth logout --hostname github.com --user ${a.user}`;
    if (!(await confirmBox(`Remove ${a.user}?`, `It is taken off ${a.folders.map(f => `<code>${esc(f)}</code>`).join(", ")}; those files go to the backup first. Its token stays in the system keychain: to delete it too, run <code>${esc(logout)}</code> afterwards.`, "Remove", "danger"))) return;
    githubPost("/api/github/remove", { user: a.user });
  });
  const draft = (id, k, v) => { (S.ghDraft[id] = S.ghDraft[id] || {})[k] = v; ghMark(); };
  document.querySelectorAll("[data-ghacc]").forEach(sel => sel.onchange = () => {
    const p = prof(sel.dataset.ghacc);
    if (sel.value === "+") { sel.value = ghVal(p, "user"); return signInAnother(p); }
    draft(p.id, "user", sel.value);
  });
  document.querySelectorAll("[data-ghname]").forEach(i => i.oninput = () => draft(i.dataset.ghname, "name", i.value.trim()));
  document.querySelectorAll("[data-ghemail]").forEach(i => i.oninput = () => draft(i.dataset.ghemail, "email", i.value.trim()));
  document.querySelectorAll("[data-ghname], [data-ghemail]").forEach(i => i.onkeydown = e => { if (e.key === "Enter" && !$("#gh-bar").hidden) $("#gh-save").click(); });
  $("#gh-cancel").onclick = () => { S.ghDraft = {}; const y = window.scrollY; renderSharing(); window.scrollTo(0, y); };
  $("#gh-save").onclick = async () => {
    const changes = g.profiles.filter(ghChanged).map(p => {
      const c = { profile: p.id };
      if (ghVal(p, "user") !== (p.user || "")) c.user = ghVal(p, "user");
      if (ghVal(p, "name") !== (p.name || "") || ghVal(p, "email") !== (p.email || "")) { c.name = ghVal(p, "name"); c.email = ghVal(p, "email"); }
      return c;
    });
    try { await run(() => api("/api/github/save", { changes })); } catch { return; }
    S.ghDraft = {};
    await refresh(); loadSharing();
  };
  ghMark();
}

// ---------- profile by folder ----------
function byFolderHtml() {
  const x = S.shell;
  if (!x) return "";
  const on = x.installed.length > 0, files = l => l.map(f => `<code>${esc(f)}</code>`).join(", ");
  const rules = x.rules.map(r => `<li><code>${esc(r.text)}</code> <span class="hint">${r.exact ? "this folder only" : "any path containing it"}</span>
      <span aria-hidden="true">→</span> ${r.profile === "shared" ? `<span class="badge b-shared">All profiles</span> <span class="hint">default profile</span>` : badge(r.profile)}</li>`).join("");
  const state = on ? `On: the line is in ${files(x.installed)}.`
    : x.targets.length ? `Off. Turning it on adds one line to ${files(x.targets.map(t => t.file))}.`
    : `Off. Your shell (${esc(x.shell || "unknown")}) is not zsh or bash: add the output of <code>cc-profiles shell-init bash</code> to its startup file by hand.`;
  return `<h2 class="section-title">Profile by folder</h2>
    <div class="sec"><div class="b">
      <div class="hint">The rules below link folders to profiles; the Projects tab uses the same ones. When this is on, typing <code>claude</code> in a terminal starts Claude Code in the profile of the folder you are in, and folders without a rule keep the default profile.</div>
      <div class="share bf-switch">
        <div class="txt"><span class="bf-t">Pick the profile from the folder when I run claude</span><div>${state}${x.on_path ? "" : ` <span class="issue">cc-profiles was not found in <code>PATH</code>: the line needs it in your terminal.</span>`}</div></div>
        <label class="switch" title="${on ? "On" : "Off"}"><input type="checkbox" id="bf-switch" ${on ? "checked" : ""} aria-label="Pick the profile from the folder when I run claude"><span></span></label>
      </div>
      <div class="share"><div class="txt"><span class="bf-t">Rules: folder → profile</span>
        ${rules ? `<ul class="bf-rules">${rules}</ul>` : `<div>No rules yet: add one from the Projects tab with Assign….</div>`}</div></div>
      <div class="share"><div class="txt"><span class="bf-t">Try a folder</span>
        <div class="bf-try">${folderField("bf-path", "", "~/code/work/api", "Folder to try", 'list="bf-list"')}
          <datalist id="bf-list">${x.projects.map(p => `<option value="${esc(p.path)}">`).join("")}</datalist>
          <button class="btn" id="bf-go">Try</button></div>
        <div id="bf-result" role="status"></div></div></div>
    </div></div>`;
}
function wireByFolder() {
  const sw = $("#bf-switch");
  if (!sw) return;
  sw.onchange = async () => {
    const x = S.shell, on = sw.checked;
    const sub = on
      ? `Adds one line at the end of ${plural(x.targets.length, "file", "files")}.` + x.targets.map(t => `<div style="margin-top:8px">To <code>${esc(t.file)}</code>:</div><pre class="log" style="margin-top:4px">${esc(t.line)}</pre>`).join("")
        + `<div style="margin-top:8px">The file is backed up first. Open a new terminal afterwards. A <code>CLAUDE_CONFIG_DIR</code> you set yourself still wins.</div>`
      : `Removes the line ending in <code># cc-profiles: profile by folder</code> from ${x.installed.map(f => `<code>${esc(f)}</code>`).join(", ")}, and nothing else. In new terminals <code>claude</code> then always starts in the default profile.`;
    if (!(await confirmBox(on ? "Pick the profile from the folder?" : "Stop picking the profile from the folder?", sub, on ? "Turn on" : "Turn off"))) { sw.checked = !on; return; }
    try { await run(() => api("/api/shell", { install: on })); } catch {}
    loadSharing();
  };
  const go = async () => {
    const out = $("#bf-result"), path = $("#bf-path").value.trim();
    if (!/^[\/~]/.test(path)) { out.innerHTML = `<span class="issue err">Type an absolute folder, or one starting with ~</span>`; return; }
    try {
      const w = await api("/api/shell/which?path=" + encodeURIComponent(path));
      const where = `<code>${esc(w.path)}</code>${w.exists ? "" : " (not on disk yet)"}`;
      out.innerHTML = w.profile
        ? `${where}: ${badge(w.profile)} ` + (w.default ? `the default profile, <code>CLAUDE_CONFIG_DIR</code> left unset.` : `<code>CLAUDE_CONFIG_DIR=${esc(w.dir)}</code>`)
        : `${where}: ` + (w.rule === "shared" ? `a rule says all profiles, so claude starts in the default profile.` : `no rule matches, so claude starts in the default profile.`);
    } catch (e) { out.innerHTML = `<span class="issue err">${esc(e.message)}</span>`; }
  };
  $("#bf-go").onclick = go;
  $("#bf-path").onkeydown = e => { if (e.key === "Enter") go(); };
}
async function newProfile() {
  let tpl = [], gh = null;
  try { tpl = (await api("/api/templates")).templates; } catch {}
  try { gh = await api("/api/github"); } catch {}
  const opts = S.profiles.map(p => `<label><input type="radio" name="base" value="${p.id}" ${p.id === S.profiles[0].id ? "checked" : ""}> Copy of ${esc(p.label)} <span class="hint">(settings, MCP servers; you log in again)</span></label>`).join("")
    + tpl.map(t => `<label><input type="radio" name="base" value="template:${esc(t.name)}"> From template: ${esc(t.name)} <span class="hint">(${esc(t.items.join(", ") || "empty")})</span></label>`).join("");
  const resP = modal({ title: "New profile", sub: "Creates the folder <code>~/.claude-&lt;id&gt;</code> and a <code>claude-&lt;id&gt;</code> command in <code>~/.local/bin</code> that starts Claude Code in it.",
    body: `<div class="form">
      <label class="f">Name<input class="text" id="np-label" placeholder="e.g. Work"></label>
      <label class="f">Id (folder and command)<input class="text" id="np-id" placeholder="e.g. work"></label>
      <div class="hint" id="np-cmd"></div>
      <div class="radio">${opts}<label><input type="radio" name="base" value=""> Empty</label></div>
      <label class="check" id="np-projwrap"><input type="checkbox" id="np-proj"> also copy project conversations, history and memories</label>
      <div id="np-share"><div class="hint">Share with ${esc(S.profiles[0].label)}:</div>
      <div class="checks">${SHARE_NEW.map(i => `<label><input type="checkbox" name="share" value="${i}" ${i === "skills" || i === "plugins" ? "checked" : ""}> <code>${i}</code></label>`).join("")}</div></div>
      <div class="hint" id="np-tpl" hidden></div>
      ${gh?.gh ? `<div class="hint">It gets its own GitHub CLI folder, <code id="np-ghdir">~/.config/gh-&lt;id&gt;</code>, signed in as your current account until you pick another one in Profiles → GitHub.</div>` : ""}
    </div>`, actions: [{ label: "Create profile", kind: "primary", value: "ok" }] });
  const L = $("#np-label"), I = $("#np-id"); let touched = false;
  const slug = v => v.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 30);
  const upd = () => {
    $("#np-cmd").innerHTML = I.value ? `Command <code>claude-${esc(I.value)}</code> · folder <code>~/.claude-${esc(I.value)}</code>` : "";
    if ($("#np-ghdir")) $("#np-ghdir").textContent = `~/.config/gh-${I.value || "<id>"}`;
  };
  L.oninput = () => { if (!touched) I.value = slug(L.value); upd(); };
  I.oninput = () => { touched = true; upd(); };
  // A template fills the items it holds; an item shared with the source is linked instead,
  // and the hint says which of the template's copies that skips. Plugins are never in a template.
  const src = esc(S.profiles[0].label);
  let shareTouched = false;
  const shareBoxes = () => [...document.querySelectorAll('input[name="share"]')];
  const tplHint = () => {
    const base = document.querySelector('input[name="base"]:checked')?.value || "";
    const t = base.startsWith("template:") && tpl.find(x => x.name === base.slice(9));
    $("#np-tpl").hidden = !t;
    if (!t) return;
    const nouns = { skills: ["skill", "skills"], agents: ["agent", "agents"], commands: ["command", "commands"] };
    const lines = shareBoxes().filter(c => c.checked).map(c => {
      const i = c.value, n = (t.counts || {})[i] || 0;
      if (i === "plugins") return `<code>plugins</code>: shared with ${src}`;
      if (!n) return `<code>${esc(i)}</code>: shared with ${src} (the template has none)`;
      return `<code>${esc(i)}</code>: shared with ${src}, the template's ${nouns[i] ? `${plural(n, ...nouns[i])} ${n === 1 ? "is" : "are"}` : `<code>${esc(i)}</code> is`} not copied`;
    });
    $("#np-tpl").innerHTML = `The profile gets the template's own copies of what is not shared: settings, <code>CLAUDE.md</code>, permissions, skills, agents, commands, output styles and MCP servers.
      Plugins are never in a template: share <code>plugins</code> to give the new profile the plugins of ${src}.`
      + (lines.length ? `<ul class="np-list">${lines.map(l => `<li>${l}</li>`).join("")}</ul>` : "");
  };
  shareBoxes().forEach(c => c.addEventListener("change", () => { shareTouched = true; tplHint(); }));
  document.querySelectorAll('input[name="base"]').forEach(r => r.onchange = () => {
    const isTpl = r.value.startsWith("template:");
    $("#np-projwrap").style.display = r.value && !isTpl ? "" : "none";
    // until the choices are changed by hand: a template keeps its own skills, plugins come from the source
    if (!shareTouched) shareBoxes().forEach(c => { c.checked = c.value === "plugins" || (!isTpl && c.value === "skills"); });
    tplHint();
  });
  const res = await resP;
  if (!res) return;
  const v = sel => $(sel, res.el);
  const base = v('input[name="base"]:checked').value;
  const body = { label: v("#np-label").value, id: v("#np-id").value,
    base, include_projects: v("#np-proj").checked,
    share: [...res.el.querySelectorAll('input[name="share"]:checked')].map(c => c.value) };
  const req = base.startsWith("template:")
    ? () => api("/api/templates/create", { name: base.slice(9), label: body.label, id: body.id, share: body.share })
    : () => api("/api/profiles/create", body);
  try { await run(req); } catch { return; }
  await refresh(); if (S.tab === "profiles") loadSharing();
}
async function manageTemplates() {
  let data;
  try { data = await api("/api/templates"); } catch (e) { toast(e.message, "", true); return; }
  const list = () => data.templates.length ? `<div class="table">${data.templates.map(t => `<div class="prow"><div class="txt">
      <div class="t">${esc(t.name)}</div>
      <div class="m">from ${esc(t.from)} · ${esc(t.created.replace("T", " ").slice(0, 16))} · ${esc(t.items.join(", ") || "empty")} · ${plural(t.skills, "skill", "skills")} · ${plural(t.mcp, "MCP server", "MCP servers")} · ${size(t.size)}</div></div>
      <div class="acts"><button class="btn small danger" data-tdel="${esc(t.name)}">Delete</button></div></div>`).join("")}</div>`
    : `<div class="hint">No templates yet.</div>`;
  const resP = modal({ title: "Profile templates",
    sub: `A template holds settings, <code>CLAUDE.md</code>, permissions, skills, agents, commands, output styles and MCP servers: never conversations, memories or login credentials. Templates live in <code>${esc(data.dir)}</code>; pick one in New profile.`,
    body: `<div id="tp-list">${list()}</div>
      <div class="form" style="margin-top:12px">
        <label class="f">Profile to save as a template<select id="tp-prof">${S.profiles.map(p => `<option value="${p.id}">${esc(p.label)}</option>`).join("")}</select></label>
        <label class="f">Template name<input class="text" id="tp-name" placeholder="e.g. Client base" autocomplete="off"></label></div>`,
    actions: [{ label: "Save template", kind: "primary", value: "save" }] });
  const box = $("#tp-list");
  box.onclick = async e => {
    const name = e.target.closest("[data-tdel]")?.dataset.tdel;
    if (!name || !(await confirmBox(`Delete the template ${name}?`, "The file goes to the backup: Restore brings it back.", "Delete", "danger"))) return;
    try { await run(() => api("/api/templates/delete", { name })); data = await api("/api/templates"); } catch { return; }
    box.innerHTML = list();
  };
  const res = await resP;
  if (!res) return;
  try { await run(() => api("/api/templates/save", { profile: $("#tp-prof", res.el).value, name: $("#tp-name", res.el).value.trim() })); } catch {}
}
async function editProfile(id) {
  const p = S.profiles.find(x => x.id === id);
  const res = await modal({ title: `Edit ${p.label}`,
    sub: `The folder <code>${esc(p.dir)}</code> does not change: renaming it would break the paths stored inside the profile.`,
    body: `<div class="form">
      <label class="f">Name (UI and status line)<input class="text" id="pe-label" value="${esc(p.label)}"></label>
      <label class="f">Command${p.primary ? " (this is Claude Code itself and cannot change)" : " (launcher in ~/.local/bin)"}
        <input class="text" id="pe-cmd" value="${esc(p.command)}" ${p.primary ? "disabled" : ""}></label></div>`,
    actions: [{ label: "Save", kind: "primary", value: "ok" }] });
  if (!res) return;
  try { await run(() => api("/api/profiles/update", { id, label: $("#pe-label", res.el).value, command: $("#pe-cmd", res.el).value })); } catch { return; }
  await refresh(); loadSharing();
}
async function deleteProfile(id) {
  const p = S.profiles.find(x => x.id === id);
  const others = S.profiles.filter(x => x.id !== id);
  const resP = modal({ title: `Delete ${p.label}?`,
    sub: `<code>${esc(p.dir)}</code> · ${plural(p.conv, "conversation", "conversations")} · ${plural(p.projects, "project", "projects")} · ${plural(p.memories, "memory", "memories")}`,
    body: `<div class="form">
      ${p.active ? `<div class="danger-box">A session is open in ${esc(p.label)}: a running Claude Code would keep writing to a folder that is gone. Close it first.
        <label class="check" style="margin-top:8px"><input type="checkbox" id="pd-force"> Delete it anyway</label></div>` : ""}
      <div class="radio" role="radiogroup" aria-label="What happens to its conversations and memories">
        <label><input type="radio" name="pd" value="" checked> Delete everything</label>
        ${others.length ? `<label><input type="radio" name="pd" value="merge"> Move its conversations, memories and history to
          <select id="pd-into" aria-label="Profile to move them to">${others.map(o => `<option value="${esc(o.id)}">${esc(o.label)}</option>`).join("")}</select></label>` : ""}
      </div>
      <div class="hint" id="pd-plan" aria-live="polite"></div>
      <div class="hint">The profile and its <code>${esc(p.command)}</code> command are removed too. Everything can be undone from the Backups tab.</div>
      <label class="f"><span>Type “<b>${esc(p.label)}</b>” to confirm</span><input class="text" id="pd-confirm" autocomplete="off"></label>
    </div>`,
    actions: [{ label: "Delete profile", kind: "danger", value: "ok" }] });
  const btn = document.querySelector('.modal [data-i="0"]'), inp = $("#pd-confirm"), box = $("#pd-plan");
  const force = $("#pd-force"), sel = $("#pd-into");
  const into = () => document.querySelector('input[name="pd"]:checked')?.value === "merge" ? sel.value : "";
  const ready = () => { btn.disabled = inp.value.trim() !== p.label || (force && !force.checked); };
  inp.oninput = ready;
  if (force) force.onchange = ready;
  ready();
  let asked = 0;
  const showPlan = async () => {
    const to_id = into(), n = ++asked;
    box.innerHTML = `<span class="spinner"></span>`;
    let plan;
    try { plan = await api(`/api/profiles/delete/preview?id=${encodeURIComponent(id)}${to_id ? "&merge_into=" + encodeURIComponent(to_id) : ""}`); }
    catch (e) { if (n === asked) box.textContent = e.message; return; }
    if (n !== asked || !box.isConnected) return;
    const to = esc(plan.into || "");
    box.innerHTML = (plan.into
      ? `Moves to ${to}: ${plural(plan.projects, "project", "projects")}, ${plural(plan.conversations, "conversation", "conversations")}, ${plural(plan.memories, "memory", "memories")}, ${plural(plan.prompts, "prompt", "prompts")}${plan.settings ? `, the settings of ${plural(plan.settings, "project", "projects")}` : ""}. Then the folder goes to the backup.`
      : `Nothing is moved: the whole folder <code>${esc(plan.folder)}</code> goes to the backup.`) + planDetails(plan.items, to);
  };
  document.querySelectorAll('input[name="pd"]').forEach(r => r.onchange = showPlan);
  if (sel) sel.onchange = () => { document.querySelector('input[name="pd"][value="merge"]').checked = true; showPlan(); };
  showPlan();
  const res = await resP;
  if (!res) return;
  const merge_into = res.el.querySelector('input[name="pd"]:checked').value === "merge" ? $("#pd-into", res.el).value : "";
  try { await run(() => api("/api/profiles/delete", { id, merge_into, force: !!$("#pd-force", res.el)?.checked })); } catch { return; }
  if (S.mem.profile === id) { S.mem.profile = null; S.mem.project = null; }
  await refresh(); loadSharing();
}
