# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Skills and MCP servers."""

import json
import os
import re
import shutil

from .core import (
    ApiError,
    Backup,
    active_session,
    parse_memory,
    pretty,
    profile,
    profiles,
    read_json,
    write_json,
    write_text,
)
from .sharing import primary, share_state
from .settings import no_targets, plan_message
from .info import names_in

# ---------------------------------------------------------------------------
# Skills and MCP servers
# ---------------------------------------------------------------------------
# Skills are folders in <profile>/skills/<name>/ with a SKILL.md. MCP servers live
# in the profile's .claude.json: "mcpServers" (user scope, every project) and
# projects[<path>].mcpServers (one project). Servers from plugins, from a
# project's .mcp.json and claude.ai connectors are configured elsewhere.
NEW_SKILL_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
MCP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
MCP_TYPES = ("stdio", "http", "sse")


def skill_dir(prof, name, must_exist=True):
    """Path of a skill folder, protected against path traversal. Existing skills
    may have any plain name; new ones must match NEW_SKILL_NAME."""
    if not name or "/" in name or name.startswith("."):
        raise ApiError("Invalid skill name")
    d = os.path.join(prof["dir_abs"], "skills", name)
    if must_exist and not os.path.isfile(os.path.join(d, "SKILL.md")):
        raise ApiError(f"Skill not found in {prof['label']}: {name}", 404)
    return d


def skills_note(prof):
    """Who else sees a change to this profile's skills."""
    src = primary()
    if prof["id"] != src["id"]:
        return f"shared with {src['label']}" if share_state(prof, "skills", "dir")["shared"] else ""
    users = [p["label"] for p in profiles()[1:] if share_state(p, "skills", "dir")["shared"]]
    return f"shared with {', '.join(users)}" if users else ""


def list_skills(pid):
    prof = profile(pid)
    root = os.path.join(prof["dir_abs"], "skills")
    items = []
    for n in names_in(root, dirs=True):
        md = os.path.join(root, n, "SKILL.md")
        if not os.path.isfile(md):
            continue
        meta = parse_memory(open(md, errors="replace").read(4000))
        files = sum(len(fs) for _, _, fs in os.walk(os.path.join(root, n))) - 1
        items.append({"name": n, "title": meta.get("name") or n, "description": meta.get("description", ""),
                      "files": files, "linked": os.path.islink(os.path.join(root, n))})
    return {"skills": items, "dir": pretty(root), "shared": skills_note(prof)}


def skill_read(pid, name):
    d = skill_dir(profile(pid), name)
    files = sorted(os.path.relpath(os.path.join(r, f), d) for r, _, fs in os.walk(d) for f in fs)
    return {"content": open(os.path.join(d, "SKILL.md"), errors="replace").read(),
            "files": [f for f in files if f != "SKILL.md"][:50]}


def op_skill_save(pid, name, content):
    prof = profile(pid)
    md = os.path.join(skill_dir(prof, name), "SKILL.md")
    bk = Backup("skill-edit", f"Edit skill {name} ({prof['label']})")
    bk.copy(md, f"{name}-SKILL.md")
    write_text(md, content if content.endswith("\n") else content + "\n")
    return {"message": f"Skill {name} saved.", "backup": bk.close()}


def op_skill_create(pid, name, description):
    prof = profile(pid)
    if not NEW_SKILL_NAME.fullmatch(name or ""):
        raise ApiError("Invalid skill name: lowercase letters, digits and dashes, up to 64")
    d = skill_dir(prof, name, must_exist=False)
    if os.path.lexists(d):
        raise ApiError(f"{prof['label']} already has a skill called {name}")
    description = " ".join((description or "").split())
    if not description:
        raise ApiError("Write a description: Claude uses it to decide when to use the skill")
    bk = Backup("skill-create", f"New skill {name} ({prof['label']})")
    bk.mkdir(d)
    md = os.path.join(d, "SKILL.md")
    bk.copy(md)
    write_text(md, f"---\nname: {name}\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n"
                   f"# {name}\n\nInstructions for Claude go here.\n")
    return {"message": f"Skill {name} created in {prof['label']}.", "backup": bk.close()}


