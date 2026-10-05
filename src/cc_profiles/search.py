# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Search and compare (read-only)."""

import glob
import os
import re
import time

from .core import ApiError, cached_read, load_settings, parse_memory, pretty, profile, profiles, read_json
from .paths import memory_files, path_index, project_folders
from .settings import SETTING_FIELDS, effective, settings_files
from .info import names_in
from .extensions import mcp_summary

# ---------------------------------------------------------------------------
# Search and compare (read-only)
# ---------------------------------------------------------------------------
SEARCH_KINDS = ("projects", "memories", "skills", "mcp", "claude_md")
SEARCH_LIMIT = 30      # results per kind
SEARCH_SECONDS = 5     # stop looking after this, and say the results are partial
SEARCH_BYTES = 200_000  # read at most this much of one file


def read_head(path):
    try:
        with open(path, errors="replace") as f:
            return f.read(SEARCH_BYTES)
    except OSError:
        return ""


def snippet(text, q, width=60):
    """One-line excerpt around the first match of q (lowercase) in text, with the match
    position inside the excerpt so the UI can highlight it; None without a match."""
    i = text.lower().find(q)
    if i < 0:
        return None
    a, b = max(0, i - width), min(len(text), i + len(q) + width)
    pre, post = ("…" if a else ""), ("…" if b < len(text) else "")
    flat = re.sub(r"\s", " ", text[a:b])  # same length, so the offsets stay right
    return {"text": pre + flat + post, "at": len(pre) + i - a, "len": len(q)}


def warm_search():
    """Read every memory once, so the first search does not run into its time limit."""
    for p in profiles():
        for _, d, _ in project_folders(p):
            for f in memory_files(d):
                cached_read("head", os.path.join(d, "memory", f), read_head)


def search(q):
    q = (q or "").strip()
    if len(q) < 2:
        raise ApiError("Type at least 2 characters to search")
    ql = q.lower()
    deadline = time.time() + SEARCH_SECONDS
    res = {k: [] for k in SEARCH_KINDS}
    truncated = False

    def add(kind, item):
        nonlocal truncated
        if len(res[kind]) < SEARCH_LIMIT:
            res[kind].append(item)
        else:
            truncated = True

    def late():
        nonlocal truncated
        if time.time() > deadline:
            truncated = True
            return True
        return False

    idx = path_index()
    profs = profiles()
    projects, seen_skills, seen_md = {}, {}, set()
    for p in profs:
        if late():
            break
        root = p["dir_abs"]
        for d in sorted(glob.glob(os.path.join(root, "projects", "*", ""))):
            name = os.path.basename(d.rstrip("/"))
            path = pretty(idx.get(name) or name)
            m = snippet(path, ql)
            if m:
                if name in projects:
                    projects[name]["profiles"].append(p["id"])
                else:
                    projects[name] = {"kind": "project", "profile": p["id"], "profiles": [p["id"]], "title": path,
                                      "snippet": m, "open": {"project": name, "path": path}}
            for f in memory_files(d):
                text = cached_read("head", os.path.join(d, "memory", f), read_head)
                meta = parse_memory(text)
                title = meta.get("name") or f[:-3]
                m = snippet(title, ql) or snippet(meta.get("description", ""), ql) or snippet(text, ql)
                if m:
                    add("memories", {"kind": "memory", "profile": p["id"], "title": title, "where": path,
                                     "snippet": m, "open": {"project": name, "file": f}})
            if late():
                break
        sk = os.path.join(root, "skills")
        for n in names_in(sk, dirs=True):
            md = os.path.join(sk, n, "SKILL.md")
            if not os.path.isfile(md):
                continue
            real = os.path.realpath(os.path.join(sk, n))
            if real in seen_skills:  # a shared skills folder: one result, every profile that sees it
                seen_skills[real]["profiles"].append(p["id"])
                continue
            text = cached_read("head", md, read_head)
            m = snippet(n, ql) or snippet(text, ql)
            if m:
                item = {"kind": "skill", "profile": p["id"], "profiles": [p["id"]], "title": n,
                        "snippet": m, "open": {"skill": n}}
                seen_skills[real] = item
                add("skills", item)
            else:
                seen_skills[real] = {"profiles": []}
        cfg = read_json(p["config_abs"], {}) or {}
        tables = [("user", cfg.get("mcpServers") or {})] + [
            (path_, (pr or {}).get("mcpServers") or {}) for path_, pr in sorted((cfg.get("projects") or {}).items())]
        for scope, servers in tables:
            for n, conf in sorted(servers.items()):
                s = mcp_summary(n, conf, scope)  # names and targets only: env and header values never leave
                m = snippet(n, ql) or snippet(s["target"], ql)
                if m:
                    add("mcp", {"kind": "mcp", "profile": p["id"], "title": n, "where": scope if scope == "user"
                                else pretty(scope), "snippet": m, "open": {"scope": scope, "name": n}})
        cm = os.path.join(root, "CLAUDE.md")
        if os.path.isfile(cm) and os.path.realpath(cm) not in seen_md:
            seen_md.add(os.path.realpath(cm))
            hits = 0
            for i, line in enumerate(read_head(cm).splitlines(), 1):
                m = snippet(line, ql)
                if m:
                    add("claude_md", {"kind": "claude_md", "profile": p["id"], "title": f"CLAUDE.md, line {i}",
                                      "snippet": m, "open": {"line": i}})
                    hits += 1
                    if hits == 5:
                        break
    for item in projects.values():
        add("projects", item)
    return {"q": q, "results": res, "counts": {k: len(v) for k, v in res.items()}, "truncated": truncated}


