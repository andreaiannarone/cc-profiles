// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Andrea Iannarone
// Settings, status line, theme.

// ---------- settings ----------
// Reloading the same profile keeps the page where it is: no spinner, same scroll.
async function loadSettings(pid) {
  const same = S.set?.profile === pid && S.set.data, y = window.scrollY;
  if (!same) { S.set = { profile: pid, data: null, rawFile: S.set?.rawFile || "settings", draft: {} }; renderSettings(); }
  try {
    const [data, sl] = await Promise.all([api("/api/settings?profile=" + pid), api("/api/statusline?profile=" + pid)]);
    Object.assign(S.set, { data, sl, draft: same ? S.set.draft || {} : {} });
    slDraft();
  } catch (e) { toast(e.message, "", true); }
  renderSettings();
  if (same) window.scrollTo(0, y);
}
window.addEventListener("beforeunload", e => { if (S.set?.data && genChanged().length) { e.preventDefault(); e.returnValue = ""; } });
// General: changes wait in a draft (key → the value to send) until Save changes.
// reqOf turns a stored value into that form, so an edit undone by hand is no change.
function reqOf(f, v) {
  if (f.off_value !== undefined) return v === f.off_value ? false : v == null ? true : v;
  if (f.type === "bool" && v == null && f.default !== undefined) return f.default;
  return v ?? null;
}
function storedOf(f, r) {  // the reverse, to draw a draft value
  if (f.off_value !== undefined) return r === false ? f.off_value : r === true ? null : r;
  return r;
}
const genChanged = () => Object.keys(S.set.draft).filter(k => { const f = S.set.data.fields.find(x => x.key === k); return f && JSON.stringify(S.set.draft[k]) !== JSON.stringify(reqOf(f, f.value)); });
function genMark() {
  const keys = genChanged();
  document.querySelectorAll("[data-srow]").forEach(r => r.classList.toggle("changed", keys.includes(r.dataset.srow)));
  const bar = $("#gen-bar"); if (!bar) return;
  bar.hidden = !keys.length;
  $("#gen-count").textContent = plural(keys.length, "unsaved change", "unsaved changes");
}
function genRedraw() {  // after a reset or a copy: redraw in place
  const y = window.scrollY; renderSettings(); window.scrollTo(0, y);
}

// ---------- status line ----------
// The draft holds what the form shows until it is saved; switching mode re-renders only this section.
function slDraft() {
  const sl = S.set.sl, v = sl.value || {};
  const ids = sl.parts_available.map(p => p.id), saved = sl.parts.map(x => x.split(":"));
  const parts = saved.map(([id]) => id).filter(id => ids.includes(id));
  const brackets = Object.fromEntries(sl.parts_available.map(p => [p.id, p.brackets]));
  saved.forEach(([id, br]) => { if (br) brackets[id] = br; });
  S.set.slDraft = { mode: sl.mode, parts, order: [...parts, ...ids.filter(i => !parts.includes(i))], brackets,
                    separator: sl.separator, colors: sl.colors, limits: sl.limits || "used", command: sl.mode === "custom" ? v.command || "" : "",
                    padding: v.padding ?? "", refreshInterval: v.refreshInterval ?? "", hide: v.hideVimModeIndicator === true };
  S.set.slSaved = slKey(S.set.slDraft);
}
// What decides whether there is something to save: the order of unticked parts does not count.
const slKey = dr => JSON.stringify(dr.mode === "off" ? { mode: "off" } : {
  mode: dr.mode, parts: dr.mode === "builtin" ? slParts(dr) : null,
  separator: dr.mode === "builtin" ? dr.separator : null, colors: dr.mode === "builtin" ? dr.colors : null,
  limits: dr.mode === "builtin" ? dr.limits : null,
  command: dr.mode === "custom" ? dr.command.trim() : null, padding: String(dr.padding ?? ""), refresh: String(dr.refreshInterval ?? ""), hide: dr.hide });
