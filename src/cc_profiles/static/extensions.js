// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Andrea Iannarone
// Skills, MCP servers and claude.ai connectors, agents.

// ---------- skills and MCP servers ----------
const EXT_TABS = ["skills", "agents", "mcp"];
async function loadExt(pid) {
  const x = S.ext, tab = S.tab;
  if (pid && pid !== x.profile) { x.profile = pid; x.skill = null; x.agent = null; }
  x.profile = x.profile || S.profiles[0]?.id;
  x.error = null;
  if (tab === "skills") x.skills = null; else if (tab === "agents") x.agents = null; else x.mcp = null;
  renderExt();
  try {
    if (tab === "skills") x.skills = await api("/api/skills?profile=" + x.profile);
    else if (tab === "agents") x.agents = await api("/api/agents?profile=" + x.profile);
    else [x.mcp, x.conn] = await Promise.all([api("/api/mcp?profile=" + x.profile), api("/api/connectors?profile=" + x.profile)]);
  } catch (e) {
    // "Not found" means the page is newer than the running server: the page is read from disk at every load
    x.error = e.message === "Not found" ? "This page is newer than the running cc-profiles server: run cc-profiles restart (or /cc-profiles restart in Claude Code), then reload the page." : e.message;
    return renderExt();
  }
  if (x.skills && x.skill && !x.skills.skills.some(k => k.name === x.skill)) x.skill = null;
  if (x.agents && x.agent && x.agent.name && !x.agents.agents.some(a => a.name === x.agent.name)) x.agent = null;
  renderExt();
  if (tab === "mcp") checkConnectors(false);
}
// Ask claude.ai, through `claude mcp list`, which connectors the account has now (the server keeps
// the answer for an hour), then take off the list the ones that are gone.
async function checkConnectors(force) {
  const x = S.ext, pid = x.profile;
  x.connChecking = true; renderExt();
  try {
    const r = await api(`/api/connectors/check?profile=${encodeURIComponent(pid)}${force ? "&force=1" : ""}`);
    x.connSkipped = r.skipped;
    if (r.error && force) toast(r.error, "", true);
    if (r.gone.length) await run(() => api("/api/connectors/sync", { profile: pid }));
    if (x.profile === pid) x.conn = await api("/api/connectors?profile=" + encodeURIComponent(pid));
  } catch {}
  x.connChecking = false;
  if (x.profile === pid) renderExt();
}
async function openSkill(name) {
  const x = S.ext;
  const r = await api(`/api/skills/file?profile=${x.profile}&name=${encodeURIComponent(name)}`);
  Object.assign(x, { skill: name, content: r.content, files: r.files }); renderExt();
}
const otherProfiles = pid => S.profiles.filter(p => p.id !== pid);
async function pickProfile(title, sub, pid, okLabel) {
  const res = await modal({ title, sub, body: `<select id="pp" aria-label="Target profile">${otherProfiles(pid).map(p => `<option value="${p.id}">${esc(p.label)}</option>`).join("")}</select>`,
    actions: [{ label: okLabel, kind: "primary", value: "ok" }] });
  return res && $("#pp", res.el).value;
}
const scopeLabel = s => s === "user" ? "All projects" : basename(s);
function renderExt() {
  if (!EXT_TABS.includes(S.tab)) return;
  const x = S.ext, prof = S.profiles.find(p => p.id === x.profile), data = S.tab === "skills" ? x.skills : S.tab === "agents" ? x.agents : x.mcp;
  const seg = `<div class="seg" style="max-width:360px">${S.profiles.map(p => `<button data-extprof="${p.id}" class="${x.profile === p.id ? "on" : ""}">${esc(p.label)}</button>`).join("")}</div>`;
  const head = `<div class="toolbar">${seg}<span class="hint">${prof?.email ? `Signed in as <b>${esc(prof.email)}</b>` : "Not signed in"}. Changes apply from the next Claude Code session in this profile; every change goes to the backup.</span></div>`;
  if (x.error) { $("#main").innerHTML = `${head}<div class="empty">${esc(x.error)}</div>`; return; }
  if (!data) { $("#main").innerHTML = `${head}<div class="empty">${LOADER} Loading ${S.tab === "skills" ? "skills" : S.tab === "agents" ? "agents" : "MCP servers"}…</div>`; return; }
  return S.tab === "skills" ? renderSkills(head) : S.tab === "agents" ? renderAgents(head) : renderMcp(head);
}
function renderSkills(head) {
  const x = S.ext;
  const q = x.q.toLowerCase();
  const skills = x.skills.skills.filter(k => !q || (k.name + " " + k.description).toLowerCase().includes(q));
  const cur = x.skills.skills.find(k => k.name === x.skill);
  $("#main").innerHTML = `${head}
    <div class="ext-head" style="margin-top:0"><h2>Skills</h2><span class="hint"><code>${esc(x.skills.dir)}</code> · ${plural(x.skills.skills.length, "skill", "skills")}${x.skills.shared ? ` · <span class="shared-note">${esc(x.skills.shared)}: a change here applies there too</span>` : ""}</span>
      <input class="search" style="margin:0" placeholder="Filter skills…" value="${esc(x.q)}" id="extq" aria-label="Filter skills">
      <button class="btn primary" id="sknew">New skill…</button></div>
    <div class="cards skgrid">${skills.map(k => `<div class="mcard ${k.name === x.skill ? "on" : ""}" data-skill="${esc(k.name)}" tabindex="0" role="button">
        <div class="t">${esc(k.title)}${k.linked ? ` <span class="badge b-none" title="A link to a folder elsewhere">linked</span>` : ""}${k.files ? ` <span class="badge b-none">${plural(k.files + 1, "file", "files")}</span>` : ""}</div>
        <div class="d">${esc(k.description) || "No description"}</div></div>`).join("") || `<div class="empty">${x.skills.skills.length ? "No skills match the filter." : "No skills in this profile yet."}</div>`}</div>
    ${cur ? `<div class="editor"><div class="hint" style="margin-bottom:6px"><code>${esc(x.skill)}/SKILL.md</code>${x.files.length ? ` · also in the folder: ${x.files.slice(0, 8).map(f => `<code>${esc(f)}</code>`).join(", ")}${x.files.length > 8 ? "…" : ""}` : ""}</div>
      <textarea id="sktext" spellcheck="false" aria-label="SKILL.md">${esc(x.content)}</textarea>
      <div class="row"><span class="grow">Saving keeps a copy of the previous version.</span>
        <button class="btn danger" id="skdel">Delete</button><button class="btn" id="skcopy">Copy to…</button><button class="btn" id="skall">Copy to all…</button>
        <button class="btn primary" id="sksave">Save</button></div></div>` : ""}`;

  $("#extq").oninput = e => { x.q = e.target.value; const pos = e.target.selectionStart; renderExt(); const i = $("#extq"); i.focus(); i.setSelectionRange(pos, pos); };
  $("#sknew").onclick = newSkill;
  if (cur) {
    $("#sksave").onclick = async () => { try { await run(() => api("/api/skills/save", { profile: x.profile, name: x.skill, content: $("#sktext").value })); x.content = $("#sktext").value; } catch {} };
    $("#skdel").onclick = async () => {
      const sub = cur.linked ? `Only the link <code>${esc(x.skill)}</code> is removed; the folder it points to is untouched.` : `The folder <code>${esc(x.skill)}</code> goes to the backup.`;
      if (!(await confirmBox(`Delete ${x.skill}?`, sub + (x.skills.shared ? ` The skills are ${esc(x.skills.shared)}: it disappears there too.` : ""), "Delete", "danger"))) return;
      try { await run(() => api("/api/skills/delete", { profile: x.profile, name: x.skill })); } catch { return; }
      x.skill = null; loadExt();
    };
    $("#skcopy").onclick = async () => {
      const to = await pickProfile("Copy skill", `The folder <code>${esc(x.skill)}</code> is copied with all its files.`, x.profile, "Copy");
      if (to) { try { await run(() => api("/api/skills/copy", { profile: x.profile, name: x.skill, to })); } catch {} }
    };
    $("#skall").onclick = () => applyAll(`Copy ${x.skill} to every profile?`,
      `/api/skills/copy-all/preview?profile=${encodeURIComponent(x.profile)}&name=${encodeURIComponent(x.skill)}`,
      `The folder <code>${esc(x.skill)}</code> is copied with all its files to every profile that does not have it. Profiles that share their skills with ${esc(label(x.profile))} already see it.`,
      "Copy to all", () => api("/api/skills/copy-all", { profile: x.profile, name: x.skill }));
  }
}
function renderMcp(head) {
  const x = S.ext;
  $("#main").innerHTML = `${head}
    <div class="ext-head" style="margin-top:0"><h2>MCP servers</h2><span class="hint"><code>${esc(x.mcp.config)}</code> · servers from plugins and from a project's <code>.mcp.json</code> are managed elsewhere</span>
      <button class="btn primary" id="mcpnew">Add server…</button></div>
    <div class="table">${x.mcp.servers.map((m, i) => `<div class="prow"><div class="txt">
        <div class="t">${esc(m.name)} <span class="badge b-none">${esc(m.type)}</span> <span class="badge b-none" title="${esc(m.scope === "user" ? "Available in every project" : m.scope)}">${esc(scopeLabel(m.scope))}</span></div>
        <div class="mcp-target">${esc(m.target)}</div>
        ${m.env.length || m.headers.length ? `<div class="m">${m.env.length ? `env: ${m.env.map(esc).join(", ")}` : ""}${m.env.length && m.headers.length ? " · " : ""}${m.headers.length ? `headers: ${m.headers.map(esc).join(", ")}` : ""}</div>` : ""}</div>
      <div class="acts"><button class="btn small" data-mcpedit="${i}">Edit…</button><button class="btn small" data-mcpcopy="${i}">Copy to…</button><button class="btn small" data-mcpall="${i}">Copy to all…</button>
        <button class="btn small danger" data-mcpdel="${i}">Delete</button></div></div>`).join("") || `<div class="empty">No MCP servers configured in this profile.</div>`}</div>
    ${connectorsSection()}`;

  $("#mcpnew").onclick = () => editMcp(null);
  const setConn = (path, body, cb) => run(() => api(path, { profile: x.profile, ...body })).then(() => loadExt(), () => { cb.checked = !cb.checked; });
  $("#conn-check")?.addEventListener("click", () => checkConnectors(true));
  $("#conn-all")?.addEventListener("change", e => setConn("/api/connectors/all", { enabled: e.target.checked }, e.target));
  document.querySelectorAll("[data-conn]").forEach(cb => cb.onchange = () => setConn("/api/connectors/set", { name: cb.dataset.conn, enabled: cb.checked }, cb));
  document.querySelectorAll("[data-connforget]").forEach(b => b.onclick = async () => {
    try { await run(() => api("/api/connectors/forget", { profile: x.profile, name: b.dataset.connforget })); } catch { return; }
    loadExt();
  });
  document.querySelectorAll("[data-mcpedit]").forEach(b => b.onclick = () => editMcp(x.mcp.servers[b.dataset.mcpedit]));
  document.querySelectorAll("[data-mcpcopy]").forEach(b => b.onclick = async () => {
    const m = x.mcp.servers[b.dataset.mcpcopy];
    const to = await pickProfile("Copy MCP server", `<code>${esc(m.name)}</code> is added to the other profile for every project. Its sign-in, if any, is not copied.`, x.profile, "Copy");
    if (to) { try { await run(() => api("/api/mcp/copy", { profile: x.profile, scope: m.scope, name: m.name, to })); } catch {} }
  });
  document.querySelectorAll("[data-mcpall]").forEach(b => b.onclick = () => {
    const m = x.mcp.servers[b.dataset.mcpall];
    applyAll(`Copy ${m.name} to every profile?`,
      `/api/mcp/copy-all/preview?profile=${encodeURIComponent(x.profile)}&scope=${encodeURIComponent(m.scope)}&name=${encodeURIComponent(m.name)}`,
      `<code>${esc(m.name)}</code> is added for every project to each profile that does not have a server with this name. Its sign-in, if any, is not copied.`,
      "Copy to all", () => api("/api/mcp/copy-all", { profile: x.profile, scope: m.scope, name: m.name }));
  });
  document.querySelectorAll("[data-mcpdel]").forEach(b => b.onclick = async () => {
    const m = x.mcp.servers[b.dataset.mcpdel];
    if (!(await confirmBox(`Remove ${m.name}?`, `It is removed from <code>${esc(x.mcp.config)}</code> (${esc(scopeLabel(m.scope))}). The file goes to the backup first.`, "Remove", "danger"))) return;
    try { await run(() => api("/api/mcp/delete", { profile: x.profile, scope: m.scope, name: m.name })); } catch {}
    loadExt();
  });
}
function connCheckText(c) {
  const x = S.ext;
  if (x.connChecking) return `Asking claude.ai for the account's connectors (<code>claude mcp list</code>, a few seconds)…`;
  if (x.connSkipped) return `The list shows the connectors Claude Code has connected in this profile; it is not checked with claude.ai because ${esc(x.connSkipped)}. If you removed or renamed one on claude.ai, <b>Forget</b> it here.`;
  const at = c.check?.at ? new Date(c.check.at * 1000).toTimeString().slice(0, 5) : "";
  return `${c.check?.error ? `Last check failed: ${esc(c.check.error)}.` : at ? `Checked with claude.ai at ${at}: connectors removed there leave this list, new ones appear.` : ""}
    The check runs <code>claude mcp list</code>, which also starts this profile's MCP servers, so it runs at most once an hour. <button class="btn small" id="conn-check">Check now</button>`;
}
// claude.ai connectors: they come with the account, so a profile can only keep them out
function connectorsSection() {
  const c = S.ext.conn, prof = S.profiles.find(p => p.id === S.ext.profile);
  if (!c) return "";
  const off = c.all_off.length > 0, files = { settings: "settings.json", local: "settings.local.json" };
  const err = Object.entries(c.errors).map(([w, e]) => `<code>${files[w]}</code> has an error (${esc(e)}): fix it in the advanced editor`).join("; ");
  const rows = c.connectors.map(k => `<div class="prow"><div class="txt">
      <div class="t">${esc(k.name)}${k.blocked ? ` <span class="badge b-none">blocked</span>` : ""}${k.on_account === false ? ` <span class="badge b-none" title="claude.ai no longer lists it: turn it on to remove its deny rule, then it leaves the list">not on the account</span>` : ""}</div>
      <div class="m"><code>${esc(k.rule)}</code>${k.blocked ? ` in deny of ${k.where.map(w => `<code>${files[w]}</code>`).join(" and ")}` : ""}</div></div>
    ${k.seen && !k.blocked && k.on_account !== true ? `<button class="btn small" data-connforget="${esc(k.name)}" title="Take it off this list: for a connector removed or renamed on claude.ai">Forget</button>` : ""}
    <label class="switch" title="${k.blocked ? "Off in this profile" : "On"}"><input type="checkbox" data-conn="${esc(k.name)}" ${k.blocked ? "" : "checked"} ${off || err ? "disabled" : ""} aria-label="Use ${esc(k.name)} in ${esc(prof?.label || "")}"><span></span></label></div>`).join("");
  return `<div class="ext-head"><h2>claude.ai connectors</h2><span class="hint">They come with the account${prof?.email ? ` <b>${esc(prof.email)}</b>` : ""}, so every profile signed in with it has the same ones. Turning one off adds a deny rule to this profile's <code>settings.json</code>; connect or remove them on <a href="${esc(c.url)}" target="_blank" rel="noopener">claude.ai</a>.</span>
      <span class="conn-all">All connectors</span><label class="switch" title="${off ? "All off" : "On"}"><input type="checkbox" id="conn-all" ${off ? "" : "checked"} ${err ? "disabled" : ""} aria-label="Use claude.ai connectors in ${esc(prof?.label || "")}"><span></span></label></div>
    ${err ? `<div class="hint" style="margin-bottom:8px">${err}</div>` : ""}
    ${off ? `<div class="hint" style="margin-bottom:8px">All connectors are off in this profile: <code>disableClaudeAiConnectors</code> is true in ${c.all_off.map(w => `<code>${files[w]}</code>`).join(" and ")}.</div>` : ""}
    <div class="table">${rows || `<div class="empty">No connectors seen in this profile yet: Claude Code lists the ones it has connected here at least once.</div>`}</div>
    <p class="hint conn-check">${connCheckText(c)}</p>`;
}
// ---------- agents ----------
// The list as cards; the open agent below them as a form (the fields Claude Code reads) and its
// instructions. Keys the form does not show stay in the file; Edit file… edits everything.
const AGENT_DOT = { red: "#dc2626", blue: "#6a9bcc", green: "#16a34a", yellow: "#ca8a04", purple: "#827dbd", orange: "#d97757", pink: "#c46686", cyan: "#0e9aa7" };
function agentDot(c) { return AGENT_DOT[c] ? `<span class="adot" style="background:${AGENT_DOT[c]}" aria-hidden="true"></span>` : ""; }
function agentBadges(a) {
  return `${a.model ? `<span class="badge b-none">${esc(a.model)}</span>` : ""}<span class="badge b-none">${a.tools.length ? plural(a.tools.length, "tool", "tools") : "all tools"}</span>${a.linked ? `<span class="badge b-none" title="A link to a file elsewhere">linked</span>` : ""}${a.valid ? "" : `<span class="badge b-warn" title="No frontmatter or no description: Claude Code skips it">invalid</span>`}`;
}
function renderAgents(head) {
  const x = S.ext, d = x.agents, q = x.q.toLowerCase();
  const list = d.agents.filter(a => !q || (a.name + " " + a.description).toLowerCase().includes(q));
  const cur = x.agent;
  $("#main").innerHTML = `${head}
    <div class="ext-head" style="margin-top:0"><h2>Agents</h2><span class="hint"><code>${esc(d.dir)}</code> · ${plural(d.agents.length, "agent", "agents")}: Claude hands work to them with the Agent tool${d.shared ? ` · <span class="shared-note">${esc(d.shared)}: a change here applies there too</span>` : ""}</span>
      <input class="search" style="margin:0" placeholder="Filter agents…" value="${esc(x.q)}" id="extq" aria-label="Filter agents">
      <button class="btn primary" id="agnew">New agent…</button></div>
    <div class="cards skgrid">${list.map(a => `<div class="mcard ${cur?.name === a.name ? "on" : ""}" data-agent="${esc(a.name)}" tabindex="0" role="button">
        <div class="t">${agentDot(a.color)}${esc(a.name)}</div>
        <div class="d">${esc(a.description) || "No description"}</div>
        <div class="abadges">${agentBadges(a)}</div></div>`).join("") || `<div class="empty">${d.agents.length ? "No agents match the filter." : "No agents in this profile yet: New agent… creates one."}</div>`}</div>
    ${cur ? agentEditorHtml(cur) : ""}
    ${d.plugins.length ? `<div class="ext-head"><h2>From plugins</h2><span class="hint">read-only: the plugin installs and updates them</span></div>
      <div class="cards skgrid">${d.plugins.map(a => `<div class="mcard ro"><div class="t">${agentDot(a.color)}${esc(a.name)}</div>
        <div class="d">${esc(a.description) || "No description"}</div><div class="abadges"><span class="badge b-shared">${esc(a.plugin)}</span>${agentBadges(a)}</div></div>`).join("")}</div>` : ""}`;
  $("#extq").oninput = e => { x.q = e.target.value; const pos = e.target.selectionStart; renderExt(); const i = $("#extq"); i.focus(); i.setSelectionRange(pos, pos); };
  $("#agnew").onclick = () => { x.agent = { name: "", fields: { model: "inherit" }, prompt: "", other: [], isNew: true }; renderExt(); $("#ag-name")?.focus(); };
  if (cur) bindAgentEditor(cur);
}
async function openAgent(name) {
  const x = S.ext;
  try { const r = await api(`/api/agents/file?profile=${x.profile}&name=${encodeURIComponent(name)}`); x.agent = { name, ...r }; }
  catch (e) { toast(e.message, "", true); return; }
  renderExt();
  $(".editor")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}