def op_skill_delete(pid, name):
    prof = profile(pid)
    d = skill_dir(prof, name)
    bk = Backup("skill-delete", f"Delete skill {name} ({prof['label']})")
    linked = os.path.islink(d)
    bk.stash(d, f"skill-{name}")
    msg = f"Skill {name} removed from {prof['label']}" + (" (only the link; its folder is untouched)." if linked else ".")
    return {"message": msg, "backup": bk.close()}


def op_skill_copy(pid, name, to_pid):
    src, dst = profile(pid), profile(to_pid)
    d = skill_dir(src, name)
    if src["id"] == dst["id"]:
        raise ApiError("Pick another profile")
    t = skill_dir(dst, name, must_exist=False)
    if os.path.realpath(os.path.dirname(t)) == os.path.realpath(os.path.dirname(d)):
        raise ApiError(f"{dst['label']} already has it: the two profiles share their skills")
    if os.path.lexists(t):
        raise ApiError(f"{dst['label']} already has a skill called {name}: delete it there first")
    bk = Backup("skill-copy", f"Copy skill {name}: {src['label']} → {dst['label']}")
    bk.mkdir(os.path.dirname(t))
    shutil.copytree(os.path.realpath(d), t, symlinks=True)
    bk.created(t)
    return {"message": f"Skill {name} copied to {dst['label']}.", "backup": bk.close()}


def skill_all_plan(pid, name):
    """Which profiles copying a skill to every profile that lacks it changes, and which it
    skips: those sharing their skills folder with the source (or with a profile that gets it)."""
    src = profile(pid)
    d = skill_dir(src, name)
    written = {os.path.realpath(os.path.dirname(d)): src["label"]}
    apply, skip = [], []
    for o in profiles():
        if o["id"] == pid:
            continue
        t = skill_dir(o, name, must_exist=False)
        root = os.path.realpath(os.path.dirname(t))
        if root in written:
            reason = f"shares its skills with {written[root]}"
        elif os.path.lexists(t):
            reason = f"already has a skill called {name}"
        else:
            written[root] = o["label"]
            apply.append({"id": o["id"], "label": o["label"], "detail": f"copied to {pretty(t)}"})
            continue
        skip.append({"id": o["id"], "label": o["label"], "reason": reason})
    return {"name": name, "from": src["label"], "apply": apply, "skip": skip}


def op_skill_copy_all(pid, name):
    plan = skill_all_plan(pid, name)
    if not plan["apply"]:
        raise no_targets(plan)
    src = profile(pid)
    d = os.path.realpath(skill_dir(src, name))
    bk = Backup("skill-copy-all", f"Copy skill {name} from {src['label']} to every profile")
    for t in plan["apply"]:
        o = profile(t["id"])
        dst = skill_dir(o, name, must_exist=False)
        bk.mkdir(os.path.dirname(dst))
        shutil.copytree(d, dst, symlinks=True)
        bk.created(dst)
        bk.note(f"{o['label']}: {t['detail']}")
    for s in plan["skip"]:
        bk.note(f"skipped {s['label']}: {s['reason']}")
    return {"message": plan_message(f"Skill {name} copied", plan), "backup": bk.close()}


def mcp_summary(name, conf, scope):
    conf = conf if isinstance(conf, dict) else {}
    kind = conf.get("type") or ("stdio" if "command" in conf else "http")
    target = conf.get("url") or " ".join([str(conf.get("command", ""))] + [str(a) for a in conf.get("args") or []])
    return {"name": name, "scope": scope, "type": kind, "target": target.strip(),
            "env": sorted((conf.get("env") or {}).keys()), "headers": sorted((conf.get("headers") or {}).keys())}