// The ticked parts in line order, each with its brackets: "model:square".
const slParts = dr => dr.order.filter(i => dr.parts.includes(i)).map(i => `${i}:${dr.brackets[i]}`);
// SGR escapes (bold, dim, the 8 colors and grey) to spans; everything else is text.
function ansiHtml(text) {
  let out = "", open = 0;
  for (const piece of text.split(/(\x1b\[[0-9;]*m)/)) {
    const m = piece.match(/^\x1b\[([0-9;]*)m$/);
    if (!m) { out += esc(piece); continue; }
    const codes = m[1].split(";").filter(Boolean);
    if (!codes.length || codes.includes("0")) { out += "</span>".repeat(open); open = 0; continue; }
    const cls = codes.map(c => c === "1" ? "b" : c === "2" ? "d" : /^(3[1-7]|90)$/.test(c) ? "a" + c : "").filter(Boolean).join(" ");
    out += `<span class="${cls}">`; open++;
  }
  return out + "</span>".repeat(open);
}
// A preset fills the draft (nothing is saved): it is "on" while the draft is exactly that preset.
const slPresetOn = (dr, p) => slParts(dr).join(",") === p.parts.join(",") && dr.separator === p.separator && dr.colors === p.colors && dr.limits === p.limits;
function slApplyPreset(p) {
  const dr = S.set.slDraft, ids = p.parts.map(x => x.split(":")[0]);
  dr.parts = ids;
  dr.order = [...ids, ...dr.order.filter(i => !ids.includes(i))];
  S.set.sl.parts_available.forEach(x => { dr.brackets[x.id] = p.brackets || x.brackets; });
  p.parts.forEach(x => { const [id, br] = x.split(":"); dr.brackets[id] = br; });
  Object.assign(dr, { separator: p.separator, colors: p.colors, limits: p.limits });
}
const slBr = (sl, br, text) => { const b = sl.brackets.find(x => x.id === br); return b ? b.left + text + b.right : text; };
function statusLineSection() {
  const st = S.set, sl = st.sl, dr = st.slDraft;
  if (!sl) return "";
  const where = sl.value ? `Now: ${sl.mode === "builtin" ? "made by cc-profiles" : "your command"}, in ${srcBadge(sl.source)}` : "Now: off";
  const byId = Object.fromEntries(sl.parts_available.map(p => [p.id, p]));
  const dirty = slKey(dr) !== st.slSaved;
  return `<section class="sec" id="sl-sec"><div class="h"><h2>Status line</h2><span class="hint">The line Claude Code shows under the prompt. ${where}</span></div>
    <div class="b">
      <div class="seg" style="max-width:460px" role="group" aria-label="Status line">${[["off", "Off"], ["builtin", "Made by cc-profiles"], ["custom", "Your command"]].map(([m, l]) =>
        `<button data-slmode="${m}" class="${dr.mode === m ? "on" : ""}" aria-pressed="${dr.mode === m}">${l}</button>`).join("")}</div>
      ${dr.mode === "builtin" ? `
        ${sl.presets?.length ? `<div class="slpresets" role="group" aria-label="Presets"><span class="hint">Presets</span>${sl.presets.map(p => { const on = slPresetOn(dr, p); return `<button class="chip ${on ? "on" : ""}" data-slpreset="${p.id}" aria-pressed="${on}" title="${esc(p.description)}">${esc(p.label)}</button>`; }).join("")}</div>` : ""}
        <div class="slgrid">
          <ul class="slparts" aria-label="What to show, in order: drag or use the arrows">${dr.order.map((id, i) => { const p = byId[id], on = dr.parts.includes(id); return `
            <li class="${on ? "" : "off"}" draggable="true" data-slitem="${id}">
              <span class="grip" aria-hidden="true">⋮⋮</span>
              <label><input type="checkbox" data-slpart="${id}" ${on ? "checked" : ""}> ${esc(p.label)}</label>
              <select class="slbr" data-slbr="${id}" aria-label="Brackets around ${esc(p.label)}">${sl.brackets.map(b => `<option value="${b.id}" ${dr.brackets[id] === b.id ? "selected" : ""}>${b.id === "none" ? "no brackets" : esc(b.left + "…" + b.right)}</option>`).join("")}</select>
              <span class="smp">${esc(slBr(sl, dr.brackets[id], dr.limits === "left" && p.sample_left || p.sample))}</span>
              <span class="mv"><button class="btn small" data-slmove="${id}" data-dir="-1" ${i === 0 ? "disabled" : ""} aria-label="Move ${esc(p.label)} up">↑</button><button class="btn small" data-slmove="${id}" data-dir="1" ${i === dr.order.length - 1 ? "disabled" : ""} aria-label="Move ${esc(p.label)} down">↓</button></span>
            </li>`; }).join("")}</ul>
          <div class="slside">
            <div class="f">Separator<div class="seg slsep" role="group" aria-label="Separator">${sl.separators.map(x => `<button data-slsep="${x.id}" class="${dr.separator === x.id ? "on" : ""}" aria-pressed="${dr.separator === x.id}" aria-label="${x.id === "space" ? "two spaces" : x.id}" title="${x.id === "space" ? "Two spaces" : esc(x.text.trim())}">${esc(x.text.trim() || "␣")}</button>`).join("")}</div></div>
            <div class="f">Brackets: each piece has its own, in its row; or all the same<div class="seg slsep" role="group" aria-label="Brackets for every piece">${sl.brackets.map(b => `<button data-slbrall="${b.id}" aria-label="${b.id === "none" ? "no brackets anywhere" : b.id + " brackets everywhere"}" title="${b.id === "none" ? "No brackets anywhere" : "Use " + esc(b.left + " " + b.right) + " everywhere"}">${b.id === "none" ? "–" : esc(b.left + b.right)}</button>`).join("")}<button data-slbrall="default" title="Back to each piece's own brackets" aria-label="each piece's own brackets">mix</button></div></div>
            <div class="f">Rate limits: used, or left with the time to the reset when half or less is left<div class="seg" style="max-width:240px" role="group" aria-label="Rate limits">${[["used", "Used"], ["left", "Left"]].map(([v, l]) => `<button data-sllim="${v}" class="${dr.limits === v ? "on" : ""}" aria-pressed="${dr.limits === v}">${l}</button>`).join("")}</div></div>
            <label class="c"><input type="checkbox" id="sl-colors" ${dr.colors ? "checked" : ""}> Colors <span class="hint">(your terminal's own; context and limits turn yellow at 70% used, red at 90%)</span></label>
          </div>
        </div>
        <div class="slpreview" id="sl-preview" aria-live="polite" aria-label="Preview with sample data"></div>
        <div class="hint" style="margin-top:6px">Preview with sample data; the branch shows inside a git repository. Saved as <code>${esc(sl.script)}</code>, a shell script that reads Claude Code's data with <code>jq</code>.
          ${sl.jq ? "" : ` <b>jq is not installed</b>: until you install it (<code>brew install jq</code>), the line shows only the profile.`}</div>
        <details class="slscript"><summary>Show the script</summary><pre class="code" id="sl-script"></pre></details>
        ${sl.script_is_other ? `<div class="danger-box" style="margin-top:10px"><code>${esc(sl.script)}</code> was not made by cc-profiles and is never overwritten: rename it to use this, or pick <b>Your command</b> to run it.</div>` : ""}` : ""}
      ${dr.mode === "custom" ? `<div class="slopts" style="margin-top:14px"><label class="f" style="flex:1;min-width:240px">Command<input class="text" style="width:100%" id="sl-cmd" value="${esc(dr.command)}" placeholder="e.g. sh ~/.claude/my-statusline.sh" autocomplete="off" spellcheck="false"></label></div>
        <div class="hint" style="margin-top:6px">Claude Code runs it with the session's data as JSON on stdin and shows what it prints. cc-profiles never runs it.</div>` : ""}
      ${dr.mode !== "off" ? `<div class="slopts">
        <label class="f">Padding<input class="text" type="number" min="0" step="1" id="sl-pad" value="${esc(dr.padding)}" placeholder="0"></label>
        <label class="f">Refresh every (s)<input class="text" type="number" min="1" step="1" id="sl-ref" value="${esc(dr.refreshInterval)}" placeholder="on events"></label>
        <label class="c"><input type="checkbox" id="sl-hide" ${dr.hide ? "checked" : ""}> Hide the vim mode indicator</label></div>` : ""}
      <div class="row-end"><span class="grow hint" id="sl-dirty">${dirty ? "Unsaved changes" : ""}</span><button class="btn" id="sl-all" title="Give every other profile the status line saved in this one">Apply to all…</button><button class="btn primary" id="sl-save" ${dirty ? "" : "disabled"}>Save status line</button></div>
    </div></section>`;
}
function slRead() {
  const dr = S.set.slDraft, num = id => { const v = $(id)?.value; return v === undefined ? undefined : v === "" ? "" : parseInt(v, 10); };
  if (dr.mode === "builtin") { dr.parts = [...document.querySelectorAll("[data-slpart]")].filter(c => c.checked).map(c => c.dataset.slpart); dr.colors = $("#sl-colors").checked; }
  if (dr.mode === "custom") dr.command = $("#sl-cmd").value;
  if (dr.mode !== "off") { dr.padding = num("#sl-pad"); dr.refreshInterval = num("#sl-ref"); dr.hide = $("#sl-hide").checked; }
}
function slDirty() {
  const dirty = slKey(S.set.slDraft) !== S.set.slSaved;
  $("#sl-dirty").textContent = dirty ? "Unsaved changes" : "";
  $("#sl-save").disabled = !dirty;
  document.querySelectorAll("[data-slpreset]").forEach(b => {  // the colors switch changes the draft without a re-render
    const on = slPresetOn(S.set.slDraft, S.set.sl.presets.find(p => p.id === b.dataset.slpreset));
    b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on));
  });
}
let slSeq = 0;
async function slPreview() {
  const box = $("#sl-preview"); if (!box) return;
  const dr = S.set.slDraft, parts = slParts(dr), seq = ++slSeq;
  try {
    const r = await api(`/api/statusline/preview?profile=${S.set.profile}&parts=${encodeURIComponent(parts.join(","))}&separator=${dr.separator}&colors=${dr.colors ? 1 : 0}&limits=${dr.limits}`);
    if (seq !== slSeq || !$("#sl-preview")) return;  // a newer preview is on its way
    $("#sl-preview").innerHTML = parts.length ? ansiHtml(r.text) : `<span class="d">Tick something to show</span>`;
    $("#sl-script").textContent = r.script;
  } catch {}
}
function renderStatusLine(focus) {
  const sec = $("#sl-sec"); if (!sec) return;
  sec.outerHTML = statusLineSection();
  bindStatusLine();
  if (focus) $(focus)?.focus();
}
function bindStatusLine() {
  const st = S.set, pid = st.profile, dr = st.slDraft;
  if (!$("#sl-sec")) return;
  const changed = () => { slRead(); slDirty(); slPreview(); };
  const move = (id, to) => { const o = dr.order.filter(x => x !== id); o.splice(Math.max(0, Math.min(to, o.length)), 0, id); dr.order = o; };
  document.querySelectorAll("[data-slmode]").forEach(b => b.onclick = () => { slRead(); dr.mode = b.dataset.slmode; renderStatusLine(); });
  // a ticked part joins the end of the line, an unticked one leaves it: the list reads in line order
  document.querySelectorAll("[data-slpart]").forEach(c => c.onchange = () => {
    slRead(); const id = c.dataset.slpart, shown = dr.order.filter(x => x !== id && dr.parts.includes(x));
    move(id, shown.length); renderStatusLine(`[data-slpart="${id}"]`);
  });
  document.querySelectorAll("[data-slbr]").forEach(sel => sel.onchange = () => { slRead(); dr.brackets[sel.dataset.slbr] = sel.value; renderStatusLine(`[data-slbr="${sel.dataset.slbr}"]`); });
  document.querySelectorAll("[data-slbrall]").forEach(b => b.onclick = () => {
    slRead(); const v = b.dataset.slbrall;
    st.sl.parts_available.forEach(p => { dr.brackets[p.id] = v === "default" ? p.brackets : v; });
    renderStatusLine(`[data-slbrall="${v}"]`);
  });
  document.querySelectorAll("[data-slpreset]").forEach(b => b.onclick = () => {
    slRead(); slApplyPreset(st.sl.presets.find(p => p.id === b.dataset.slpreset)); renderStatusLine(`[data-slpreset="${b.dataset.slpreset}"]`);
  });
  document.querySelectorAll("[data-slsep]").forEach(b => b.onclick = () => { slRead(); dr.separator = b.dataset.slsep; renderStatusLine(`[data-slsep="${dr.separator}"]`); });
  document.querySelectorAll("[data-sllim]").forEach(b => b.onclick = () => { slRead(); dr.limits = b.dataset.sllim; renderStatusLine(`[data-sllim="${dr.limits}"]`); });
  document.querySelectorAll("[data-slmove]").forEach(b => b.onclick = () => {
    slRead(); const id = b.dataset.slmove, d = +b.dataset.dir;
    move(id, dr.order.indexOf(id) + d);
    const next = `[data-slmove="${id}"][data-dir="${d}"]`;
    renderStatusLine($(next) && !document.querySelector(next)?.disabled ? next : `[data-slpart="${id}"]`);
  });
  let dragged = null;
  document.querySelectorAll("[data-slitem]").forEach(li => {
    li.ondragstart = e => { dragged = li.dataset.slitem; li.classList.add("drag"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragged); };
    li.ondragend = () => { li.classList.remove("drag"); document.querySelectorAll(".slparts li.over").forEach(x => x.classList.remove("over")); };
    li.ondragover = e => { if (!dragged) return; e.preventDefault(); li.classList.add("over"); };
    li.ondragleave = () => li.classList.remove("over");
    li.ondrop = e => {
      e.preventDefault(); if (!dragged || dragged === li.dataset.slitem) return;
      slRead(); move(dragged, dr.order.filter(x => x !== dragged).indexOf(li.dataset.slitem)); dragged = null; renderStatusLine();
    };
  });
  ["#sl-colors", "#sl-hide"].forEach(id => { if ($(id)) $(id).onchange = changed; });
  ["#sl-cmd", "#sl-pad", "#sl-ref"].forEach(id => { if ($(id)) $(id).oninput = () => { slRead(); slDirty(); }; });
  slDirty();
  slPreview();
  $("#sl-save").onclick = async () => {
    slRead();
    const opt = v => v === "" || Number.isNaN(v) ? null : v;
    const body = { profile: pid, mode: dr.mode, parts: slParts(dr), separator: dr.separator, colors: dr.colors, limits: dr.limits,
                   command: dr.command, padding: opt(dr.padding), refreshInterval: opt(dr.refreshInterval), hideVimModeIndicator: dr.hide };
    try { await run(() => api("/api/statusline", body)); } catch { return; }
    st.sl = await api("/api/statusline?profile=" + pid); slDraft(); renderStatusLine();
  };
  $("#sl-all").onclick = async () => {
    if (slKey(dr) !== st.slSaved && !(await confirmBox("Unsaved changes", "<b>Apply to all</b> uses the status line saved in this profile, without the changes you have not saved yet. Go on?", "Go on"))) return;
    if (await applyAll("Use this status line in every profile?", `/api/statusline/all/preview?profile=${pid}`,
        `The status line saved in <b>${esc(label(pid))}</b> goes to every other profile. One made by cc-profiles gets its own script in each profile, and shows each profile's name.`,
        "Apply to all", () => api("/api/statusline/all", { profile: pid }))) { st.sl = await api("/api/statusline?profile=" + pid); slDraft(); renderStatusLine(); }
  };
}
const fmt = v => v === null || v === undefined ? "default" : v === "" ? "none" : typeof v === "boolean" ? (v ? "on" : "off") : String(v);
const srcBadge = src => src === "local" ? `<span class="badge b-warn src" title="settings.local.json wins over settings.json">settings.local.json</span>`
  : src === "settings" ? `<span class="badge b-none src">settings.json</span>`
  : src === "global" ? `<span class="badge b-none src" title="Where /config keeps this setting: the profile's global config">.claude.json</span>` : `<span class="badge b-default src">default</span>`;
