// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Andrea Iannarone
// Projects, choosing a folder, Open in Terminal, dropped files, memories, conversations, health.

// ---------- projects ----------
function filtered() {
  const q = S.q.toLowerCase();
  return S.projects.filter(r => {
    if (q && !r.pretty.toLowerCase().includes(q)) return false;
    if (S.filter === "issues") return r.issues.length > 0;
    if (S.filter === "all") return true;
    return r.expected === S.filter;
  });
}
function renderProjects() {
  const ids = S.profiles.map(p => p.id);
  const chips = [["issues", "Needs attention"], ["all", "All"], ...S.profiles.map(p => [p.id, p.label]), ["shared", "Shared"]];
  const rows = filtered();
  $("#main").innerHTML = `
    <div class="toolbar">
      ${chips.map(([k, l]) => `<button class="chip ${S.filter === k ? "on" : ""}" data-filter="${k}">${esc(l)}</button>`).join("")}
      <input class="search" placeholder="Search a path…" value="${esc(S.q)}" id="q" aria-label="Search projects">
    </div>
    <div class="table">${rows.length ? `<table>
      <thead><tr><th>Project</th><th>Belongs to</th>${S.profiles.map(p => `<th>${esc(p.label)}</th>`).join("")}<th>Status</th><th></th></tr></thead>
      <tbody>${rows.map(r => {
        const pi = r.issues.find(i => i.kind === "profile");
        const main = pi ? { a: "fixmove", l: `Move to ${label(pi.to)}` }
                   : r.issues.find(i => i.kind === "orphan") ? { a: "relink", l: "Relink…" }
                   : r.issues.find(i => i.kind === "unclassified") ? { a: "rule", l: "Assign…" } : null;
        return `<tr>
          <td class="path mono">${esc(r.pretty)}</td>
          <td>${badge(r.expected)}</td>
          ${ids.map(id => { const s = r.in[id]; return `<td class="nums">${s ? `${s.conv} conv · ${s.mem} mem` : "—"}</td>`; }).join("")}
          <td>${r.issues.length ? r.issues.map(i => `<div class="issue ${i.kind === "orphan" ? "err" : ""}">${esc(i.text)}</div>`).join("") : `<span class="okmark">✓ all good</span>`}</td>
          <td class="acts">${main ? `<button class="btn small primary" data-act="${main.a}" data-name="${esc(r.name)}">${esc(main.l)}</button>` : ""}
            ${main?.a === "relink" ? `<button class="btn small" data-act="merge" data-name="${esc(r.name)}">Merge into…</button>` : ""}
            ${S.term?.supported && r.exists ? `<button class="btn small" data-act="term" data-name="${esc(r.name)}" title="Claude Code in this folder">Open in ${esc(S.term.terminal)}</button>` : ""}
            <button class="btn small" data-act="manage" data-name="${esc(r.name)}">Manage</button></td></tr>`;
      }).join("")}</tbody></table>` : `<div class="empty">${S.filter === "issues" ? "Nothing needs attention. ✓" : "No projects."}</div>`}
    </div>`;
  $("#q").oninput = e => { S.q = e.target.value; const pos = e.target.selectionStart; renderProjects(); const i = $("#q"); i.focus(); i.setSelectionRange(pos, pos); };
}
const byName = n => S.projects.find(r => r.name === n);

