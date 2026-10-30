// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Andrea Iannarone
// Search, compare, usage, backups.

// ---------- search everything ----------
// A pseudo-tab: S.tab is "search" while results show; Esc or an empty field goes back.
const SKINDS = [["projects", "Projects"], ["memories", "Memories"], ["skills", "Skills"], ["mcp", "MCP servers"], ["claude_md", "CLAUDE.md"]];
S.search = { q: "", data: null, error: null, prev: "projects", timer: null };
function goTab(tab) {
  S.tab = tab;
  markTab(tab);
}
function highlight(sn) {
  const t = sn.text;
  return esc(t.slice(0, sn.at)) + "<mark>" + esc(t.slice(sn.at, sn.at + sn.len)) + "</mark>" + esc(t.slice(sn.at + sn.len));
}
async function runSearch(q) {
  const x = S.search;
  if (S.tab !== "search") x.prev = S.tab;
  x.q = q; x.data = null; x.error = null;
  goTab("search"); renderSearch();
  try { const r = await api("/api/search?q=" + encodeURIComponent(q)); if (x.q === q) x.data = r; }
  catch (e) { x.error = e.message; }
  if (x.q === q) renderSearch();
}
function closeSearch() {
  const x = S.search;
  clearTimeout(x.timer);
  $("#gsearch").value = ""; x.q = ""; x.data = null;
  if (S.tab !== "search") return;
  const prev = x.prev || "projects";
  $(`#tabs button[data-tab="${prev}"]`)?.click();
}
function renderSearch() {
  if (S.tab !== "search") return;
  const x = S.search, d = x.data;
  if (x.error) { $("#main").innerHTML = `<div class="empty">${esc(x.error)}</div>`; return; }
  if (!d) { $("#main").innerHTML = `<div class="empty">${LOADER} Searching every profile for “${esc(x.q)}”…</div>`; return; }
  const total = Object.values(d.counts).reduce((a, b) => a + b, 0);
  const others = r => (r.profiles || [r.profile]).map(badge).join(" ");
  $("#main").innerHTML = `<div class="toolbar"><span class="hint">${plural(total, "result", "results")} for “${esc(d.q)}” in every profile${d.truncated ? " · only the first ones: refine the search to see more" : ""}. Values of MCP environment variables and headers are not searched.</span>
      <button class="btn small" id="s-close" style="margin-left:auto">Close search</button></div>
    ${total ? SKINDS.filter(([k]) => d.results[k].length).map(([k, l]) => `<div class="ext-head"><h2>${l}</h2><span class="hint">${d.counts[k]}</span></div>
      <div class="table sres">${d.results[k].map((r, i) => `<div class="prow" data-sres="${k}:${i}" tabindex="0" role="button"><div class="txt">
          <div class="t">${esc(r.title)} ${others(r)}${r.where ? ` <span class="hint" style="font-weight:400">${esc(r.where)}</span>` : ""}</div>
          <div class="snip">${highlight(r.snippet)}</div></div></div>`).join("")}</div>`).join("")
      : `<div class="empty">Nothing matches “${esc(d.q)}” in any profile.</div>`}`;
  $("#s-close").onclick = closeSearch;
  document.querySelectorAll("[data-sres]").forEach(el => {
    const [k, i] = el.dataset.sres.split(":"), r = d.results[k][+i];
    el.onclick = () => openResult(r);
    el.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openResult(r); } };
  });
}
async function openResult(r) {
  const o = r.open;
  $("#gsearch").value = ""; S.search.q = "";
  if (r.kind === "memory") {
    goTab("memories"); S.mem.profile = r.profile; S.mem.q = ""; await loadMemProjects();
    await openMemProject(o.project); return openMemFile(o.file);
  }
  if (r.kind === "skill") { goTab("skills"); await loadExt(r.profile); return openSkill(o.skill); }
  if (r.kind === "mcp") { goTab("mcp"); return loadExt(r.profile); }
  if (r.kind === "project") { goTab("projects"); S.filter = "all"; S.q = o.path; return renderProjects(); }
  if (r.kind === "claude_md") { goTab("settings"); return loadSettings(r.profile); }
}
$("#gsearch").addEventListener("input", e => {
  const x = S.search, q = e.target.value.trim();
  clearTimeout(x.timer);
  if (!q) return closeSearch();
  if (q.length >= 2) x.timer = setTimeout(() => runSearch(q), 300);
});
$("#gsearch").addEventListener("keydown", e => {
  if (e.key === "Escape") { e.preventDefault(); closeSearch(); }
  if (e.key === "Enter") { const q = e.target.value.trim(); clearTimeout(S.search.timer); if (q.length >= 2) runSearch(q); }
});
document.addEventListener("click", e => { if (e.target.closest("#tabs button") && S.search.q) { $("#gsearch").value = ""; S.search.q = ""; } }, true);