function selectOptions(f) {
  const opt = o => `<option value="${esc(o.value)}" ${o.value === f.value ? "selected" : ""}>${esc(o.label)}</option>`;
  const groups = [...new Set(f.options.map(o => o.group))];
  if (groups.length < 2) return f.options.map(opt).join("");
  return groups.map(g => g ? `<optgroup label="${esc(g)}">${f.options.filter(o => o.group === g).map(opt).join("")}</optgroup>`
                           : f.options.filter(o => !o.group).map(opt).join("")).join("");
}
const optionDesc = (f, v) => v == null || v === "" ? f.default_desc || "" : f.options?.find(o => o.value === v)?.desc || "";
function fieldInput(f) {
  if (f.type === "select") return `<select data-sfield="${f.key}" style="flex:1;min-width:0" aria-label="${esc(f.label)}">
      <option value="" ${f.value == null ? "selected" : ""}>— default${f.default != null && f.options?.find(o => o.value === f.default) ? ": " + esc(f.options.find(o => o.value === f.default).label) : ""} —</option>
      ${selectOptions(f)}</select>`;
  if (f.off_value !== undefined) return `<label class="switch"><input type="checkbox" data-sfield="${f.key}" ${f.value !== f.off_value ? "checked" : ""} aria-label="${esc(f.label)}"><span></span></label>${typeof f.value === "string" && f.value !== f.off_value ? `<span class="hint" title="${esc(f.value)}">custom text, kept</span>` : ""}`;
  if (f.type === "bool" && f.value != null && typeof f.value !== "boolean") return `<span class="hint">custom value: edit it in the advanced editor</span>`;
  if (f.type === "bool") return `<label class="switch"><input type="checkbox" data-sfield="${f.key}" ${f.value === true || (f.value == null && f.default === true) ? "checked" : ""} aria-label="${esc(f.label)}"><span></span></label>`;
  const list = f.suggest?.length ? `list="dl-${f.key}"` : "";
  return `<input class="text" ${f.type === "number" ? 'type="number" min="1" step="1"' : ""} data-sfield="${f.key}" value="${esc(f.value ?? "")}" placeholder="default" ${list} aria-label="${esc(f.label)}">
    ${f.suggest?.length ? `<datalist id="dl-${f.key}">${f.suggest.map(v => `<option value="${esc(v)}">`).join("")}</datalist>` : ""}
`;
}
function renderSettings() {
  if (S.tab !== "settings") return;
  const st = S.set, d = st?.data;
  const seg = `<div class="seg" style="max-width:360px">${S.profiles.map(p => `<button data-setprof="${p.id}" class="${st?.profile === p.id ? "on" : ""}">${esc(p.label)}</button>`).join("")}</div>`;
  if (!d) { $("#main").innerHTML = `<div class="toolbar">${seg}</div><div class="empty">${LOADER}</div>`; return; }
  const sh = f => f.shared ? `<span class="shared-note">shared with ${esc(S.profiles[0].label)}</span>` : "";
  const errs = ["settings", "local"].filter(k => d.files[k].error).map(k => `<div class="danger-box"><code>${esc(d.files[k].path)}</code>: ${esc(d.files[k].error)}. Fix it in the advanced editor below.</div>`).join("");
  $("#main").innerHTML = `<div class="toolbar">${seg}<span class="hint">Changes apply from the next Claude Code session in this profile. Every save goes to the backup.</span></div>
  <div class="setgrid">${errs}
    <section class="sec"><div class="h"><h2>General</h2><span class="hint">The settings of <code>/config</code> in Claude Code: the value in use and the file it comes from; the other profiles on the right. Options checked against Claude Code ${esc(d.schema_version)}.</span>${sh(d.files.settings)}</div>
      ${d.fields.map((f, i) => { const shownF = f.key in st.draft ? { ...f, value: storedOf(f, st.draft[f.key]) } : f; return `${f.group && f.group !== d.fields[i - 1]?.group ? `<h3 class="sgroup">${esc(f.group)}</h3>` : ""}<div class="srow" data-srow="${f.key}">
        <div class="l"><b>${esc(f.label)}${f.deprecated ? ` <span class="badge b-warn">deprecated</span>` : ""}</b><span>${esc(f.help)}</span></div>
        <div class="v">${fieldInput(shownF)} ${srcBadge(f.source)}
          ${f.source ? `<button class="btn small" data-sreset="${f.key}" title="Remove the setting and go back to the default" aria-label="Reset ${esc(f.label)}">×</button>` : ""}
          ${f.default_desc || f.options?.some(o => o.desc) ? `<div class="sdesc" data-sdesc="${f.key}">${esc(optionDesc(f, shownF.value))}</div>` : ""}</div>
        <div class="o">${f.others.map(o => `<div>${esc(o.label)}: <code>${esc(f.off_value !== undefined ? (o.value === f.off_value ? "off" : o.value == null ? "on" : "custom") : f.options?.find(x => x.value === o.value)?.label || fmt(o.value))}</code>
          ${f.deprecated ? "" : JSON.stringify(o.value) !== JSON.stringify(f.value) ? `<button class="btn small" data-scopy="${f.key}" data-from="${o.id}">copy</button>` : `<span class="okmark">same</span>`}</div>`).join("") || "—"}
          ${!f.deprecated && f.others.some(o => JSON.stringify(o.value) !== JSON.stringify(f.value)) ? `<div><button class="btn small" data-sall="${f.key}" title="Give every other profile the value saved in this one">Apply to all…</button></div>` : ""}</div>
      </div>`; }).join("")}
      <div class="savebar" id="gen-bar" hidden><span id="gen-count"></span><span class="grow"></span><button class="btn" id="gen-cancel">Cancel</button><button class="btn primary" id="gen-save">Save changes</button></div>
    </section>

    ${statusLineSection()}

    <section class="sec"><div class="h"><h2>Global instructions · CLAUDE.md</h2><span class="hint"><code>${esc(d.claude_md.path)}</code> · loaded at the start of every session in this profile${d.claude_md.exists ? "" : " · does not exist yet: saving creates it"}</span>${sh(d.claude_md)}</div>
      <div class="b"><textarea class="code" id="cmd-text" spellcheck="false" aria-label="CLAUDE.md" placeholder="# Context&#10;&#10;In this profile you work on …">${esc(d.claude_md.content)}</textarea>
        <div class="row-end"><span class="grow">${plural(d.claude_md.content ? d.claude_md.content.split("\n").length : 0, "line", "lines")}</span><button class="btn primary" id="cmd-save">Save CLAUDE.md</button></div></div>
    </section>

    <section class="sec"><div class="h"><h2>Permissions</h2><span class="hint">One rule per line, in <code>settings.json</code>. E.g. <code>Bash(npm run test:*)</code>, <code>Read(~/Documents/**)</code>, <code>mcp__claude_ai_Gmail</code></span></div>
      <div class="b"><div class="perm">${[["allow", "Allow without asking"], ["ask", "Always ask"], ["deny", "Block"]].map(([k, l]) => `<label class="f">${l} <code>${k}</code>
          <textarea class="text" id="perm-${k}" spellcheck="false">${esc((d.permissions[k] || []).join("\n"))}</textarea>
          ${(d.permissions_local[k] || []).length ? `<span class="hint">+ ${d.permissions_local[k].length} in settings.local.json (edit them in the advanced editor)</span>` : ""}</label>`).join("")}</div>
        <div class="row-end"><span class="grow">deny wins over ask, which wins over allow.</span><button class="btn" id="perm-all">Add a rule to every profile…</button><button class="btn primary" id="perm-save">Save permissions</button></div></div>
    </section>

    <section class="sec"><div class="h"><h2>Advanced editor</h2><span class="hint">Hooks, environment variables (<code>env</code>) and everything else. The JSON is checked before saving.</span></div>
      <div class="b"><div class="seg" style="max-width:420px;margin-bottom:10px">${["settings", "local"].map(k => `<button data-rawfile="${k}" class="${st.rawFile === k ? "on" : ""}">${k === "settings" ? "settings.json" : "settings.local.json"}</button>`).join("")}</div>
        <textarea class="code" id="raw-text" spellcheck="false" style="min-height:340px" aria-label="Raw JSON">${esc(d.files[st.rawFile].raw)}</textarea>
        <div class="row-end"><span class="grow" id="raw-status" aria-live="polite"></span>${sh(d.files[st.rawFile])}<button class="btn" id="raw-format">Format</button><button class="btn primary" id="raw-save">Save</button></div></div>
    </section>

    <section class="sec"><div class="h"><h2>Global</h2><span class="hint"><code>${esc(d.global.path)}</code> · almost everything in here is Claude Code's internal state: shown, not edited.</span></div>
      <div class="b"><div class="srow" style="padding:0 0 10px;border:0"><div class="l"><b>Auto-updates</b><span>autoUpdates</span></div>
        <div class="v"><label class="switch"><input type="checkbox" id="g-auto" ${d.global.autoUpdates ? "checked" : ""} aria-label="Auto-updates"><span></span></label></div><div></div></div>
        <dl class="kv">${Object.entries(d.global.info).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>
    </section>
  </div>`;
  bindSettings();
}
function bindSettings() {
  const st = S.set, d = st.data, pid = st.profile;
  bindStatusLine();
  const set = (f, r) => { st.draft[f.key] = r; genMark(); };
  document.querySelectorAll("[data-sfield]").forEach(el => {
    const f = d.fields.find(x => x.key === el.dataset.sfield);
    if (!f) return;
    if (f.off_value !== undefined) {  // on keeps a custom text the profile already has
      el.onchange = () => set(f, el.checked ? (typeof f.value === "string" && f.value !== f.off_value ? f.value : true) : false);
      return;
    }
    if (f.type === "bool") { el.onchange = () => set(f, el.checked); return; }
    if (f.type === "select") {
      el.onchange = () => {
        const dsc = document.querySelector(`[data-sdesc="${f.key}"]`);
        if (dsc) dsc.textContent = optionDesc(f, el.value);
        set(f, el.value === "" ? null : el.value);
      };
      return;
    }
    el.oninput = () => set(f, f.type === "number" ? (el.value === "" ? null : parseInt(el.value, 10)) : (el.value.trim() || null));
    el.onkeydown = e => { if (e.key === "Enter" && genChanged().length) $("#gen-save").click(); };
  });
  document.querySelectorAll("[data-sreset]").forEach(b => b.onclick = () => {
    const f = d.fields.find(x => x.key === b.dataset.sreset);
    st.draft[f.key] = null; genRedraw();
  });
  document.querySelectorAll("[data-scopy]").forEach(b => b.onclick = () => {
    const f = d.fields.find(x => x.key === b.dataset.scopy), o = f.others.find(x => x.id === b.dataset.from);
    st.draft[f.key] = reqOf(f, o.value); genRedraw();
  });
  $("#gen-cancel").onclick = () => { st.draft = {}; genRedraw(); };
  $("#gen-save").onclick = async () => {
    const values = Object.fromEntries(genChanged().map(k => [k, st.draft[k]]));
    try { await run(() => api("/api/settings/fields", { profile: pid, values })); } catch { return; }
    st.draft = {}; loadSettings(pid);
  };
  genMark();
  document.querySelectorAll("[data-sall]").forEach(b => b.onclick = async () => {
    const f = d.fields.find(x => x.key === b.dataset.sall);
    if (genChanged().includes(f.key) && !(await confirmBox("Unsaved change", `<b>Apply to all</b> uses the value of <b>${esc(f.label)}</b> saved in this profile, not the one you have not saved yet. Go on?`, "Go on"))) return;
    const shown = f.value === null || f.value === undefined ? "the default" : f.options?.find(o => o.value === f.value)?.label || fmt(f.value);
    if (await applyAll(`Apply ${f.label.toLowerCase()} to every profile?`,
        `/api/settings/field/all/preview?profile=${encodeURIComponent(pid)}&key=${encodeURIComponent(f.key)}`,
        `<b>${esc(f.label)}</b>: <code>${esc(shown)}</code>, the value saved in ${esc(label(pid))}, goes to every other profile.`,
        "Apply to all", () => api("/api/settings/field/all", { profile: pid, key: f.key }))) loadSettings(pid);
  });
  $("#perm-all").onclick = async () => {
    const res = await modal({ title: "Add a rule to every profile", sub: "The rule is added to <code>settings.json</code> of each profile that does not have it yet. The next step shows which profiles change.",
      body: `<div class="form"><label class="f">List<select id="pa-list">${[["allow", "Allow without asking"], ["ask", "Always ask"], ["deny", "Block"]].map(([k, l]) => `<option value="${k}" ${k === "deny" ? "selected" : ""}>${l} (${k})</option>`).join("")}</select></label>
        <label class="f">Rule<input class="text" id="pa-rule" placeholder="e.g. Bash(rm -rf:*)" autocomplete="off"></label></div>`,
      actions: [{ label: "Preview", kind: "primary", value: "ok" }] });
    if (!res) return;
    const list = $("#pa-list", res.el).value, rule = $("#pa-rule", res.el).value.trim();
    if (!rule) { toast("Write a rule first, e.g. Bash(rm -rf:*)", "", true); return; }
    if (await applyAll(`Add the rule to every profile?`,
        `/api/settings/permissions/all/preview?list=${encodeURIComponent(list)}&rule=${encodeURIComponent(rule)}`,
        `<code>${esc(rule)}</code> is added to <code>${esc(list)}</code>.`,
        "Add to all", () => api("/api/settings/permissions/all", { list, rule }))) loadSettings(pid);
  };
  document.querySelectorAll("[data-setprof]").forEach(b => b.onclick = async () => {
    if (b.dataset.setprof === pid) return;
    if (genChanged().length && !(await confirmBox("Discard the changes?", `${plural(genChanged().length, "change", "changes")} to ${esc(label(pid))} ${genChanged().length === 1 ? "is" : "are"} not saved yet.`, "Discard"))) return;
    loadSettings(b.dataset.setprof);
  });
  document.querySelectorAll("[data-rawfile]").forEach(b => b.onclick = () => { st.rawFile = b.dataset.rawfile; renderSettings(); });
  $("#cmd-save").onclick = async () => { try { await run(() => api("/api/settings/claude-md", { profile: pid, content: $("#cmd-text").value })); } catch {} loadSettings(pid); };
  $("#perm-save").onclick = async () => {
    const rules = Object.fromEntries(["allow", "ask", "deny"].map(k => [k, $("#perm-" + k).value.split("\n")]));
    try { await run(() => api("/api/settings/permissions", { profile: pid, rules })); } catch {} loadSettings(pid);
  };
  const raw = $("#raw-text"), status = $("#raw-status");
  const check = () => { try { const v = JSON.parse(raw.value); if (typeof v !== "object" || Array.isArray(v) || v === null) throw new Error("must be an object { … }"); status.textContent = "Valid JSON"; status.style.color = "var(--ok)"; return true; }
    catch (e) { status.textContent = e.message; status.style.color = "var(--err)"; return false; } };
  raw.oninput = check; check();
  $("#raw-format").onclick = () => { if (check()) { raw.value = JSON.stringify(JSON.parse(raw.value), null, 2) + "\n"; } };
  $("#raw-save").onclick = async () => { if (!check()) return; try { await run(() => api("/api/settings/raw", { profile: pid, file: st.rawFile, content: raw.value })); } catch {} loadSettings(pid); };
  $("#g-auto").onchange = async e => { try { await run(() => api("/api/settings/global", { profile: pid, key: "autoUpdates", value: e.target.checked })); } catch {} loadSettings(pid); };
}