const PLAN = { move: to => `moves to ${to}`, merge: to => `is merged into the index of ${to}`, conflict: to => `${to} already has it: the original goes to the backup` };
// The other previews (delete a profile, share, separate) use the same items plus a few actions of their own.
const PLAN_MORE = {
  merge: (i, to) => i.item === "history.jsonl" ? `is merged into the prompt history of ${to}` : PLAN.merge(to),
  stash: () => "goes to the backup",
  edit: i => `in <code>${esc(i.from)}</code>: ${esc(i.to)}`,
  "only-here": () => "exists only here: it goes to the backup and is no longer used",
  link: i => `becomes a link to <code>${esc(i.to)}</code>`,
  create: i => `is created, empty, at <code>${esc(i.to)}</code>`,
  copy: i => `is copied from <code>${esc(i.from)}</code>${i.files > 1 ? ` (${plural(i.files, "file", "files")})` : ""}`,
};
function planDetails(items, to) {
  if (!items.length) return "";
  const text = i => PLAN_MORE[i.action] ? PLAN_MORE[i.action](i, to) : PLAN[i.action] ? PLAN[i.action](to) : esc(i.action);
  return `<details style="margin-top:10px"><summary>Show the ${plural(items.length, "file or folder", "files and folders")} it touches</summary>
    <ul class="plan">${items.map(i => `<li class="${esc(i.action)}" title="${esc(i.from)}${i.to ? " → " + esc(i.to) : ""}"><code>${esc(i.item)}</code> ${text(i)}</li>`).join("")}</ul></details>`;
}
// Apply to all profiles: show which profiles change and which are skipped (with the reason), then run it.
// One backup covers every profile, so one Restore undoes it. Returns true when it ran.
async function applyAll(title, preview, intro, okLabel, post) {
  let plan;
  try { plan = await api(preview); } catch (e) { toast(e.message, "", true); return false; }
  const skip = plan.skip.length ? `<div style="margin-top:10px">Skipped:</div><ul class="plan">${plan.skip.map(s => `<li><b>${esc(s.label)}</b>: ${esc(s.reason)}</li>`).join("")}</ul>` : "";
  if (!plan.apply.length) { await modal({ title, sub: `${intro} No profile to change.${skip}` }); return false; }
  const list = `<ul class="plan">${plan.apply.map(a => `<li><b>${esc(a.label)}</b>: ${esc(a.detail)}</li>`).join("")}</ul>`;
  if (!(await confirmBox(title, `${intro}<div style="margin-top:10px">Changes ${plural(plan.apply.length, "profile", "profiles")}:</div>${list}${skip}<div style="margin-top:10px">One backup covers every profile: one Restore undoes it all.</div>`, okLabel))) return false;
  try { await run(post); } catch { return false; }
  return true;
}
async function doMove(r, from, to) {
  const s = r.in[from];
  let plan = null;
  try { plan = await api(`/api/projects/move/preview?project=${encodeURIComponent(r.name)}&from=${from}&to=${to}`); } catch {}
  const open = S.profiles.filter(p => (p.id === from || p.id === to) && p.active).map(p => esc(p.label));
  const details = plan ? `<details style="margin-top:10px"><summary>Show the ${plural(plan.items.length, "file or folder", "files and folders")} it touches</summary>
      <ul class="plan">${plan.items.map(i => `<li class="${i.action}" title="${esc(i.from)} → ${esc(i.to)}"><code>${esc(i.item)}</code> ${PLAN[i.action](esc(label(to)))}</li>`).join("")}
        ${plan.prompts ? `<li>${plural(plan.prompts, "prompt", "prompts")} ${plan.prompts === 1 ? "moves" : "move"} from <code>${esc(plan.history)}</code></li>` : ""}
        ${plan.settings ? `<li>The project settings move from <code>${esc(plan.config)}</code></li>` : ""}</ul></details>` : "";
  const warn = open.length ? `<div class="danger-box" style="margin-top:10px">A Claude Code session is open in ${open.join(" and ")}. It keeps <code>.claude.json</code> in memory and could write the old project settings back: close it first, or restart it after moving.</div>` : "";
  if (!(await confirmBox(`Move to ${label(to)}?`,
      `<code>${esc(r.pretty)}</code><br>From ${esc(label(from))} to ${esc(label(to))}: ${plural(s.conv, "conversation", "conversations")}, ${plural(s.mem, "memory", "memories")}, the prompt history and the project settings. Anything ${esc(label(to))} already has goes to the backup.${warn}${details}`, "Move"))) return;
  await run(() => api("/api/projects/move", { project: r.name, from, to })); await refresh();
}
// ---------- choosing a folder ----------
// A browser never tells a page the full path of a folder you pick, so Choose… asks the server:
// it opens the system's folder dialog (macOS, Linux with zenity or kdialog) and returns the path.
// Where there is no dialog (WSL…), a folder browser opens under the field instead.
function folderField(id, value, placeholder, label, extra = "") {
  return `<div class="ffield"><div class="ffrow"><input class="text mono" id="${id}" value="${esc(value)}" placeholder="${esc(placeholder)}" aria-label="${esc(label)}" autocomplete="off" ${extra}>
    <button type="button" class="btn" data-choose="${id}" data-prompt="${esc(label)}">Choose…</button></div>
    <div class="fbrowse" id="${id}-browse" hidden></div></div>`;
}
const joinPath = (dir, name) => dir.endsWith("/") ? dir + name : dir + "/" + name;
async function chooseFolder(id, prompt) {
  const input = $("#" + id), btn = $(`[data-choose="${id}"]`);
  if (!input) return;
  const label = btn.textContent;
  btn.disabled = true; btn.textContent = "Choosing…";
  let r;
  try { r = await api(`/api/folders/pick?start=${encodeURIComponent(input.value)}&prompt=${encodeURIComponent(prompt || "Choose a folder")}`); }
  catch (e) { toast(e.message, "", true); return; }
  finally { btn.disabled = false; btn.textContent = label; }
  if (!r.native) return browseFolder(id, input.value.trim() || r.start, false);
  if (r.cancelled) return input.focus();
  input.value = r.path; input.dispatchEvent(new Event("input", { bubbles: true })); input.focus();
}
async function browseFolder(id, path, hidden) {
  const box = $(`#${id}-browse`), input = $("#" + id);
  if (!box) return;
  let d;
  try { d = await api(`/api/folders?path=${encodeURIComponent(path)}${hidden ? "&hidden=1" : ""}`); }
  catch (e) { toast(e.message, "", true); return; }
  box.hidden = false;
  box.innerHTML = `<div class="fbcrumbs" aria-label="Folder">${d.crumbs.map((c, i) => `${i && d.crumbs[i - 1].name !== "/" ? `<span aria-hidden="true">/</span>` : ""}<button type="button" class="linkbtn" data-fpath="${esc(c.path)}">${esc(c.name)}</button>`).join("")}
      <button type="button" class="btn small" data-fpath="${esc(d.home)}" style="margin-left:auto">Home</button></div>
    <div class="fblist" role="list">${d.parent ? `<button type="button" class="fbitem" data-fpath="${esc(d.parent)}" role="listitem">↑ ..</button>` : ""}
      ${d.folders.map(n => `<button type="button" class="fbitem" data-fpath="${esc(joinPath(d.path, n))}" role="listitem">${esc(n)}</button>`).join("") || `<div class="hint" style="padding:6px 8px">No folders in here.</div>`}
      ${d.truncated ? `<div class="hint" style="padding:6px 8px">Only the first ${d.folders.length}: type the path instead.</div>` : ""}</div>
    <div class="fbfoot"><label class="check"><input type="checkbox" class="fbhidden" ${hidden ? "checked" : ""}> Show hidden folders</label><span class="grow"></span>
      <button type="button" class="btn small" data-fbclose>Cancel</button><button type="button" class="btn small primary" data-fbuse="${esc(d.path)}">Use ${esc(d.crumbs[d.crumbs.length - 1].name)}</button></div>`;
  box.onclick = e => {
    const t = /** @type {HTMLElement} */ (e.target);
    const go = t.closest("[data-fpath]");
    if (go) return browseFolder(id, go.dataset.fpath, $(".fbhidden", box).checked);
    if (t.closest("[data-fbclose]")) { box.hidden = true; return input.focus(); }
    const use = t.closest("[data-fbuse]");
    if (use) { input.value = use.dataset.fbuse; input.dispatchEvent(new Event("input", { bubbles: true })); box.hidden = true; input.focus(); }
  };
  $(".fbhidden", box).onchange = e => browseFolder(id, d.path, e.target.checked);
  $(".fbitem", box)?.focus();
}
document.addEventListener("click", e => { const b = e.target.closest?.("[data-choose]"); if (b) chooseFolder(b.dataset.choose, b.dataset.prompt); });