// ---------- compare two profiles ----------
S.cmp = { a: null, b: null, data: null, error: null };
async function loadCompare() {
  const c = S.cmp;
  if (S.profiles.length < 2) { c.data = null; c.error = "There is only one profile: create a second one to compare."; return renderCompare(); }
  if (!S.profiles.some(p => p.id === c.a)) c.a = S.profiles[0].id;
  if (!S.profiles.some(p => p.id === c.b) || c.b === c.a) c.b = S.profiles.find(p => p.id !== c.a).id;
  c.data = null; c.error = null; renderCompare();
  try { c.data = await api(`/api/compare?a=${c.a}&b=${c.b}`); } catch (e) { c.error = e.message; }
  renderCompare();
}
function renderCompare() {
  if (S.tab !== "compare") return;
  const c = S.cmp, d = c.data;
  const sel = (id, v, other) => `<select id="${id}" aria-label="${id === "cmp-a" ? "Profile A" : "Profile B"}">${S.profiles.map(p => `<option value="${p.id}" ${p.id === v ? "selected" : ""} ${p.id === other ? "disabled" : ""}>${esc(p.label)}</option>`).join("")}</select>`;
  const head = S.profiles.length < 2 ? "" : `<div class="toolbar"><span class="hint">Compare</span> ${sel("cmp-a", c.a, c.b)} <span class="hint">with</span> ${sel("cmp-b", c.b, c.a)}
      <span class="hint">Rows that differ are marked; copies go through the usual operations and their backups.</span></div>`;
  if (c.error) { $("#main").innerHTML = `${head}<div class="empty">${esc(c.error)}</div>`; return bindCompare(); }
  if (!d) { $("#main").innerHTML = `${head}<div class="empty">${LOADER} Comparing…</div>`; return bindCompare(); }
  const A = esc(d.a.label), B = esc(d.b.label);
  const SRC = { local: "settings.local.json", settings: "settings.json" };
  const val = (v, src) => `${esc(fmt(v))}${src ? `<span class="src">${SRC[src]}</span>` : ""}`;
  const mark = same => same ? `<span class="okmark">same</span>` : `<span class="badge b-warn">differs</span>`;
  const only = side => `<span class="badge b-warn">only in ${side === "a" ? A : B}</span>`;
  const btn = (attrs, label) => `<button class="btn small" ${attrs}>${label}</button>`;
  const table = (cols, rows, empty) => rows.length ? `<div class="table cmp"><table><thead><tr>${cols.map(x => `<th>${x}</th>`).join("")}<th></th></tr></thead><tbody>${rows.join("")}</tbody></table></div>`
    : `<div class="hint">${empty}</div>`;
  const listRows = (sec, kind, side, name, extra = "", label = "Copy") => `<tr class="diff"><td class="v">${esc(name)}</td><td>${only(side)}${extra}</td>
      <td class="acts">${btn(`data-cmp="${sec}" data-kind="${kind}" data-side="${side}" data-name="${esc(name)}"`, `${label} to ${side === "a" ? B : A}`)}</td></tr>`;
  const P = d.permissions.diff, perms = [];
  for (const k of ["allow", "ask", "deny"]) {
    for (const r of P[k].only_a) perms.push(listRows("perm", k, "a", r, ` <code>${k}</code>`, "Add"));
    for (const r of P[k].only_b) perms.push(listRows("perm", k, "b", r, ` <code>${k}</code>`, "Add"));
  }
  const nBoth = ["allow", "ask", "deny"].reduce((n, k) => n + P[k].both.length, 0);
  const sk = d.skills, ag = d.agents, mc = d.mcp, md = d.claude_md, pl = d.plugins, mo = d.mods;
  const onOff = v => v ? "enabled" : `<span class="hint">disabled</span>`;
  const plug = k => `${pl[k].only_a.length ? `only in ${A}: ${pl[k].only_a.map(esc).join(", ")}<br>` : ""}${pl[k].only_b.length ? `only in ${B}: ${pl[k].only_b.map(esc).join(", ")}<br>` : ""}${pl[k].both.length ? `in both: ${pl[k].both.map(esc).join(", ")}` : ""}` || "none";
  $("#main").innerHTML = `${head}
    <div class="ext-head" style="margin-top:0"><h2>Settings</h2><span class="hint">the value in use and the file it comes from</span></div>
    ${table(["Setting", A, B], d.settings.map((s, i) => `<tr class="${s.same ? "" : "diff"}"><td>${esc(s.label)} ${s.same ? "" : mark(false)}</td>
        <td class="v">${val(s.a, s.a_source)}</td><td class="v">${val(s.b, s.b_source)}</td>
        <td class="acts">${s.same ? "" : btn(`data-cmp="set" data-i="${i}" data-side="a"`, `${A} → ${B}`) + btn(`data-cmp="set" data-i="${i}" data-side="b"`, `${B} → ${A}`)}</td></tr>`), "")}
    <div class="ext-head"><h2>Permissions</h2><span class="hint">rules in <code>settings.json</code> · ${plural(nBoth, "rule", "rules")} in both</span></div>
    ${table(["Rule", "Where"], perms, "Both profiles have the same rules. ✓")}
    <div class="ext-head"><h2>Skills</h2><span class="hint">${sk.shared ? "the two profiles share the same skills folder" : `${plural(sk.both.length, "skill", "skills")} in both`}</span></div>
    ${table(["Skill", "Where"], [...sk.only_a.map(n => listRows("skill", "", "a", n)), ...sk.only_b.map(n => listRows("skill", "", "b", n)),
        ...sk.both.filter(x => !x.same).map(x => `<tr class="diff"><td class="v">${esc(x.name)}</td><td>${mark(false)} <span class="hint">the SKILL.md files are different: edit them in the Skills tab</span></td><td></td></tr>`)],
      "The same skills, with the same SKILL.md. ✓")}
    <div class="ext-head"><h2>Agents</h2><span class="hint">${ag.shared ? "the two profiles share the same agents folder" : `${plural(ag.both.length, "agent", "agents")} in both`}</span></div>
    ${table(["Agent", "Where"], [...ag.only_a.map(n => listRows("agent", "", "a", n)), ...ag.only_b.map(n => listRows("agent", "", "b", n)),
        ...ag.both.filter(x => !x.same).map(x => `<tr class="diff"><td class="v">${esc(x.name)}</td><td>${mark(false)} <span class="hint">the two files are different: edit them in the Agents tab</span></td><td></td></tr>`)],
      "The same agents, with the same files. ✓")}
    <div class="ext-head"><h2>MCP servers</h2><span class="hint">for every project · ${plural(mc.both.length, "server", "servers")} in both</span></div>
    ${table(["Server", "Where"], [...mc.only_a.map(m => listRows("mcp", "", "a", m.name, ` <span class="hint">${esc(m.type)} · ${esc(m.target)}</span>`)),
        ...mc.only_b.map(m => listRows("mcp", "", "b", m.name, ` <span class="hint">${esc(m.type)} · ${esc(m.target)}</span>`)),
        ...mc.both.filter(m => !m.same).map(m => `<tr class="diff"><td class="v">${esc(m.name)}</td><td>${mark(false)} <span class="hint">different configuration: edit it in the MCP tab</span></td><td></td></tr>`)],
      "The same servers, with the same configuration. ✓")}
    <div class="ext-head"><h2>CLAUDE.md</h2><span class="hint">${md.shared ? "shared: the two profiles use the same file" : ""}</span></div>
    ${table(["", A, B], [`<tr class="${md.same ? "" : "diff"}"><td>${mark(md.same)}</td>
        <td>${md.a.exists ? plural(md.a.lines, "line", "lines") : `<span class="hint">not present</span>`}</td>
        <td>${md.b.exists ? plural(md.b.lines, "line", "lines") : `<span class="hint">not present</span>`}</td>
        <td class="acts">${md.same || md.shared ? "" : (md.a.exists ? btn(`data-cmp="md" data-side="a"`, `Replace ${B}'s with ${A}'s`) : "") + (md.b.exists ? btn(`data-cmp="md" data-side="b"`, `Replace ${A}'s with ${B}'s`) : "")}</td></tr>`], "")}
    <div class="ext-head"><h2>Mods</h2><span class="hint">${mo.shared ? "the two profiles share the same plugins folder" : `${plural(mo.both.length, "mod", "mods")} in both`}</span></div>
    ${table(["Mod", "Where"], [...mo.only_a.map(n => listRows("plugin", "", "a", n)), ...mo.only_b.map(n => listRows("plugin", "", "b", n)),
        ...mo.both.filter(x => x.a !== x.b).map(x => `<tr class="diff"><td class="v">${esc(x.name)}</td><td>${A}: ${onOff(x.a)} · ${B}: ${onOff(x.b)} <span class="hint">turn it on or off in the Plugins tab</span></td><td></td></tr>`)],
      mo.only_a.length + mo.only_b.length + mo.both.length ? "The same mods, on or off in both. ✓" : "No mods in either profile.")}
    <div class="ext-head"><h2>Plugins</h2><span class="hint">read-only: install and enable plugins with <code>/plugin</code> in Claude Code</span></div>
    ${table(["", ""], [`<tr><td>Installed</td><td>${plug("installed")}</td><td></td></tr>`, `<tr><td>Enabled</td><td>${plug("enabled")}</td><td></td></tr>`], "")}`;
  bindCompare();
}
function bindCompare() {
  const c = S.cmp, d = c.data;
  const pick = (id, k) => { const el = $(id); if (el) el.onchange = () => { c[k] = el.value; loadCompare(); }; };
  pick("#cmp-a", "a"); pick("#cmp-b", "b");
  if (!d) return;
  const ids = { a: d.a.id, b: d.b.id }, other = s => (s === "a" ? "b" : "a"), name = s => (s === "a" ? d.a.label : d.b.label);
  const done = async fn => { try { await run(fn); } catch {} loadCompare(); };
  document.querySelectorAll("[data-cmp]").forEach(b => b.onclick = async () => {
    const side = b.dataset.side, from = ids[side], to = ids[other(side)];
    if (b.dataset.cmp === "set") {
      const s = d.settings[+b.dataset.i];
      return done(() => api("/api/settings/field", { profile: to, key: s.key, value: s[side] }));
    }
    if (b.dataset.cmp === "perm") {
      const lists = d.permissions[other(side)], k = b.dataset.kind;
      const rules = { ...lists, [k]: [...lists[k], b.dataset.name] };  // the target's own rules stay
      return done(() => api("/api/settings/permissions", { profile: to, rules }));
    }
    if (b.dataset.cmp === "skill") return done(() => api("/api/skills/copy", { profile: from, name: b.dataset.name, to }));
    if (b.dataset.cmp === "agent") return done(() => api("/api/agents/copy", { profile: from, name: b.dataset.name, to }));
    if (b.dataset.cmp === "plugin") return done(() => api("/api/plugins/copy", { profile: from, plugin: b.dataset.name, to }));
    if (b.dataset.cmp === "mcp") return done(() => api("/api/mcp/copy", { profile: from, scope: "user", name: b.dataset.name, to }));
    if (b.dataset.cmp === "md") {
      if (!(await confirmBox(`Replace ${name(other(side))}'s CLAUDE.md?`, `It gets the content of ${esc(name(side))}'s CLAUDE.md. The current file goes to the backup.`, "Replace"))) return;
      const src = await api("/api/settings?profile=" + from);
      return done(() => api("/api/settings/claude-md", { profile: to, content: src.claude_md.content }));
    }
  });
}