// ---------- theme ----------
// System follows the operating system; Light and Dark set data-theme on <html>, which the CSS
// variables and the script in <head> read. The choice is kept in localStorage, per browser.
const THEMES = [["system", "System"], ["light", "Light"], ["dark", "Dark"]];
const savedTheme = () => { try { return localStorage.getItem("cc-profiles.theme") || "system"; } catch { return "system"; } };
function setTheme(v) {
  try { localStorage.setItem("cc-profiles.theme", v); } catch {}
  if (v === "light" || v === "dark") document.documentElement.setAttribute("data-theme", v);
  else document.documentElement.removeAttribute("data-theme");
}
let closeTheme = null;
function openTheme() {
  const btn = $("#theme-btn"), r = btn.getBoundingClientRect();
  const pop = document.createElement("div");
  pop.className = "popover"; pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "Theme");
  pop.style.top = (r.bottom + 8) + "px";
  pop.style.right = Math.max(16, document.documentElement.clientWidth - r.right) + "px";
  const draw = () => {
    const cur = savedTheme();
    pop.innerHTML = `<h2>Theme</h2><div class="seg">${THEMES.map(([k, l]) => `<button data-theme-set="${k}" class="${cur === k ? "on" : ""}" aria-pressed="${cur === k}">${l}</button>`).join("")}</div>`;
  };
  const close = () => { pop.remove(); closeTheme = null; document.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onOut); btn.focus(); };
  const onKey = e => { if (e.key === "Escape") close(); };
  const onOut = e => { if (!pop.contains(e.target) && !btn.contains(e.target)) close(); };
  pop.addEventListener("click", e => { const b = e.target.closest("[data-theme-set]"); if (b) { setTheme(b.dataset.themeSet); draw(); $("button.on", pop)?.focus(); } });
  draw();
  document.body.append(pop);
  document.addEventListener("keydown", onKey); document.addEventListener("mousedown", onOut);
  closeTheme = close;
  $("button.on", pop)?.focus();
}