def load_claude_json(prof):
    cfg = read_json(prof["config_abs"])
    if cfg is None:
        raise ApiError(f"{pretty(prof['config_abs'])} cannot be read: start Claude Code in {prof['label']} once")
    return cfg


def mcp_table(cfg, scope, create=False):
    """The mcpServers dict for a scope: "user", or a project path in .claude.json."""
    if scope == "user":
        holder = cfg
    else:
        holder = (cfg.get("projects") or {}).get(scope)
        if not isinstance(holder, dict):
            raise ApiError(f"Unknown project: {scope}")
    if create:
        if not isinstance(holder.get("mcpServers"), dict):
            holder["mcpServers"] = {}
        return holder["mcpServers"]  # the dict inside cfg, even when empty: writes go into it
    return holder.get("mcpServers") or {}


def list_mcp(pid):
    prof = profile(pid)
    cfg = read_json(prof["config_abs"], {}) or {}
    servers = [mcp_summary(n, c, "user") for n, c in sorted((cfg.get("mcpServers") or {}).items())]
    for path, pr in sorted((cfg.get("projects") or {}).items()):
        for n, c in sorted(((pr or {}).get("mcpServers") or {}).items()):
            servers.append(mcp_summary(n, c, path))
    return {"servers": servers, "config": pretty(prof["config_abs"]),
            "projects": sorted((cfg.get("projects") or {}).keys())}


def mcp_server(pid, scope, name):
    servers = mcp_table(load_claude_json(profile(pid)), scope)
    if name not in servers:
        raise ApiError(f"MCP server not found: {name}", 404)
    return {"config": servers[name]}


def check_mcp_config(conf):
    if not isinstance(conf, dict):
        raise ApiError("The server configuration must be a JSON object")
    kind = conf.get("type", "stdio")
    if kind not in MCP_TYPES:
        raise ApiError(f"Unknown type {kind}: use stdio, http or sse")
    if kind == "stdio" and not (isinstance(conf.get("command"), str) and conf["command"].strip()):
        raise ApiError("A stdio server needs a command")
    if kind != "stdio" and not re.match(r"^https?://", str(conf.get("url", ""))):
        raise ApiError(f"An {kind} server needs a URL starting with http:// or https://")
    for k in ("args",):
        if k in conf and not (isinstance(conf[k], list) and all(isinstance(a, str) for a in conf[k])):
            raise ApiError("args must be a list of strings")
    for k in ("env", "headers"):
        if k in conf and not (isinstance(conf[k], dict) and all(isinstance(v, str) for v in conf[k].values())):
            raise ApiError(f"{k} must map names to text values")


def session_hint(prof):
    return f" Restart the open session in {prof['label']} to load it." if active_session(prof) else \
        f" New Claude Code sessions in {prof['label']} will use it."


def op_mcp_save(pid, scope, name, conf, old_name=None):
    prof = profile(pid)
    if not MCP_NAME.fullmatch(name or ""):
        raise ApiError("Invalid server name: letters, digits, dots, dashes and underscores")
    check_mcp_config(conf)
    cfg = load_claude_json(prof)
    servers = mcp_table(cfg, scope, create=True)
    if old_name and old_name not in servers:
        raise ApiError(f"MCP server not found: {old_name}", 404)
    if name in servers and name != old_name:
        raise ApiError(f"There is already a server called {name} here")
    bk = Backup("mcp-save", f"{'Edit' if old_name else 'Add'} MCP server {name} ({prof['label']})")
    bk.copy(prof["config_abs"], "claude.json")
    if old_name and old_name != name:
        servers.pop(old_name)
    servers[name] = conf
    write_json(prof["config_abs"], cfg)
    where = "for every project" if scope == "user" else f"for {pretty(scope)}"
    return {"message": f"MCP server {name} saved {where}." + session_hint(prof), "backup": bk.close()}