// ---------- usage ----------
// Read-only: tokens and an estimated cost from the usage Claude Code records on every reply.
S.use = { profile: "all", days: 30, data: null, error: null, seq: 0 };
async function loadUsage() {
  const u = S.use, seq = ++u.seq;
  if (u.profile !== "all" && !S.profiles.some(p => p.id === u.profile)) u.profile = "all";
  u.data = null; u.error = null; renderUsage();
  try { const d = await api(`/api/usage?profile=${encodeURIComponent(u.profile)}&days=${u.days}`); if (seq === u.seq) u.data = d; }
  catch (e) { if (seq === u.seq) u.error = e.message; }
  if (seq === u.seq) renderUsage();
}
const tok = n => n >= 1e9 ? (n / 1e9).toFixed(1) + "B" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e4 ? Math.round(n / 1e3) + "K" : n.toLocaleString("en-US");
const usd = n => n === 0 ? "$0" : n < 0.01 ? "<$0.01" : "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const dayLabel = (d, year) => new Date(d + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", ...(year ? { year: "numeric" } : {}) });
function usageChart(daily) {
  const W = 1000, H = 190, n = daily.length, gap = n > 120 ? 0 : n > 40 ? 1.5 : 4, bw = W / n;
  const max = Math.max(...daily.map(d => d.tokens));
  const y = v => (v / (max || 1)) * (H - 6);
  const bars = daily.map((d, i) => {
    const x = i * bw + gap / 2, w = Math.max(bw - gap, 0.6);
    let top = H, rects = "";
    for (const [cls, v] of [["u-read", d.cache_read], ["u-in", d.input + d.cache_write], ["u-out", d.output]]) {
      if (!v) continue;
      const h = y(v); top -= h;
      rects += `<rect class="bar ${cls}" x="${x.toFixed(2)}" y="${top.toFixed(2)}" width="${w.toFixed(2)}" height="${h.toFixed(2)}"/>`;
    }
    const tip = `${dayLabel(d.date, true)}: ` + (d.tokens ? `${tok(d.tokens)} tokens (${tok(d.output)} output, ${tok(d.input + d.cache_write)} input and cache write, ${tok(d.cache_read)} cache read), ${plural(d.replies, "reply", "replies")}, ${usd(d.cost)} estimated` : "no replies");
    return `<g class="day"><title>${esc(tip)}</title><rect class="hit" x="${(i * bw).toFixed(2)}" y="0" width="${bw.toFixed(2)}" height="${H}"/>${rects}</g>`;
  }).join("");
  const busiest = daily.reduce((a, d) => d.tokens > a.tokens ? d : a, daily[0]);
  const label = `Tokens per day from ${dayLabel(daily[0].date, true)} to ${dayLabel(daily[n - 1].date, true)}` + (busiest.tokens ? `; the busiest day is ${dayLabel(busiest.date, true)} with ${tok(busiest.tokens)} tokens` : "; no replies");
  const half = ((H - 6) / 2 + 6).toFixed(1);
  return `<div class="uchart">
      <div class="top"><span class="grow">Tokens per day · highest ${tok(max)}, dashed line at half</span>
        <span class="legend"><i class="u-out"></i>Output</span><span class="legend"><i class="u-in"></i>Input and cache write</span><span class="legend"><i class="u-read"></i>Cache read</span></div>
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(label)}">
        <line class="grid" x1="0" y1="${H - 0.5}" x2="${W}" y2="${H - 0.5}" vector-effect="non-scaling-stroke"/>
        <line class="grid" x1="0" y1="${half}" x2="${W}" y2="${half}" stroke-dasharray="3 4" vector-effect="non-scaling-stroke"/>${bars}</svg>
      <div class="ax" aria-hidden="true"><span>${esc(dayLabel(daily[0].date))}</span><span>${esc(dayLabel(daily[Math.floor((n - 1) / 2)].date))}</span><span>${esc(dayLabel(daily[n - 1].date))}</span></div></div>`;
}
function renderUsage() {
  if (S.tab !== "usage") return;
  const u = S.use, d = u.data;
  const head = `<div class="useg">
      <div class="seg" role="group" aria-label="Profile">${[["all", "All profiles"], ...S.profiles.map(p => [p.id, p.label])].map(([id, l]) =>
        `<button data-uprof="${esc(id)}" class="${u.profile === id ? "on" : ""}" aria-pressed="${u.profile === id}">${esc(l)}</button>`).join("")}</div>
      <div class="seg" role="group" aria-label="Period">${[7, 14, 30, 90].map(n =>
        `<button data-udays="${n}" class="${u.days === n ? "on" : ""}" aria-pressed="${u.days === n}">${n} days</button>`).join("")}</div>
      <button class="btn" id="u-csv" style="margin-left:auto">Export CSV</button></div>`;
  if (u.error) { $("#main").innerHTML = `${head}<div class="empty">${esc(u.error)}</div>`; return bindUsage(); }
  if (!d) { $("#main").innerHTML = `${head}<div class="empty">${LOADER} Reading the conversations…</div>`; return bindUsage(); }
  const T = d.totals, who = d.profile === "all" ? "all profiles" : label(d.profile);
  const note = `<p class="hint">Cost is an estimate at Anthropic's list prices per token (checked ${esc(d.prices_checked)}), from the usage Claude Code records on every reply. Subscription plans (Pro, Max, Team) are not billed per token: for them it shows what the same use would cost through the API.${T.unpriced_tokens ? ` ${tok(T.unpriced_tokens)} tokens come from models without a list price and are not in the cost.` : ""}</p>`;
  if (!T.replies) {
    $("#main").innerHTML = `${head}<div class="empty">No replies from Claude in ${esc(who)} in the last ${d.days} days.</div>${note}`;
    return bindUsage();
  }
  // a row whose tokens all come from models without a price has no cost; a partial one gets a *
  const cost = x => x.tokens && x.unpriced_tokens === x.tokens ? `<span class="hint">no list price</span>` : usd(x.cost) + (x.unpriced_tokens ? "*" : "");
  const n = x => x.toLocaleString("en-US");
  const all = d.profile === "all";
  const projects = d.projects.map(p => `<tr><td class="path"><code>${esc(p.pretty)}</code></td>${all ? `<td>${badge(p.profile)}</td>` : ""}
      <td class="r">${n(p.replies)}</td><td class="r">${tok(p.tokens)}</td><td class="r">${cost(p)}</td></tr>`).join("");
  const models = d.models.map(m => `<tr><td><code>${esc(m.model)}</code>${m.family ? ` <span class="hint">${esc(m.family)} price</span>` : ""}</td>
      <td class="r">${n(m.replies)}</td><td class="r">${tok(m.input)}</td><td class="r">${tok(m.output)}</td>
      <td class="r">${tok(m.cache_write)}</td><td class="r">${tok(m.cache_read)}</td><td class="r">${cost(m)}</td></tr>`).join("");
  const sessions = d.sessions.map((x, i) => `<tr><td>${x.exists ? `<button class="linkbtn" data-usess="${i}">${esc(x.title) || "No prompt"}</button>` : `<span class="hint">only subagent replies</span>`}</td>
      <td class="path"><code>${esc(x.pretty)}</code></td>${all ? `<td>${badge(x.profile)}</td>` : ""}<td class="nums">${esc(dayLabel(x.date, true))}</td>
      <td class="r">${n(x.replies)}</td><td class="r">${tok(x.tokens)}</td><td class="r">${cost(x)}</td></tr>`).join("");
  const profs = (d.profiles || []).map(p => `<tr><td>${badge(p.id)}</td><td class="r">${n(p.replies)}</td>
      <td class="r">${tok(p.tokens)}</td><td class="r">${p.tokens ? cost(p) : "$0"}</td></tr>`).join("");
  $("#main").innerHTML = `${head}
    <div class="ucards">
      <div class="ucard"><b>${tok(T.tokens)}</b><span>tokens: ${tok(T.input + T.cache_write + T.cache_read)} in, ${tok(T.output)} out</span></div>
      <div class="ucard"><b>${usd(T.cost)}${T.unpriced_tokens ? "*" : ""}</b><span>estimated cost at list price</span></div>
      <div class="ucard"><b>${n(T.replies)}</b><span>${T.replies === 1 ? "reply" : "replies"} in ${plural(d.projects_count, "project", "projects")}</span></div>
      <div class="ucard"><b>${Math.round(T.cache_read_share * 100)}%</b><span>of input tokens read from the cache</span></div>
    </div>
    ${usageChart(d.daily)}
    ${note}
    <div class="ext-head"><h2>Top projects</h2><span class="hint">${d.projects_count > d.projects.length ? `the ${d.projects.length} with the most tokens, of ${d.projects_count}` : "by tokens"} · ${esc(who)} · last ${d.days} days</span></div>
    <div class="table uproj"><table><thead><tr><th>Project</th>${all ? "<th>Profile</th>" : ""}<th class="r">Replies</th><th class="r">Tokens</th><th class="r">Estimated cost</th></tr></thead><tbody>${projects}</tbody></table></div>
    <div class="ext-head"><h2>Most expensive sessions</h2><span class="hint">the ${plural(d.sessions.length, "conversation", "conversations")} with the highest estimated cost, then the most tokens · open one to read it</span></div>
    <div class="table usess"><table><thead><tr><th>Conversation</th><th>Project</th>${all ? "<th>Profile</th>" : ""}<th>Last reply</th><th class="r">Replies</th><th class="r">Tokens</th><th class="r">Estimated cost</th></tr></thead><tbody>${sessions}</tbody></table></div>
    <div class="ext-head"><h2>Models</h2><span class="hint">cache write and cache read are priced differently from input</span></div>
    <div class="table"><table><thead><tr><th>Model</th><th class="r">Replies</th><th class="r">Input</th><th class="r">Output</th><th class="r">Cache write</th><th class="r">Cache read</th><th class="r">Estimated cost</th></tr></thead><tbody>${models}</tbody></table></div>
    ${profs ? `<div class="ext-head"><h2>Profiles</h2><span class="hint">a reply copied into another conversation or profile counts once</span></div>
    <div class="table"><table><thead><tr><th>Profile</th><th class="r">Replies</th><th class="r">Tokens</th><th class="r">Estimated cost</th></tr></thead><tbody>${profs}</tbody></table></div>` : ""}
    ${T.unpriced_tokens ? `<p class="hint">* without the tokens of models that have no list price.</p>` : ""}`;
  bindUsage();
}
function bindUsage() {
  const u = S.use;
  $("#u-csv").onclick = async () => {
    try { toast("Exported usage as CSV", await download(`/api/usage.csv?profile=${encodeURIComponent(u.profile)}&days=${u.days}`, "cc-profiles-usage.csv")); }
    catch (e) { toast(e.message, "", true); }
  };
  document.querySelectorAll("[data-usess]").forEach(b => b.onclick = () => openUsageSession(u.data.sessions[+b.dataset.usess]));
}
// A session of the Usage tab opens in the Conversations tab, like a search result opens its tab.
async function openUsageSession(x) {
  goTab("conversations");
  Object.assign(S.conv, { profile: x.profile, q: "" });
  try { await loadConvProjects(); await openConvProject(x.project); await openConversation(x.session); }
  catch (e) { toast(e.message, "", true); }
}