function agentEditorHtml(a) {
  const d = S.ext.agents, f = a.fields || {};
  const sel = (key, label, help) => {
    const opts = d.options[key], v = f[key] || "";
    const known = opts.some(([o]) => o === v);
    return `<label class="f">${label}<select id="ag-${key}" title="${esc(help)}"><option value="" ${v ? "" : "selected"}>${key === "model" ? "Not set (inherit)" : "Not set"}</option>
      ${opts.map(([o, l]) => `<option value="${esc(o)}" ${o === v ? "selected" : ""}>${esc(l)}</option>`).join("")}${v && !known ? `<option value="${esc(v)}" selected>${esc(v)}</option>` : ""}</select></label>`;
  };
  if (!a.isNew && !a.valid) return `<div class="editor"><div class="hint" style="margin-bottom:8px"><code>${esc(a.name)}.md</code> has no frontmatter between <code>---</code> lines, so Claude Code skips it: fix it in the file editor.</div>
    <div class="row"><span class="grow"></span><button class="btn danger" id="agdel">Delete</button><button class="btn primary" id="agraw">Edit file…</button></div></div>`;
  return `<div class="editor agform">
    <div class="hint" style="margin-bottom:10px">${a.isNew ? "New agent: saved as" : "Editing"} <code>${esc(d.dir)}/${esc(a.isNew ? "<name>" : a.name)}.md</code>${a.other?.length ? ` · also in the file, kept as they are: ${a.other.map(k => `<code>${esc(k)}</code>`).join(", ")} (Edit file… to change them)` : ""}</div>
    <div class="aggrid">
      <label class="f">Name (lowercase letters, digits and dashes)<input class="text" id="ag-name" value="${esc(f.name || a.name || "")}" placeholder="e.g. code-reviewer" autocomplete="off"></label>
      ${sel("model", "Model", "The model the agent runs on")}
      <label class="f ag-wide">Description: when Claude should use it<textarea class="text" id="ag-description" rows="2" placeholder="e.g. Reviews a diff for bugs before a commit. Use after writing code.">${esc(f.description || "")}</textarea></label>
      ${sel("effort", "Effort", "Thinking effort")}
      ${sel("permissionMode", "Permission mode", "How the agent's tool calls are approved")}
      <label class="f">Max turns<input class="text" id="ag-maxTurns" inputmode="numeric" value="${esc(f.maxTurns || "")}" placeholder="no limit"></label>
      ${sel("color", "Color", "Its color in Claude Code")}
      <label class="f ag-wide">Tools it may use (comma-separated; empty: all of them)<input class="text" id="ag-tools" list="ag-tool-list" value="${esc((f.tools || []).join(", "))}" placeholder="all tools" autocomplete="off"></label>
      <label class="f ag-wide">Tools it may not use (only when the list above is empty)<input class="text" id="ag-disallowedTools" value="${esc((f.disallowedTools || []).join(", "))}" placeholder="none" autocomplete="off"></label>
      <datalist id="ag-tool-list">${d.tools.map(t => `<option value="${esc(t)}">`).join("")}</datalist>
    </div>
    <label class="f" style="margin-top:12px">Instructions: the agent's system prompt<textarea id="ag-prompt" spellcheck="false" placeholder="You are … When you are called, …">${esc(a.prompt || "")}</textarea></label>
    <div class="row"><span class="grow">${a.isNew ? "Saving creates the file." : "Saving keeps a copy of the previous version."}</span>
      ${a.isNew ? `<button class="btn" id="agcancel">Cancel</button>` : `<button class="btn danger" id="agdel">Delete</button><button class="btn" id="agcopy">Copy to…</button><button class="btn" id="agall">Copy to all…</button><button class="btn" id="agraw">Edit file…</button>`}
      <button class="btn primary" id="agsave">${a.isNew ? "Create agent" : "Save"}</button></div></div>`;
}
function bindAgentEditor(a) {
  const x = S.ext, v = id => $(id)?.value ?? "";
  $("#agcancel") && ($("#agcancel").onclick = () => { x.agent = null; renderExt(); });
  $("#agsave") && ($("#agsave").onclick = async () => {
    const fields = { name: v("#ag-name").trim(), description: v("#ag-description").replace(/\s+/g, " ").trim(), model: v("#ag-model"), effort: v("#ag-effort"),
      permissionMode: v("#ag-permissionMode"), maxTurns: v("#ag-maxTurns").trim(), color: v("#ag-color"), tools: v("#ag-tools"), disallowedTools: v("#ag-disallowedTools") };
    try { await run(() => api("/api/agents/save", { profile: x.profile, fields, prompt: v("#ag-prompt"), old_name: a.isNew ? null : a.name })); } catch { return; }
    x.agents = await api("/api/agents?profile=" + x.profile);
    await openAgent(fields.name);
  });
  $("#agdel") && ($("#agdel").onclick = async () => {
    if (!(await confirmBox(`Delete ${a.name}?`, `<code>${esc(a.name)}.md</code> goes to the backup.${x.agents.shared ? ` The agents are ${esc(x.agents.shared)}: it disappears there too.` : ""}`, "Delete", "danger"))) return;
    try { await run(() => api("/api/agents/delete", { profile: x.profile, name: a.name })); } catch { return; }
    x.agent = null; loadExt();
  });
  $("#agcopy") && ($("#agcopy").onclick = async () => {
    const to = await pickProfile("Copy agent", `<code>${esc(a.name)}.md</code> is copied as it is now (save your changes first).`, x.profile, "Copy");
    if (to) { try { await run(() => api("/api/agents/copy", { profile: x.profile, name: a.name, to })); } catch {} }
  });
  $("#agall") && ($("#agall").onclick = () => applyAll(`Copy ${a.name} to every profile?`,
    `/api/agents/copy-all/preview?profile=${encodeURIComponent(x.profile)}&name=${encodeURIComponent(a.name)}`,
    `<code>${esc(a.name)}.md</code> is copied, as it is now, to every profile that does not have an agent with this name. Profiles that share their agents with ${esc(label(x.profile))} already see it.`,
    "Copy to all", () => api("/api/agents/copy-all", { profile: x.profile, name: a.name })));
  $("#agraw") && ($("#agraw").onclick = async () => {
    const r = await api(`/api/agents/file?profile=${x.profile}&name=${encodeURIComponent(a.name)}`);
    const res = await modal({ title: `${a.name}.md`, sub: "The whole file: frontmatter between <code>---</code> lines, then the instructions. The name must stay the same; rename it from the form.",
      body: `<textarea id="agrawtext" class="rawtext" spellcheck="false" aria-label="${esc(a.name)}.md">${esc(r.content)}</textarea>`,
      actions: [{ label: "Save", kind: "primary", value: "ok" }] });
    if (!res) return;
    try { await run(() => api("/api/agents/save-raw", { profile: x.profile, name: a.name, content: $("#agrawtext", res.el).value })); } catch { return; }
    x.agents = await api("/api/agents?profile=" + x.profile);
    await openAgent(a.name);
  });
}
async function newSkill() {
  const x = S.ext;
  const res = await modal({ title: "New skill", sub: `Creates <code>${esc(x.skills.dir)}/&lt;name&gt;/SKILL.md</code>, ready to fill in.`,
    body: `<div class="form"><label class="f">Name (lowercase letters, digits and dashes)<input class="text" id="skn" placeholder="e.g. release-notes"></label>
      <label class="f">Description: what it does and when Claude should use it<input class="text" id="skd" placeholder="e.g. Write release notes from the merged pull requests"></label></div>`,
    actions: [{ label: "Create skill", kind: "primary", value: "ok" }] });
  if (!res) return;
  const name = $("#skn", res.el).value.trim();
  try { await run(() => api("/api/skills/create", { profile: x.profile, name, description: $("#skd", res.el).value })); } catch { return; }
  await loadExt(); openSkill(name);
}
const lines = t => t.split("\n").map(l => l.trim()).filter(Boolean);
const pairs = (t, sep) => Object.fromEntries(lines(t).map(l => { const i = l.indexOf(sep); return i < 0 ? [l, ""] : [l.slice(0, i).trim(), l.slice(i + 1).trim()]; }));
async function editMcp(m) {
  const x = S.ext;
  const conf = m ? (await api(`/api/mcp/server?profile=${x.profile}&scope=${encodeURIComponent(m.scope)}&name=${encodeURIComponent(m.name)}`)).config : { type: "stdio" };
  const type = conf.type || (conf.command ? "stdio" : "http");
  const scopes = m ? [m.scope] : ["user", ...x.mcp.projects];
  const resP = modal({ title: m ? `Edit ${m.name}` : "Add MCP server",
    sub: `Saved in <code>${esc(x.mcp.config)}</code>, like <code>claude mcp add</code> does.`,
    body: `<div class="form">
      <label class="f">Name<input class="text" id="mn" value="${esc(m?.name || "")}" placeholder="e.g. github"></label>
      <label class="f">Available in<select id="ms" ${m ? "disabled" : ""}>${scopes.map(s => `<option value="${esc(s)}">${s === "user" ? "All projects" : esc(s)}</option>`).join("")}</select></label>
      <label class="f">Type<select id="mt">${["stdio", "http", "sse"].map(t => `<option value="${t}" ${t === type ? "selected" : ""}>${{ stdio: "stdio: a local command", http: "http: a remote server", sse: "sse: a remote server (older protocol)" }[t]}</option>`).join("")}</select></label>
      <label class="f" data-for="stdio">Command<input class="text" id="mc" value="${esc(conf.command || "")}" placeholder="e.g. npx"></label>
      <label class="f" data-for="stdio">Arguments, one per line<textarea class="code" id="ma" style="min-height:70px">${esc((conf.args || []).join("\n"))}</textarea></label>
      <label class="f" data-for="stdio">Environment variables, one NAME=value per line<textarea class="code" id="me" style="min-height:60px">${esc(Object.entries(conf.env || {}).map(([k, v]) => `${k}=${v}`).join("\n"))}</textarea></label>
      <label class="f" data-for="remote">URL<input class="text" id="mu" value="${esc(conf.url || "")}" placeholder="https://…"></label>
      <label class="f" data-for="remote">Headers, one Name: value per line<textarea class="code" id="mh" style="min-height:60px">${esc(Object.entries(conf.headers || {}).map(([k, v]) => `${k}: ${v}`).join("\n"))}</textarea></label>
    </div>`, actions: [{ label: m ? "Save" : "Add server", kind: "primary", value: "ok" }] });
  const show = () => { const t = $("#mt").value; document.querySelectorAll(".modal [data-for]").forEach(el => { el.hidden = (el.dataset.for === "stdio") !== (t === "stdio"); }); };
  $("#mt").onchange = show; show();
  const res = await resP;
  if (!res) return;
  const v = id => $(id, res.el).value;
  const t = v("#mt");
  const out = { ...conf, type: t };  // keeps fields this form does not show
  for (const k of ["command", "args", "env", "url", "headers"]) delete out[k];
  if (t === "stdio") {
    out.command = v("#mc").trim();
    if (lines(v("#ma")).length) out.args = lines(v("#ma"));
    if (lines(v("#me")).length) out.env = pairs(v("#me"), "=");
  } else {
    out.url = v("#mu").trim();
    if (lines(v("#mh")).length) out.headers = pairs(v("#mh"), ":");
  }
  try { await run(() => api("/api/mcp/save", { profile: x.profile, scope: m ? m.scope : v("#ms"), name: v("#mn").trim(), old_name: m?.name, config: out })); } catch { return; }
  loadExt();
}