async function doRelink(r, pid) {
  pid = pid || Object.keys(r.in)[0];
  let cands = [];
  try { cands = r.path ? await api("/api/candidates?fresh=1&name=" + encodeURIComponent(basename(r.path))) : []; } catch {}
  const res = await modal({ title: "Relink to a folder", sub: `<code>${esc(r.pretty)}</code> no longer exists. Tell where the project is now: conversations, memories, history and settings will follow${Object.keys(r.in).length > 1 ? ` (profile ${esc(label(pid))})` : ""}.`,
    body: `${cands.length ? `<div class="hint">Folders with the same name:</div>${cands.map(c => `<button class="btn small" data-pick="${esc(c)}" style="text-align:left;white-space:normal"><code>${esc(c)}</code></button>`).join("")}` : `<div class="hint">No folder with the same name was found.</div>`}
      ${folderField("relink-path", cands[0] || "", "~/code/…", "New folder of the project")}`,
    actions: [{ label: "Relink", kind: "primary", value: "ok" }] });
  if (!res) return;
  const path = $("#relink-path", res.el)?.value || "";
  await run(() => api("/api/projects/relink", { project: r.name, profile: pid, path })); await refresh();
}
// Merge a project whose folder is gone into another project of the same profile: the same as
// relinking it to that project's folder, picked from a list instead of the disk.
async function doMerge(r, pid) {
  pid = pid || Object.keys(r.in)[0];
  const base = r.path ? basename(r.path) : "";
  const targets = S.projects.filter(p => p.name !== r.name && p.exists && p.path && p.in[pid])
    .sort((a, b) => Number(basename(b.path) === base) - Number(basename(a.path) === base) || a.pretty.localeCompare(b.pretty));
  if (!targets.length) { toast(`${label(pid)} has no other project on disk to merge into.`, "", true); return; }
  const resP = modal({ title: "Merge into another project",
    sub: `<code>${esc(r.pretty)}</code> no longer exists. Its conversations, memories, prompt history and settings go into the project you pick, in ${esc(label(pid))}; nothing is deleted.`,
    body: `<input class="text" id="mg-q" placeholder="Filter projects…" aria-label="Filter projects" autocomplete="off">
      <div class="mglist" role="radiogroup" aria-label="Project to merge into">${targets.map((t, i) => `<label class="mgitem" data-mg="${esc(t.pretty.toLowerCase())}">
        <input type="radio" name="mg" value="${esc(t.name)}" ${i ? "" : "checked"}><span class="mono grow">${esc(t.pretty)}</span>
        <span class="hint">${t.in[pid].conv} conv · ${t.in[pid].mem} mem${basename(t.path) === base ? " · same name" : ""}</span></label>`).join("")}</div>`,
    actions: [{ label: "Continue", kind: "primary", value: "ok" }] });
  $("#mg-q").oninput = e => {
    const q = e.target.value.trim().toLowerCase();
    document.querySelectorAll("[data-mg]").forEach(l => { l.hidden = !!q && !l.dataset.mg.includes(q); });
  };
  const res = await resP;
  if (!res) return;
  const into = $('input[name="mg"]:checked', res.el)?.value;
  if (!into) return;
  let pl;
  try { pl = await api(`/api/projects/merge/preview?project=${encodeURIComponent(r.name)}&profile=${encodeURIComponent(pid)}&into=${encodeURIComponent(into)}`); }
  catch (e) { toast(e.message, "", true); return; }
  const clash = pl.conflicts.length ? `<div class="danger-box" style="margin-top:10px">${plural(pl.conflicts.length, "file is", "files are")} already in the target, which keeps its own; the originals go to the backup: ${pl.conflicts.slice(0, 8).map(c => `<code>${esc(c)}</code>`).join(", ")}${pl.conflicts.length > 8 ? "…" : ""}</div>` : "";
  if (!(await confirmBox(`Merge into ${pl.into}?`, `From <code>${esc(pl.from)}</code> into <code>${esc(pl.into)}</code>: ${plural(pl.conversations, "conversation", "conversations")}, ${plural(pl.memories, "memory", "memories")}${pl.memories ? " (with their MEMORY.md lines)" : ""} and ${plural(pl.prompts, "prompt", "prompts")} of the history, and the project settings. Everything goes to the backup first.${clash}`, "Merge"))) return;
  try { await run(() => api("/api/projects/merge", { project: r.name, profile: pid, into })); } catch { return; }
  await refresh();
}
async function doDelete(r, pid) {
  const s = r.in[pid];
  if (!(await confirmBox(`Delete from ${label(pid)}?`, `<code>${esc(r.pretty)}</code><br>${plural(s.conv, "conversation", "conversations")} and ${plural(s.mem, "memory", "memories")} are moved to the backup, not erased.`, "Delete"))) return;
  await run(() => api("/api/projects/delete", { project: r.name, profile: pid })); await refresh();
}
async function doRule(r) {
  const guess = r.path ? r.path.replace(/^~\//, "") : "";
  const res = await modal({ title: "Assign to a profile",
    sub: "Creates a rule: every project whose path contains this text belongs to the chosen profile. New rules win over older ones.",
    body: `<input class="text" value="${esc(guess)}" placeholder="e.g. code/work" aria-label="Path text">
      <select id="rp" aria-label="Profile">${[...S.profiles.map(p => [p.id, p.label]), ["shared", "Shared (all profiles)"]].map(([k, l]) => `<option value="${k}" ${k === r.expected ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`,
    actions: [{ label: "Save rule", kind: "primary", value: "ok" }] });
  if (!res) return;
  await run(() => api("/api/rules", { match: $("input.text", res.el).value, profile: $("#rp", res.el).value })); await refresh();
}
async function doManage(r) {
  const ids = S.profiles.map(p => p.id);
  const opts = [];
  for (const pid of Object.keys(r.in)) {
    const s = r.in[pid];
    for (const to of ids.filter(x => x !== pid)) opts.push({ label: `Move from ${label(pid)} to ${label(to)}`, info: `${s.conv} conv · ${s.mem} mem`, v: ["move", pid, to] });
    if (!r.exists) opts.push({ label: `Relink to a folder (${label(pid)})`, info: "", v: ["relink", pid] });
    if (r.exists && S.term?.supported) opts.push({ label: `Open in ${S.term.terminal} with Claude Code in ${label(pid)}`, info: "", v: ["term", pid] });
    opts.push({ label: `Delete from ${label(pid)}`, info: "goes to the backup", v: ["delete", pid], danger: true });
  }
  opts.push({ label: "Assign to a profile (rule)", info: r.expected ? "now: " + label(r.expected) : "unassigned", v: ["rule"] });
  const res = await modal({ title: "Manage project", sub: `<code>${esc(r.pretty)}</code>`,
    body: opts.map((o, i) => `<div class="opt"><span>${esc(o.label)} <span class="hint">${esc(o.info)}</span></span>
      <button class="btn small ${o.danger ? "danger" : ""}" data-i="${i}">Choose</button></div>`).join(""),
    actions: opts.map(o => ({ label: "", value: o.v })) });
  if (!res) return;
  const [a, p1, p2] = res.action;
  if (a === "move") return doMove(r, p1, p2);
  if (a === "relink") return doRelink(r, p1);
  if (a === "delete") return doDelete(r, p1);
  if (a === "rule") return doRule(r);
  if (a === "term") return doTerminal(r, p1);
}

// ---------- open a project in a terminal (macOS and Linux) ----------
// The server writes a small script and the terminal opens it: Claude Code starts in the project's
// folder, in the profile picked here. The terminal is chosen in the About panel.
async function doTerminal(r, pid) {
  const ids = Object.keys(r.in);
  if (!pid && ids.length > 1) {
    const res = await modal({ title: `Open in ${S.term.terminal}`, sub: `<code>${esc(r.pretty)}</code><br>Claude Code starts in this folder, in the profile you pick.`,
      body: `<select id="tp" aria-label="Profile">${ids.map(id => `<option value="${esc(id)}">${esc(label(id))}</option>`).join("")}</select>`,
      actions: [{ label: "Open", kind: "primary", value: "ok" }] });
    if (!res) return;
    pid = $("#tp", res.el).value;
  }
  try { await run(() => api("/api/terminal/open", { project: r.name, profile: pid || ids[0] })); } catch {}
}

// ---------- files dropped on the page ----------
// A profile .zip opens Import. A folder opens Relink, in the Mac app only: a browser never tells
// a page where a folder is. The Mac app also passes on what is dropped on its Dock icon.
const IN_APP = navigator.userAgent.includes("cc-profiles-app");
const APP_TAB = "cc-profiles.app-tab";
const draggingFiles = e => [...(e.dataTransfer?.types || [])].includes("Files") && !e.target.closest?.('input[type="file"]');
document.addEventListener("dragover", e => { if (draggingFiles(e)) e.preventDefault(); });
document.addEventListener("drop", e => {
  if (!draggingFiles(e)) return;
  e.preventDefault();
  const zip = [...e.dataTransfer.files].find(f => /\.zip$/i.test(f.name));
  if (zip) importProfile(zip);
  else toast("Drop the .zip of an exported profile to import it", IN_APP ? "or a project's new folder to relink it" : "", true);
});
window.ccDropZip = (name, b64) => importProfile(new File([Uint8Array.from(atob(b64), c => c.charCodeAt(0))], name, { type: "application/zip" }));
window.ccDropFolder = async path => {
  const lost = S.projects.filter(r => !r.exists);
  if (!lost.length) return toast("No project needs relinking", `every project's folder is where it was: ${path}`);
  const base = basename(path);
  lost.sort((a, b) => Number(basename(b.path) === base) - Number(basename(a.path) === base) || a.pretty.localeCompare(b.pretty));
  const res = await modal({ title: "Relink a project to this folder",
    sub: `<code>${esc(path)}</code><br>Pick the project that now lives here: its conversations, memories, history and settings follow.`,
    body: `<div class="mglist" role="radiogroup" aria-label="Project to relink">${lost.map((r, i) => `<label class="mgitem">
      <input type="radio" name="rl" value="${esc(r.name)}" ${i ? "" : "checked"}><span class="mono grow">${esc(r.pretty)}</span>
      <span class="hint">${basename(r.path) === base ? "same name" : ""}</span></label>`).join("")}</div>`,
    actions: [{ label: "Relink", kind: "primary", value: "ok" }] });
  if (!res) return;
  const r = byName(res.el.querySelector('input[name="rl"]:checked')?.value);
  if (!r) return;
  await run(() => api("/api/projects/relink", { project: r.name, profile: Object.keys(r.in)[0], path })); await refresh();
};

// ---------- memories ----------
async function loadMemProjects() {
  S.mem.projects = await api("/api/memory/projects?profile=" + S.mem.profile);
}
async function openMemProject(name) {
  S.mem.project = name; S.mem.file = null; S.mem.list = null; renderMemories();
  S.mem.list = await api(`/api/memory/list?profile=${S.mem.profile}&project=${encodeURIComponent(name)}`);
  renderMemories();
}
async function openMemFile(f) {
  S.mem.file = f;
  const r = await api(`/api/memory/file?profile=${S.mem.profile}&project=${encodeURIComponent(S.mem.project)}&file=${encodeURIComponent(f)}`);
  S.mem.content = r.content; renderMemories();
}
function renderMemories() {
  const m = S.mem;
  const q = m.q.toLowerCase();
  const plist = m.projects.filter(p => (m.all || p.count > 0) && (!q || p.pretty.toLowerCase().includes(q)));
  const cur = m.projects.find(p => p.name === m.project);
  $("#main").innerHTML = `<div class="memgrid">
    <aside class="side"><div class="head">
      <div class="seg">${S.profiles.map(p => `<button data-mprof="${p.id}" class="${m.profile === p.id ? "on" : ""}">${esc(p.label)}</button>`).join("")}</div>
      <input class="search" style="min-width:0;margin:0" placeholder="Filter projects…" value="${esc(m.q)}" id="mq" aria-label="Filter projects">
      <label class="check"><input type="checkbox" id="mall" ${m.all ? "checked" : ""}> also show projects without memories</label></div>
      <div class="plist">${plist.map(p => `<button data-mproj="${esc(p.name)}" class="${p.name === m.project ? "on" : ""}">
        <span class="p">${esc(p.pretty)}</span>${p.shared ? `<span class="badge b-shared">shared</span>` : ""}<span class="n">${p.count}</span></button>`).join("") || `<div class="empty">No projects.</div>`}</div>
    </aside>
    <section>${!cur ? `<div class="empty">Pick a project on the left.</div>` : `
      <div class="hint" style="margin-bottom:8px"><code>${esc(cur.pretty)}</code> · ${esc(label(m.profile))}</div>
      ${!m.list ? `<div class="empty">${LOADER}</div>` : `
        ${memSharing(m.list.sharing)}
        ${m.list.missing.length ? `<div class="issue err" style="margin-bottom:8px">MEMORY.md lists files that do not exist: ${m.list.missing.map(esc).join(", ")}</div>` : ""}
        <div class="cards">${m.list.items.map(it => `<div class="mcard ${it.file === m.file ? "on" : ""}" data-mfile="${esc(it.file)}" tabindex="0" role="button">
          <div class="t">${esc(it.name)} ${it.type ? `<span class="badge b-none">${esc(it.type)}</span>` : ""}
            ${it.indexed ? "" : `<span class="badge b-warn">not in MEMORY.md</span>`}</div>
          <div class="d">${esc(it.description)}</div></div>`).join("") || `<div class="empty">No memories in this project.</div>`}</div>
        ${m.file ? `<div class="editor"><div class="hint" style="margin-bottom:6px"><code>${esc(m.file)}</code></div>
          <textarea id="mtext" spellcheck="false" aria-label="Memory content">${esc(m.content)}</textarea>
          <div class="row"><span class="grow">Saving keeps a copy of the previous version.</span>
            <button class="btn danger" id="mdel">Delete</button><button class="btn" id="mmove">Move…</button>
            <button class="btn primary" id="msave">Save</button></div></div>` : ""}`}`}
    </section></div>`;
  $("#mq").oninput = e => { m.q = e.target.value; const pos = e.target.selectionStart; renderMemories(); const i = $("#mq"); i.focus(); i.setSelectionRange(pos, pos); };
  $("#mall").onchange = e => { m.all = e.target.checked; renderMemories(); };
  if ($("#msave")) {
    const ctx = () => ({ profile: m.profile, project: m.project, file: m.file });
    $("#msave").onclick = async () => { await run(() => api("/api/memory/save", { ...ctx(), content: $("#mtext").value })); m.content = $("#mtext").value; };
    $("#mdel").onclick = async () => {
      if (!(await confirmBox("Delete this memory?", `<code>${esc(m.file)}</code> is removed from MEMORY.md and moved to the backup.`, "Delete"))) return;
      await run(() => api("/api/memory/delete", ctx())); m.file = null; await loadMemProjects(); await openMemProject(m.project); loadProfiles();
    };
    $("#mmove").onclick = () => moveMemory(ctx());
  }
  if ($("#mshare")) $("#mshare").onclick = () => shareMemory();
  for (const b of $("#main").querySelectorAll("[data-mshare-off]")) b.onclick = () => separateMemory(b.dataset.mshareOff);
}
// Shared memory: other profiles use this profile's memory of the project, or this one uses another's
function memSharing(sh) {
  if (!sh) return "";
  if (sh.from) return `<div class="memshare">Shared: the same memories as ${badge(sh.from)}
    <button class="btn small" data-mshare-off="${esc(S.mem.profile)}">Separate</button></div>`;
  const free = sh.others.filter(o => !o.elsewhere);
  if (!sh.with.length && !free.length) return "";
  return `<div class="memshare">${sh.with.length ? `Shared with ${sh.with.map(id => `${badge(id)}
      <button class="btn small" data-mshare-off="${esc(id)}" aria-label="Stop sharing with ${esc(label(id))}">Stop sharing</button>`).join(" ")}`
    : "Only this profile uses these memories."}
    ${free.length ? `<button class="btn small" id="mshare">Share with…</button>` : ""}</div>`;
}
async function shareMemory() {
  const m = S.mem, free = m.list.sharing.others.filter(o => !o.elsewhere);
  const plan = async id => api(`/api/memory/share-plan?profile=${id}&project=${encodeURIComponent(m.project)}&from=${m.profile}`);
  const says = p => {
    let t = `${esc(p.profile)} will read and write these memories: what Claude learns in one profile, the other sees too.`;
    if (p.join.length) t += ` Its own ${p.join.length} ${p.join.length === 1 ? "memory joins" : "memories join"} them.`;
    if (p.conflicts.length) t += ` ${p.conflicts.length} with a name already here (${p.conflicts.map(esc).join(", ")}) ${p.conflicts.length === 1 ? "goes" : "go"} to the backup.`;
    return t;
  };
  let p = await plan(free[0].id);
  const resP = modal({ title: "Share memory", sub: `<code>${esc(m.projects.find(x => x.name === m.project)?.pretty || m.project)}</code>, from ${esc(label(m.profile))}`,
    body: `<select id="msp" aria-label="Profile">${free.map(o => `<option value="${esc(o.id)}">${esc(label(o.id))}</option>`).join("")}</select>
      <p class="hint" id="msplan">${says(p)}</p>`,
    actions: [{ label: "Share", kind: "primary", value: "ok" }] });
  const sel = $("#msp");
  sel.onchange = async () => {  // the dialog may be gone when the answer comes
    p = await plan(sel.value); const el = $("#msplan"); if (el) el.innerHTML = says(p);
  };
  const res = await resP;
  if (!res) return;
  await run(() => api("/api/memory/share", { profile: $("#msp", res.el).value, project: m.project, from: m.profile, shared: true }));
  await loadMemProjects(); await openMemProject(m.project); loadProfiles();
}
async function separateMemory(pid) {
  const m = S.mem;
  if (!(await confirmBox(`Separate the memory of ${label(pid)}?`,
      `${esc(label(pid))} gets its own copy of these memories: from now on changes in one profile no longer reach the other.`, "Separate"))) return;
  await run(() => api("/api/memory/share", { profile: pid, project: m.project, shared: false }));
  await loadMemProjects(); await openMemProject(m.project); loadProfiles();
}
async function moveMemory(ctx) {
  const projFor = async pid => (await api("/api/memory/projects?profile=" + pid));
  let list = await projFor(ctx.profile);
  const opts = l => l.map(p => `<option value="${esc(p.name)}">${esc(p.pretty)}${p.count ? ` (${p.count})` : ""}</option>`).join("");
  const resP = modal({ title: "Move memory", sub: `<code>${esc(ctx.file)}</code>`,
    body: `<select id="mvp" aria-label="Target profile">${S.profiles.map(p => `<option value="${p.id}" ${p.id === ctx.profile ? "selected" : ""}>${esc(p.label)}</option>`).join("")}</select>
      <select id="mvj" aria-label="Target project">${opts(list)}</select>`,
    actions: [{ label: "Move", kind: "primary", value: "ok" }] });
  const sel = $("#mvp");
  sel.onchange = async () => { list = await projFor(sel.value); $("#mvj").innerHTML = opts(list); };
  const res = await resP;
  if (!res) return;
  await run(() => api("/api/memory/move", { ...ctx, to_profile: $("#mvp", res.el).value, to_project: $("#mvj", res.el).value }));
  S.mem.file = null; await loadMemProjects(); await openMemProject(ctx.project); loadProfiles();
}

// ---------- conversations ----------
async function loadConvProjects() {
  S.conv.projects = await api("/api/conversations/projects?profile=" + S.conv.profile);
}
async function openConvProject(name) {
  const c = S.conv;
  Object.assign(c, { project: name, list: null, session: null, view: null }); renderConversations();
  c.list = await api(`/api/conversations?profile=${c.profile}&project=${encodeURIComponent(name)}`);
  renderConversations();
}
async function openConversation(session) {
  const c = S.conv;
  Object.assign(c, { session, view: null }); renderConversations();
  c.view = await api(`/api/conversations/view?profile=${c.profile}&project=${encodeURIComponent(c.project)}&session=${encodeURIComponent(session)}`);
  renderConversations();
}
const convDate = c => new Date(c.last || c.mtime * 1000).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const openWarning = ids => {
  const open = S.profiles.filter(p => ids.includes(p.id) && p.active).map(p => esc(p.label));
  return open.length ? `<div class="danger-box" style="margin-top:10px">A Claude Code session is open in ${open.join(" and ")}: if it is this conversation, it keeps writing to it. Close it first.</div>` : "";
};
function renderConversations() {
  if (S.tab !== "conversations") return;
  const c = S.conv, q = c.q.toLowerCase();
  const plist = c.projects.filter(p => !q || p.pretty.toLowerCase().includes(q));
  const cur = c.list?.conversations.find(x => x.session === c.session);
  $("#main").innerHTML = `<div class="memgrid">
    <aside class="side"><div class="head">
      <div class="seg">${S.profiles.map(p => `<button data-cprof="${p.id}" class="${c.profile === p.id ? "on" : ""}">${esc(p.label)}</button>`).join("")}</div>
      <input class="search" style="min-width:0;margin:0" placeholder="Filter projects…" value="${esc(c.q)}" id="cq" aria-label="Filter projects"></div>
      <div class="plist">${plist.map(p => `<button data-cproj="${esc(p.name)}" class="${p.name === c.project ? "on" : ""}">
        <span class="p">${esc(p.pretty)}</span><span class="n">${p.count}</span></button>`).join("") || `<div class="empty">No conversations in this profile.</div>`}</div>
    </aside>
    <section>${!c.project ? `<div class="empty">Pick a project on the left.</div>` : !c.list ? `<div class="empty">${LOADER}</div>` : `
      <div class="hint" style="margin-bottom:8px"><code>${esc(c.list.path)}</code> · ${esc(label(c.profile))} · ${plural(c.list.conversations.length, "conversation", "conversations")}</div>
      <div class="cards">${c.list.conversations.map(x => `<div class="ccard ${x.session === c.session ? "on" : ""}" data-conv="${esc(x.session)}" tabindex="0" role="button">
        <div class="t">${esc(x.title) || `<span class="hint">No prompt</span>`}</div>
        <div class="d">${esc(convDate(x))} · ${plural(x.prompts, "prompt", "prompts")} · ${plural(x.replies, "reply", "replies")} · ${size(x.size)}</div></div>`).join("")}</div>
      ${cur ? `<div class="editor">
        <div class="hint" style="margin-bottom:6px"><code>${esc(cur.session)}.jsonl</code>${cur.snapshots ? " · with file snapshots" : ""}</div>
        ${!c.view ? `<div class="empty">${LOADER}</div>` : `
          ${c.view.truncated ? `<div class="hint">Shortened: the last ${plural(c.view.messages.length, "message", "messages")} of ${c.view.total}, long texts cut.</div>` : ""}
          <div class="convview">${c.view.messages.map(m => `<div class="msg ${m.role}"><div class="who">${{ user: "You", assistant: "Claude", tool: "Tool" }[m.role]}${m.time ? `<time>${esc(new Date(m.time).toLocaleString())}</time>` : ""}</div>
            <div class="txt">${esc(m.text)}</div></div>`).join("") || `<div class="empty">No messages to show.</div>`}</div>`}
        <div class="row"><span class="grow">Read-only. Moving takes the conversation and its file snapshots; the prompt history stays.</span>
          <button class="btn danger" id="cdel">Delete</button><button class="btn" id="cmove">Move to…</button></div></div>` : ""}`}
    </section></div>`;
  $("#cq").oninput = e => { c.q = e.target.value; const pos = e.target.selectionStart; renderConversations(); const i = $("#cq"); i.focus(); i.setSelectionRange(pos, pos); };
  document.querySelectorAll("[data-cprof]").forEach(b => b.onclick = async () => {
    Object.assign(c, { profile: b.dataset.cprof, project: null, list: null, session: null, view: null });
    await loadConvProjects(); renderConversations();
  });
  document.querySelectorAll("[data-cproj]").forEach(b => b.onclick = () => openConvProject(b.dataset.cproj));
  document.querySelectorAll("[data-conv]").forEach(el => {
    el.onclick = () => openConversation(el.dataset.conv);
    el.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openConversation(el.dataset.conv); } };
  });
  if (!cur) return;
  const ctx = { profile: c.profile, project: c.project, session: c.session };
  const after = async () => { c.session = null; c.view = null; await loadConvProjects(); if (c.projects.some(p => p.name === c.project)) await openConvProject(c.project); else { c.project = null; renderConversations(); } refresh(); };
  $("#cmove").onclick = async () => {
    const to = await pickProfile("Move conversation", `<b>${esc(cur.title || cur.session)}</b> moves to the same project in the other profile, with its file snapshots. The prompt history stays where it is.${openWarning([c.profile])}`, c.profile, "Move");
    if (!to) return;
    if (S.profiles.find(p => p.id === to)?.active && !(await confirmBox("A session is open there", openWarning([to]) + "Move anyway?", "Move"))) return;
    try { await run(() => api("/api/conversations/move", { ...ctx, to })); } catch { return; }
    after();
  };
  $("#cdel").onclick = async () => {
    if (!(await confirmBox("Delete this conversation?", `<b>${esc(cur.title || cur.session)}</b> and its file snapshots go to the backup, not erased.${openWarning([c.profile])}`, "Delete", "danger"))) return;
    try { await run(() => api("/api/conversations/delete", ctx)); } catch { return; }
    after();
  };
}

// ---------- health ----------
async function loadHealth(fresh, quiet) {  // fresh: search the folders again; quiet: no loader, redraw only a change
  const before = quiet && JSON.stringify(S.health);
  if (!quiet) { S.health = null; renderHealth(); }
  S.health = await api("/api/health" + (fresh === true ? "?fresh=1" : ""));
  if (quiet && JSON.stringify(S.health) === before) return;
  const n = S.health.reduce((a, h) => a + h.checks.filter(c => c.level === "error").length + h.orphans.length, 0);
  const c = $("#cnt-health"); c.hidden = !n; c.textContent = n; syncNav();
  renderHealth();
}
function renderHealth() {
  if (S.tab !== "health") return;
  if (!S.health) { $("#main").innerHTML = `<div class="empty">${LOADER} Checking login, files, links, skills, plugins, memories and folders…</div>`; return; }
  const icon = { ok: "✓", warn: "!", error: "✕" };
  $("#main").innerHTML = `<div class="toolbar"><button class="btn" id="rehealth">Run the checks again</button></div>
    <div class="health">${S.health.map(h => `<div class="hcard"><h2>${esc(h.label)}</h2>
      ${h.checks.map(c => `<div class="check ${c.level}"><span class="i" aria-hidden="true">${icon[c.level]}</span><span>${esc(c.text)}</span></div>`).join("")}
      <h3>Projects whose folder is gone (${h.orphans.length})</h3>
      ${h.orphans.map(o => `<div class="orphan"><div class="p">${esc(o.pretty)}</div>
        <div class="hint">${plural(o.conv, "conversation", "conversations")} · ${plural(o.mem, "memory", "memories")}</div>
        <div class="c">${o.candidates.map(c => `<button class="btn small primary" data-hlink="${esc(o.name)}" data-prof="${h.id}" data-path="${esc(c)}">Relink to ${esc(c)}</button>`).join("")}
          <button class="btn small" data-hrelink="${esc(o.name)}" data-prof="${h.id}">Relink…</button>
          <button class="btn small" data-hmerge="${esc(o.name)}" data-prof="${h.id}">Merge into…</button>
          <button class="btn small danger" data-hdel="${esc(o.name)}" data-prof="${h.id}">Delete</button></div></div>`).join("") || `<div class="hint">None. ✓</div>`}
    </div>`).join("")}</div>`;
  $("#rehealth").onclick = () => loadHealth(true);
}