// ---------- backups ----------
async function loadBackups() {
  S.backups = null; renderBackups();
  [S.backups, S.bkAuto] = await Promise.all([api("/api/backups"), api("/api/backups/auto").catch(() => null)]);
  renderBackups();
}
const size = n => n > 1e9 ? (n / 1e9).toFixed(1) + " GB" : n > 1e6 ? (n / 1e6).toFixed(1) + " MB" : n > 1e3 ? Math.round(n / 1e3) + " KB" : n + " B";
const when = t => new Date(t * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
function renderBackups() {
  if (S.tab !== "backups") return;
  if (!S.backups) { $("#main").innerHTML = `<div class="empty">${LOADER}</div>`; return; }
  const tot = S.backups.reduce((a, b) => a + b.size, 0);
  const where = S.backups[0]?.path.replace(/\/[^/]+$/, "") || "~/.cc-profiles/backups";
  $("#main").innerHTML = `<div class="toolbar"><span class="hint">${plural(S.backups.length, "backup", "backups")} · ${size(tot)} in <code>${esc(where)}</code>. Restoring undoes the operation and creates a backup of its own.</span>
      ${S.bkAuto ? `<label class="hint" style="margin-left:auto;display:flex;gap:6px;align-items:center">Delete backups older than
        <select id="bk-auto" aria-label="Automatic cleanup">${S.bkAuto.choices.map(d => `<option value="${d}" ${S.bkAuto.days === d ? "selected" : ""}>${d} days${d === S.bkAuto.default ? " (default)" : ""}</option>`).join("")}</select> automatically, except the ones you keep</label>` : ""}
      ${S.backups.length ? `<button class="btn" id="bk-prune" ${S.bkAuto ? "" : `style="margin-left:auto"`}>Delete old backups…</button>` : ""}</div>
    <div class="table">${S.backups.map(b => `<div class="bk"><div class="txt">
        <div class="t">${esc(b.title)} ${b.kept ? `<span class="badge b-shared" title="Never deleted by a cleanup">kept</span>` : ""} ${b.failed ? `<span class="badge b-warn" title="${esc(b.failed)}">incomplete: the operation failed halfway</span>` : ""} ${b.restored ? `<span class="badge b-none">restored ${esc(when(b.restored))}</span>` : ""}</div>
        <div class="m">${esc(when(b.created))} · ${plural(b.steps, "step", "steps")} · ${size(b.size)}${b.log.length ? " · " + b.log.map(esc).join(" · ") : ""}</div></div>
      <div class="acts">${b.steps ? `<button class="btn small" data-bchanges="${esc(b.name)}">Show changes</button>` : ""}
        ${b.restorable ? `<button class="btn small primary" data-restore="${esc(b.name)}">Restore</button>` : ""}
        <button class="btn small" data-bkeep="${esc(b.name)}" aria-pressed="${b.kept}" title="${b.kept ? "Let the cleanup delete it once it is old enough" : "Never delete it in a cleanup"}">${b.kept ? "Kept ✓" : "Keep"}</button>
        <button class="btn small danger" data-bdel="${esc(b.name)}" ${b.kept ? `disabled title="Kept: turn off Keep to delete it"` : ""}>Delete</button></div></div>`).join("") || `<div class="empty">No backups yet: one is created for every operation.</div>`}</div>`;
  $("#bk-prune")?.addEventListener("click", pruneBackups);
  $("#bk-auto")?.addEventListener("change", autoCleanup);
}
async function autoCleanup(e) {
  const days = +e.target.value;
  // what goes at once: the same rules as the server (never kept ones, nor incomplete ones not restored yet)
  const now = S.backups.filter(b => b.created < Date.now() / 1000 - days * 86400 && !b.kept && !(b.failed && !b.restored));
  const sub = `When cc-profiles starts and once a day while it runs, the backups older than ${days} days are deleted permanently, except the ones you keep and incomplete ones not restored yet. `
    + (now.length ? `<b>Deleted now: ${plural(now.length, "backup", "backups")}, ${size(now.reduce((a, b) => a + b.size, 0))}.</b> Press Keep on any you want to keep first.` : "Nothing to delete now.");
  if (!(await confirmBox(`Delete backups older than ${days} days automatically?`, sub, "Save", now.length ? "danger" : "primary"))) { e.target.value = S.bkAuto.days; return; }
  await run(() => api("/api/backups/auto", { days })).catch(() => {});
  loadBackups();
}
async function keepBackup(name) {
  const b = S.backups.find(x => x.name === name);
  await run(() => api("/api/backups/keep", { name, kept: !b.kept })).catch(() => {});
  loadBackups();
}
async function pruneBackups() {
  const old = days => S.backups.filter(b => b.created < Date.now() / 1000 - days * 86400 && !b.kept);
  const line = days => { const o = old(days); return o.length ? `${plural(o.length, "backup", "backups")}, ${size(o.reduce((a, b) => a + b.size, 0))}` : "none"; };
  const resP = modal({ title: "Delete old backups",
    sub: "Deleted backups cannot be restored afterwards. Kept backups are never deleted: press Keep on the ones of operations you might still want to undo.",
    body: `<div class="form"><label class="f">Delete the backups older than
        <select id="pr-days">${[7, 30, 90, 365].map(d => `<option value="${d}" ${d === 30 ? "selected" : ""}>${d} days</option>`).join("")}</select></label>
      <div class="hint" id="pr-what"></div></div>`,
    actions: [{ label: "Delete permanently", kind: "danger", value: "ok" }] });
  const sel = $("#pr-days"), what = () => { $("#pr-what").textContent = "To delete: " + line(+sel.value); };
  sel.onchange = what; what();
  const res = await resP;
  if (!res) return;
  await run(() => api("/api/backups/prune", { days: +$("#pr-days", res.el).value })).catch(() => {});
  loadBackups();
}
async function restoreBackup(name) {
  const b = S.backups.find(x => x.name === name);
  const newer = S.backups.filter(x => x.created > b.created && x.restorable && !x.title.startsWith("Before restoring"));
  const warn = newer.length ? `<br><br><span class="issue">${plural(newer.length, "newer operation has", "newer operations have")} not been undone yet (${newer.slice(0, 3).map(x => esc(x.title)).join(" · ")}${newer.length > 3 ? "…" : ""}). If they touched the same files, undo them first, newest first.</span>` : "";
  if (!(await confirmBox("Restore?", `<b>${esc(b.title)}</b><br>Undoes this operation by putting the files back as they were. Later changes to the same files are overwritten (but saved in the restore's own backup).${warn}`, "Restore"))) return;
  const r = await run(() => api("/api/backups/restore", { name })).catch(() => null);
  if (r?.problems?.length) toast("Steps not restored: " + r.problems.slice(0, 3).join(" · "), "", true);
  await refresh(); loadBackups();
}
// Read-only: every step of a backup in plain words, and for each file copied before a
// change a diff between that copy and the file as it is now.
const DIFF_STATUS = { same: "same as now", "hidden-only": "only hidden values changed", secret: "contents hidden",
  "too-big": "too big to compare", binary: "not a text file", dir: "now a folder", unavailable: "copy not available" };
function diffHtml(lines) {
  const kind = l => l.startsWith("@@") ? "h" : l.startsWith("+++ ") || l.startsWith("--- ") ? "f" : l[0] === "+" ? "a" : l[0] === "-" ? "d" : "";
  return `<pre class="diff" tabindex="0" aria-label="Diff: lines starting with - are in the backup, lines starting with + are there now">${lines.map(l => `<span class="${kind(l)}">${esc(l) || " "}</span>`).join("")}</pre>`;
}
async function showChanges(name, trigger) {
  const b = S.backups.find(x => x.name === name);
  const bg = document.createElement("div"); bg.className = "drawer-bg";
  const dr = document.createElement("aside"); dr.className = "drawer wide"; dr.setAttribute("role", "dialog"); dr.setAttribute("aria-modal", "true");
  dr.setAttribute("aria-label", `Changes of ${b.title}`);
  dr.innerHTML = `<div class="dh"><h2>${esc(b.title)}</h2><button class="btn small" id="ch-close">Close</button></div>
    <div class="db" id="ch-body"><div class="empty">${LOADER} Comparing the backup with the files as they are now…</div></div>`;
  const close = () => { bg.remove(); dr.remove(); document.removeEventListener("keydown", onKey); trigger?.focus(); };
  const onKey = e => { if (e.key === "Escape") close(); };
  bg.onclick = close; document.addEventListener("keydown", onKey);
  document.body.append(bg, dr);
  $("#ch-close", dr).onclick = close; $("#ch-close", dr).focus();
  let c;
  try { c = await api(`/api/backups/changes?name=${encodeURIComponent(name)}`); }
  catch (e) { $("#ch-body", dr).innerHTML = `<div class="empty">Error: ${esc(e.message)}</div>`; return; }
  const files = c.steps.filter(x => x.op === "copy"), other = c.steps.filter(x => x.op !== "copy");
  const open = files.length <= 3;
  const fileBlock = x => {
    const d = x.diff;
    const st = d.status === "changed" ? `+${d.added} −${d.removed}` : DIFF_STATUS[d.status] || d.status;
    return `<details class="chg" ${open && d.lines.length ? "open" : ""}><summary><code>${esc(x.path)}</code><span class="st">${esc(st)}</span></summary>
      ${d.notes.length ? `<ul class="notes">${d.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      ${d.lines.length ? diffHtml(d.lines) : d.status === "same" ? `<div class="hint" style="margin-top:6px">The file is the same as the copy in the backup${c.restored ? ": the backup was restored" : ""}.</div>` : ""}</details>`;
  };
  const now = x => x.op === "absent" || x.op === "mkdir" || x.op === "created" ? (x.now ? "" : " · no longer there") : "";
  const stepLine = x => `<li>${esc(x.text)}: <code>${esc(x.path)}</code>${x.to ? ` <span class="k">→</span> <code>${esc(x.to)}</code>${x.now ? "" : ` <span class="k">· no longer there</span>`}` : ""}${now(x) ? `<span class="k">${now(x)}</span>` : ""}</li>`;
  $("#ch-body", dr).innerHTML = `
    <div class="card"><h3>What this operation did</h3>
      <div class="hint">${esc(when(c.created))} · ${plural(c.steps.length, "step", "steps")} · ${plural(files.length, "file", "files")} copied before a change${files.length ? `, ${c.files_changed} different now` : ""}
        ${c.failed ? ` · <span class="issue">incomplete: ${esc(c.failed)}</span>` : ""}${c.restored ? ` · restored ${esc(when(c.restored))}` : ""}</div>
      <p class="hint" style="margin-bottom:0">Read-only. Each diff compares the copy kept in the backup (<code>-</code>) with the file as it is now (<code>+</code>), so it also shows changes made later. JSON is shown with sorted keys; login credentials, MCP environment variables and headers, and token-like values are hidden.</p></div>
    ${files.length ? `<div class="card"><h3>Files copied before a change</h3>${files.map(fileBlock).join("")}</div>` : ""}
    ${other.length ? `<div class="card"><h3>Other steps</h3><ul class="chsteps">${other.map(stepLine).join("")}</ul></div>` : ""}
    ${c.log.length ? `<div class="card"><h3>Notes</h3><ul class="chsteps">${c.log.map(l => `<li>${esc(l)}</li>`).join("")}</ul></div>` : ""}`;
}
async function deleteBackup(name) {
  const b = S.backups.find(x => x.name === name);
  if (!(await confirmBox("Delete this backup?", `<b>${esc(b.title)}</b> (${size(b.size)})<br>This is the only action that really erases something: it cannot be restored afterwards.`, "Delete permanently"))) return;
  await run(() => api("/api/backups/delete", { name })).catch(() => {});
  loadBackups();
}
