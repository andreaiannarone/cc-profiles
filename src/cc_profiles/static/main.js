// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Andrea Iannarone
// Navigation, keyboard shortcuts and the click handler; starts the page. Loaded last.

// ---------- navigation and keyboard shortcuts ----------
// Tabs sit in one row, like GitHub's underline nav. The ones that do not fit go into
// the More menu, in order; the active tab always stays in the row.
const TAB_BUTTONS = [...document.querySelectorAll("#tabs button[data-tab]")];
function markTab(tab) {
  TAB_BUTTONS.forEach(b => {
    const on = b.dataset.tab === tab;
    b.classList.toggle("on", on);
    if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  showMore(false);
  layoutTabs();
}
function layoutTabs() {
  const nav = $("#tabs"), row = $(".tabrow", nav), menu = $("#moremenu"), more = $(".more", nav);
  TAB_BUTTONS.forEach(b => row.appendChild(b));
  more.hidden = true;  // measured without the More button, which would take room of its own
  more.hidden = row.scrollWidth <= row.clientWidth;
  if (more.hidden) { menu.replaceChildren(); return; }
  const gap = 8, avail = nav.clientWidth - more.offsetWidth - gap, w = b => b.offsetWidth + gap;
  const active = TAB_BUTTONS.find(b => b.classList.contains("on"));
  let used = active ? w(active) : 0, full = false;
  const keep = new Set(active ? [active] : []);
  for (const b of TAB_BUTTONS) {
    if (b === active) continue;
    if (!full && used + w(b) <= avail) { keep.add(b); used += w(b); } else full = true;
  }
  TAB_BUTTONS.forEach(b => (keep.has(b) ? row : menu).appendChild(b));
  $("#tabs-more").classList.toggle("on", !!menu.querySelector(".on"));
  $(".gdot", more).hidden = !menu.querySelector(".count:not([hidden])");
}
const syncNav = layoutTabs;
function showMore(open) {
  $("#moremenu").hidden = !open;
  $("#tabs-more").setAttribute("aria-expanded", open);
}
$("#tabs-more").onclick = e => { e.stopPropagation(); showMore($("#moremenu").hidden); };
document.addEventListener("click", e => { if (!e.target.closest(".more")) showMore(false); });
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#moremenu").hidden) { showMore(false); $("#tabs-more").focus(); } });
new ResizeObserver(() => layoutTabs()).observe($("#tabs"));
// g then a letter: the tab's initial, or a distinctive letter when the initial is taken
const GO_KEYS = [["p", "projects"], ["m", "memories"], ["c", "conversations"], ["u", "usage"], ["s", "skills"], ["a", "agents"], ["x", "mcp"], ["l", "plugins"],
                 ["r", "profiles"], ["o", "compare"], ["b", "backups"], ["h", "health"], ["t", "settings"]];
function showKeys() {
  const name = tab => $(`#tabs button[data-tab="${tab}"] .tl`).textContent;
  const row = (k, what) => `<dt>${k}</dt><dd>${what}</dd>`;
  modal({ title: "Keyboard shortcuts", cancel: "Close",
    sub: "They work anywhere except while you type in a field or a dialog is open.",
    body: `<dl class="keys">${row("<kbd>/</kbd>", "Search everything")}${row("<kbd>Esc</kbd>", "Close the search, a dialog or a panel")}${row("<kbd>?</kbd>", "Show this list")}
      ${GO_KEYS.map(([k, tab]) => row(`<kbd>g</kbd> <kbd>${k}</kbd>`, "Go to " + esc(name(tab)))).join("")}
      ${IN_APP ? `${row("<kbd>⌘</kbd> <kbd>1</kbd>…<kbd>9</kbd>", "Go to the first nine tabs")}${row("<kbd>⌘</kbd> <kbd>,</kbd>", "Settings")}
        ${row("<kbd>⌘</kbd> <kbd>F</kbd>", "Search everything")}${row("<kbd>⌘</kbd> <kbd>+</kbd> <kbd>−</kbd> <kbd>0</kbd>", "Zoom in, out, actual size")}` : ""}</dl>` });
}
let goPending = 0;
document.addEventListener("keydown", e => {
  if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || e.isComposing) return;
  const el = /** @type {HTMLElement} */ (e.target);
  if (el.isContentEditable || el.closest?.("input, textarea, select")) return;
  if (document.querySelector(".modal-bg, .drawer, .moremenu:not([hidden])")) return;
  if (goPending && Date.now() - goPending < 1500) {
    goPending = 0;
    const tab = GO_KEYS.find(([k]) => k === e.key.toLowerCase())?.[1];
    if (tab) { e.preventDefault(); $(`#tabs button[data-tab="${tab}"]`).click(); }
    return;
  }
  goPending = 0;
  if (e.key === "/") { e.preventDefault(); $("#gsearch").focus(); $("#gsearch").select(); }
  else if (e.key === "?") { e.preventDefault(); showKeys(); }
  else if (e.key === "g") goPending = Date.now();
});

// ---------- events ----------
document.addEventListener("click", async e => {
  const t = e.target.closest("button"); if (!t) return;
  if (t.dataset.tab) {
    S.tab = t.dataset.tab;
    markTab(S.tab);
    if (IN_APP) try { localStorage.setItem(APP_TAB, S.tab); } catch {}
    if (S.tab === "memories" && !S.mem.profile) { S.mem.profile = S.profiles[0]?.id; await loadMemProjects(); }
    if (S.tab === "conversations" && !S.conv.profile) { S.conv.profile = S.profiles[0]?.id; await loadConvProjects(); }
    if (S.tab === "health" && !S.health) return loadHealth();
    if (S.tab === "profiles") return loadSharing();
    if (S.tab === "compare") return loadCompare();
    if (S.tab === "usage") return loadUsage();
    if (EXT_TABS.includes(S.tab)) return loadExt();
    if (S.tab === "plugins") return loadPlugins();
    if (S.tab === "settings") return loadSettings(S.set?.profile || S.profiles[0]?.id);
    if (S.tab === "backups") return loadBackups();
    return render();
  }
  if (t.id === "keys-btn") return showKeys();
  if (t.hasAttribute("data-newprofile")) return newProfile();
  if (t.hasAttribute("data-install")) return installClaude();
  if (t.hasAttribute("data-install-log")) return showInstallLog();
  if (t.dataset.pedit) return editProfile(t.dataset.pedit);
  if (t.dataset.pexport) return exportProfile(t.dataset.pexport);
  if (t.hasAttribute("data-pimport")) return importProfile();
  if (t.dataset.pext) { S.tab = t.dataset.ext; markTab(S.tab); return loadExt(t.dataset.pext); }
  if (t.dataset.extprof) return loadExt(t.dataset.extprof);
  if (t.dataset.pdel) return deleteProfile(t.dataset.pdel);
  if (t.dataset.restore) return restoreBackup(t.dataset.restore);
  if (t.dataset.bchanges) return showChanges(t.dataset.bchanges, t);
  if (t.dataset.bdel) return deleteBackup(t.dataset.bdel);
  if (t.dataset.bkeep) return keepBackup(t.dataset.bkeep);
  if (t.dataset.uprof) { S.use.profile = t.dataset.uprof; return loadUsage(); }
  if (t.dataset.udays) { S.use.days = +t.dataset.udays; return loadUsage(); }
  if (t.dataset.filter) { S.filter = t.dataset.filter; return renderProjects(); }
  if (t.dataset.act) {
    const r = byName(t.dataset.name);
    if (t.dataset.act === "fixmove") { const i = r.issues.find(x => x.kind === "profile"); return doMove(r, i.from, i.to); }
    if (t.dataset.act === "relink") return doRelink(r);
    if (t.dataset.act === "merge") return doMerge(r);
    if (t.dataset.act === "rule") return doRule(r);
    if (t.dataset.act === "manage") return doManage(r);
    if (t.dataset.act === "term") return doTerminal(r);
  }
  if (t.dataset.mprof) { S.mem.profile = t.dataset.mprof; S.mem.project = null; S.mem.file = null; await loadMemProjects(); return renderMemories(); }
  if (t.dataset.mproj) return openMemProject(t.dataset.mproj);
  if (t.dataset.hlink) {
    if (!(await confirmBox("Relink to this folder?", `<code>${esc(t.dataset.path)}</code>`, "Relink"))) return;
    await run(() => api("/api/projects/relink", { project: t.dataset.hlink, profile: t.dataset.prof, path: t.dataset.path }));
    await refresh(); return loadHealth();
  }
  if (t.dataset.hrelink) { await doRelink(byName(t.dataset.hrelink), t.dataset.prof); return S.tab === "health" && loadHealth(); }
  if (t.dataset.hmerge) { await doMerge(byName(t.dataset.hmerge), t.dataset.prof); return S.tab === "health" && loadHealth(); }
  if (t.dataset.hdel) { await doDelete(byName(t.dataset.hdel), t.dataset.prof); return S.tab === "health" && loadHealth(); }
});
const openCard = c => c.dataset.agent ? openAgent(c.dataset.agent) : c.dataset.skill ? openSkill(c.dataset.skill)
  : c.dataset.mfile ? openMemFile(c.dataset.mfile) : null;  // plugin agents are read-only
document.addEventListener("click", e => { const c = e.target.closest(".mcard"); if (c) openCard(c); });
document.addEventListener("keydown", e => { const c = e.target.closest?.(".mcard"); if (c && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openCard(c); } });

function render() {
  if (S.tab === "projects") renderProjects();
  else if (S.tab === "memories") renderMemories();
  else if (S.tab === "conversations") renderConversations();
  else if (S.tab === "settings") renderSettings();
  else if (S.tab === "profiles") renderSharing();
  else if (S.tab === "compare") renderCompare();
  else if (S.tab === "usage") renderUsage();
  else if (S.tab === "search") renderSearch();
  else if (EXT_TABS.includes(S.tab)) renderExt();
  else if (S.tab === "plugins") renderPlugins();
  else if (S.tab === "backups") renderBackups();
  else renderHealth();
}
$("#about-btn").onclick = openAbout;
{
  // a hop and a blink when the page opens, then a different gesture each time the pointer reaches the title
  const logo = $("header .logo"), GESTURES = ["g-blink", "g-look", "g-antenna", "g-peek", "g-jump"];
  let next = 0;
  const play = cls => { logo.classList.remove("play", ...GESTURES); void logo.getBoundingClientRect(); logo.classList.add(cls); };
  $("header h1").addEventListener("mouseenter", () => { play(GESTURES[next]); next = (next + 1) % GESTURES.length; });
  play("play");
}
loadClaudeStatus();
checkWhatsNew();
loadUpdateStatus();
api("/api/terminal").then(t => { S.term = t; if (t.supported && S.tab === "projects" && S.projects) renderProjects(); }).catch(() => {});
setInterval(loadUpdateStatus, 3600 * 1000);  // a page left open learns about a new version too
refresh().then(() => {  // the Mac app opens on the tab it was closed on; a browser tab on Projects
  let tab = null;
  if (IN_APP) try { tab = localStorage.getItem(APP_TAB); } catch {}
  if (tab && tab !== S.tab) TAB_BUTTONS.find(b => b.dataset.tab === tab)?.click();
}, e => { $("#main").innerHTML = `<div class="empty">Error: ${esc(e.message)}</div>`; });