def split3(a, b):
    """(only in a, only in b, in both), each sorted."""
    a, b = set(a), set(b)
    return sorted(a - b), sorted(b - a), sorted(a & b)


def skill_texts(prof):
    root = os.path.join(prof["dir_abs"], "skills")
    return {n: read_head(os.path.join(root, n, "SKILL.md")) for n in names_in(root, dirs=True)
            if os.path.isfile(os.path.join(root, n, "SKILL.md"))}


def plugin_lists(prof):
    inst = read_json(os.path.join(prof["dir_abs"], "plugins", "installed_plugins.json"), {}) or {}
    enabled, _ = effective(prof, "enabledPlugins")
    return (sorted((inst.get("plugins") or {}).keys()),
            sorted(k for k, v in (enabled or {}).items() if v) if isinstance(enabled, dict) else [])


def compare(a, b):
    pa, pb = profile(a), profile(b)
    if pa["id"] == pb["id"]:
        raise ApiError("Pick two different profiles")
    settings = []
    for fd in SETTING_FIELDS:
        va, sa = effective(pa, fd["key"])
        vb, sb = effective(pb, fd["key"])
        settings.append({"key": fd["key"], "label": fd["label"], "type": fd["type"],
                         "a": va, "a_source": sa, "b": vb, "b_source": sb, "same": va == vb})
    perms = {}
    for side, p in (("a", pa), ("b", pb)):
        data, _ = load_settings(settings_files(p)["settings"])
        pr = data.get("permissions") or {}
        perms[side] = {k: [x for x in pr.get(k, []) if isinstance(x, str)] for k in ("allow", "ask", "deny")}
    perm_diff = {}
    for k in ("allow", "ask", "deny"):
        oa, ob, both = split3(perms["a"][k], perms["b"][k])
        perm_diff[k] = {"only_a": oa, "only_b": ob, "both": both}
    ska, skb = skill_texts(pa), skill_texts(pb)
    oa, ob, both = split3(ska, skb)
    skills = {"only_a": oa, "only_b": ob, "both": [{"name": n, "same": ska[n] == skb[n]} for n in both],
              "shared": os.path.realpath(os.path.join(pa["dir_abs"], "skills"))
              == os.path.realpath(os.path.join(pb["dir_abs"], "skills"))}
    ma = (read_json(pa["config_abs"], {}) or {}).get("mcpServers") or {}
    mb = (read_json(pb["config_abs"], {}) or {}).get("mcpServers") or {}
    oa, ob, both = split3(ma, mb)
    row = lambda n, c: {k: v for k, v in mcp_summary(n, c, "user").items() if k in ("name", "type", "target")}
    mcp = {"only_a": [row(n, ma[n]) for n in oa], "only_b": [row(n, mb[n]) for n in ob],
           "both": [dict(row(n, ma[n]), same=ma[n] == mb[n]) for n in both]}
    mds = {}
    for side, p in (("a", pa), ("b", pb)):
        path = settings_files(p)["claude_md"]
        text = read_head(path) if os.path.isfile(path) else None
        mds[side] = {"exists": text is not None, "lines": len(text.splitlines()) if text else 0, "text": text}
    claude_md = {"a": {k: v for k, v in mds["a"].items() if k != "text"},
                 "b": {k: v for k, v in mds["b"].items() if k != "text"},
                 "same": mds["a"]["text"] == mds["b"]["text"],
                 "shared": os.path.realpath(settings_files(pa)["claude_md"])
                 == os.path.realpath(settings_files(pb)["claude_md"])}
    ia, ea = plugin_lists(pa)
    ib, eb = plugin_lists(pb)
    plugins = {}
    for k, (x, y) in (("installed", (ia, ib)), ("enabled", (ea, eb))):
        oa, ob, both = split3(x, y)
        plugins[k] = {"only_a": oa, "only_b": ob, "both": both}
    return {"a": {"id": pa["id"], "label": pa["label"]}, "b": {"id": pb["id"], "label": pb["label"]},
            "settings": settings, "permissions": {"a": perms["a"], "b": perms["b"], "diff": perm_diff},
            "skills": skills, "mcp": mcp, "claude_md": claude_md, "plugins": plugins}