def op_mcp_delete(pid, scope, name):
    prof = profile(pid)
    cfg = load_claude_json(prof)
    servers = mcp_table(cfg, scope)
    if name not in servers:
        raise ApiError(f"MCP server not found: {name}", 404)
    bk = Backup("mcp-delete", f"Remove MCP server {name} ({prof['label']})")
    bk.copy(prof["config_abs"], "claude.json")
    servers.pop(name)
    write_json(prof["config_abs"], cfg)
    return {"message": f"MCP server {name} removed.", "backup": bk.close()}


def op_mcp_copy(pid, scope, name, to_pid):
    src, dst = profile(pid), profile(to_pid)
    if src["id"] == dst["id"]:
        raise ApiError("Pick another profile")
    conf = mcp_server(pid, scope, name)["config"]
    if os.path.realpath(src["config_abs"]) == os.path.realpath(dst["config_abs"]):
        raise ApiError("The two profiles use the same .claude.json")
    cfg = load_claude_json(dst)
    servers = mcp_table(cfg, "user", create=True)
    if name in servers:
        raise ApiError(f"{dst['label']} already has a server called {name}")
    bk = Backup("mcp-copy", f"Copy MCP server {name}: {src['label']} → {dst['label']}")
    bk.copy(dst["config_abs"], "claude.json")
    servers[name] = json.loads(json.dumps(conf))
    write_json(dst["config_abs"], cfg)
    # Only the configuration: a sign-in (OAuth) is stored with the profile's credentials, never copied.
    msg = f"MCP server {name} copied to {dst['label']} for every project."
    if conf.get("type") in ("http", "sse"):
        msg += f" If it needs a sign-in, run /mcp in {dst['label']} to authenticate."
    return {"message": msg, "backup": bk.close()}


def mcp_all_plan(pid, scope, name):
    """Which profiles copying an MCP server to every profile that lacks it changes, and which it skips."""
    src = profile(pid)
    mcp_server(pid, scope, name)  # it exists
    written = {os.path.realpath(src["config_abs"]): src["label"]}
    apply, skip = [], []
    for o in profiles():
        if o["id"] == pid:
            continue
        real = os.path.realpath(o["config_abs"])
        cfg = read_json(o["config_abs"])
        if real in written:
            reason = f"uses the same .claude.json as {written[real]}"
        elif not isinstance(cfg, dict):
            reason = f"{pretty(o['config_abs'])} cannot be read: start Claude Code in it once"
        elif name in (cfg.get("mcpServers") or {}):
            reason = f"already has a server called {name}"
        else:
            written[real] = o["label"]
            apply.append({"id": o["id"], "label": o["label"], "detail": f"added to {pretty(o['config_abs'])} for every project"})
            continue
        skip.append({"id": o["id"], "label": o["label"], "reason": reason})
    return {"name": name, "from": src["label"], "apply": apply, "skip": skip}


def op_mcp_copy_all(pid, scope, name):
    plan = mcp_all_plan(pid, scope, name)
    if not plan["apply"]:
        raise no_targets(plan)
    src = profile(pid)
    conf = mcp_server(pid, scope, name)["config"]
    bk = Backup("mcp-copy-all", f"Copy MCP server {name} from {src['label']} to every profile")
    for t in plan["apply"]:
        o = profile(t["id"])
        cfg = load_claude_json(o)
        bk.copy(o["config_abs"], f"claude-{o['id']}.json")
        mcp_table(cfg, "user", create=True)[name] = json.loads(json.dumps(conf))
        write_json(o["config_abs"], cfg)
        bk.note(f"{o['label']}: {t['detail']}")
    for s in plan["skip"]:
        bk.note(f"skipped {s['label']}: {s['reason']}")
    msg = plan_message(f"MCP server {name} copied", plan)
    if conf.get("type") in ("http", "sse"):
        msg += " If it needs a sign-in, run /mcp in each profile to authenticate."
    return {"message": msg, "backup": bk.close()}
