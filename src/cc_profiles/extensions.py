# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Skills, MCP servers and claude.ai connectors."""

import json
import os
import re
import shutil
import subprocess
import threading
import time

from .core import (
    HOME,
    ApiError,
    Backup,
    find_tool,
    load_settings,
    parse_memory,
    pretty,
    profile,
    profiles,
    read_json,
    session_hint,
    tool_env,
    write_json,
    write_text,
)
from .sharing import primary, share_state
from .settings import no_targets, plan_message, save_settings_file, settings_files, shared_note
from .info import names_in

# ---------------------------------------------------------------------------
# Skills and MCP servers
# ---------------------------------------------------------------------------
# Skills are folders in <profile>/skills/<name>/ with a SKILL.md. MCP servers live
# in the profile's .claude.json: "mcpServers" (user scope, every project) and
# projects[<path>].mcpServers (one project). Servers from plugins, from a
# project's .mcp.json are configured elsewhere; claude.ai connectors are at the end of this module.
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


# claude.ai connectors belong to the account, not to the profile: every profile signed in with
# the same account gets the same ones. A profile can still keep one out with a deny rule naming
# the whole server (mcp__claude_ai_Gmail), or all of them with "disableClaudeAiConnectors": true
# (any settings file with true wins). Claude Code records the ones it has connected in the
# profile's .claude.json, "claudeAiMcpEverConnected", as "claude.ai <name>", and never removes them.
CONNECTOR_PREFIX = "claude.ai "
CONNECTORS_OFF = "disableClaudeAiConnectors"
CONNECTORS_SEEN = "claudeAiMcpEverConnected"
CONNECTORS_URL = "https://claude.ai/customize/connectors"


def connector_rule(name):
    """The permission rule for a whole connector: Claude Code's own server name, as in its tool names."""
    slug = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_-]", "_", CONNECTOR_PREFIX + name)).strip("_")
    return "mcp__" + slug


def connector_rules(name):
    """Every deny rule that blocks the whole connector."""
    r = connector_rule(name)
    return (r, r + "__*")


def settings_pair(prof, writing=False):
    """settings.json and settings.local.json, each as (data, error). Before a write, both must be readable:
    a rule in a file that cannot be read could still block the connector."""
    f = settings_files(prof)
    pair = {which: load_settings(f[which]) for which in ("settings", "local")}
    for which, (_, err) in pair.items():
        if writing and err:
            raise ApiError(f"{os.path.basename(f[which])} has an error ({err}): fix it in the advanced editor")
    return pair


def deny_list(data):
    perms = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
    deny = perms.get("deny")
    return [r for r in deny if isinstance(r, str)] if isinstance(deny, list) else []


def seen_connectors(cfg):
    """The connectors Claude Code has connected in the profile. It only ever adds to this list:
    one removed or renamed on claude.ai stays until it is forgotten here."""
    seen = cfg.get(CONNECTORS_SEEN) if isinstance(cfg, dict) else None
    return {n[len(CONNECTOR_PREFIX):] for n in (seen if isinstance(seen, list) else [])
            if isinstance(n, str) and n.startswith(CONNECTOR_PREFIX)}


def connector_names(prof):
    """The connectors Claude Code has connected in this profile, the ones claude.ai listed at the
    last check, and the ones a deny rule names."""
    names = seen_connectors(read_json(prof["config_abs"], {}) or {}) | set(live_connectors(prof) or ())
    known = {connector_rule(n) for n in names}
    for data, _ in settings_pair(prof).values():
        for rule in deny_list(data):
            m = re.fullmatch(r"mcp__claude_ai_([A-Za-z0-9-]+(?:_[A-Za-z0-9-]+)*)(?:__\*)?", rule)
            if m and "mcp__claude_ai_" + m.group(1) not in known:
                names.add(m.group(1).replace("_", " "))
                known.add("mcp__claude_ai_" + m.group(1))
    return sorted(names, key=str.lower)


def list_connectors(pid):
    prof = profile(pid)
    files = settings_pair(prof)
    off = [which for which, (data, _) in files.items() if data.get(CONNECTORS_OFF) is True]
    seen = seen_connectors(read_json(prof["config_abs"], {}) or {})
    live = live_connectors(prof)
    out = []
    for name in connector_names(prof):
        rules = connector_rules(name)
        where = [which for which, (data, _) in files.items() if any(r in deny_list(data) for r in rules)]
        out.append({"name": name, "rule": rules[0], "blocked": bool(where), "where": where, "seen": name in seen,
                    "on_account": None if live is None else name in live})
    return {"connectors": out, "all_off": off, "url": CONNECTORS_URL, "check": check_state(prof),
            "errors": {which: err for which, (_, err) in files.items() if err}}


# The account's connectors as claude.ai lists them now. Only Claude Code knows them, with the
# profile's own sign-in, so cc-profiles asks it: `claude mcp list` prints one "claude.ai <name>: <url> -
# <status>" line per connector. It also starts every MCP server of the profile to check it, so it runs
# at most once an hour per profile, unless asked again. cc-profiles never reads the token.
LIVE_EVERY = 3600
_live = {}  # profile folder -> {"at": time, "names": [...] or None, "error": text or None}
_live_lock = threading.Lock()
CONNECTOR_LINE = re.compile(r"^claude\.ai (.+?): \S+ - ", re.M)


def live_connectors(prof):
    """The names claude.ai listed at the last successful check, or None if there is none."""
    got = _live.get(os.path.realpath(prof["dir_abs"]))
    return got["names"] if got else None


def check_state(prof):
    got = _live.get(os.path.realpath(prof["dir_abs"]))
    return {"at": got["at"], "error": got["error"]} if got else None


def check_skipped(prof):
    """Why claude.ai cannot be asked for this profile, or None."""
    cfg = read_json(prof["config_abs"], {}) or {}
    if not find_tool("claude"):
        return "Claude Code is not installed"
    if not (isinstance(cfg, dict) and (cfg.get("oauthAccount") or {}).get("emailAddress")):
        return f"{prof['label']} is not signed in to a claude.ai account"
    if any(d.get(CONNECTORS_OFF) is True for d, _ in settings_pair(prof).values()):
        return "connectors are off in this profile"
    return None


def run_mcp_list(prof):
    """Names of the account's connectors from `claude mcp list` in the profile, or raise ApiError."""
    env = tool_env()
    if prof["dir_abs"] != os.path.join(HOME, ".claude"):
        env["CLAUDE_CONFIG_DIR"] = prof["dir_abs"]
    else:
        env.pop("CLAUDE_CONFIG_DIR", None)
    try:  # in the profile folder: no project's .mcp.json is started
        r = subprocess.run([find_tool("claude"), "mcp", "list"], env=env, cwd=prof["dir_abs"],
                           capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        raise ApiError("claude mcp list did not answer within 90 seconds")
    except OSError as e:
        raise ApiError(f"claude mcp list could not start: {e}")
    names = sorted(set(CONNECTOR_LINE.findall(r.stdout)), key=str.lower)
    if r.returncode != 0:
        raise ApiError(f"claude mcp list failed: {(r.stderr or r.stdout).strip()[-300:]}")
    if not names:  # no answer from claude.ai looks the same as an account without connectors: keep the list
        raise ApiError("claude.ai listed no connectors: the list is kept as it is")
    return names


def connectors_check(pid, force=False):
    """Ask claude.ai (through Claude Code) which connectors the account has now; cached for an hour."""
    prof = profile(pid)
    key = os.path.realpath(prof["dir_abs"])
    skipped = check_skipped(prof)
    if skipped:
        return {"skipped": skipped, "gone": []}
    with _live_lock:
        got = _live.get(key)
        if force or not got or time.time() - got["at"] > LIVE_EVERY:
            try:
                got = {"at": time.time(), "names": run_mcp_list(prof), "error": None}
            except ApiError as e:
                got = {"at": time.time(), "names": got["names"] if got else None, "error": str(e)}
            _live[key] = got
    return {"skipped": None, "gone": gone_connectors(prof), "error": got["error"]}


def gone_connectors(prof):
    """Connectors in the profile's list that claude.ai no longer has, and that no deny rule blocks
    (a blocked one keeps its rule until it is turned on, so nothing is left behind)."""
    live = live_connectors(prof)
    if live is None:
        return []
    files = settings_pair(prof)
    blocked = {r for d, _ in files.values() for r in deny_list(d)}
    seen = seen_connectors(read_json(prof["config_abs"], {}) or {})
    return sorted((n for n in seen if n not in live and not blocked & set(connector_rules(n))), key=str.lower)


def op_connectors_sync(pid):
    """Take off the profile's list the connectors the last check found gone from the account."""
    prof = profile(pid)
    gone = gone_connectors(prof)
    if not gone:
        return {"message": f"The connectors of {prof['label']} are up to date."}
    cfg = load_claude_json(prof)
    bk = Backup("connectors-sync", f"claude.ai connectors no longer on the account ({prof['label']})")
    bk.copy(prof["config_abs"], "claude.json")
    drop = {CONNECTOR_PREFIX + n for n in gone}
    cfg[CONNECTORS_SEEN] = [n for n in cfg[CONNECTORS_SEEN] if n not in drop]
    write_json(prof["config_abs"], cfg)
    bk.note("removed " + ", ".join(gone))
    return {"message": f"No longer on your claude.ai account, taken off the list of {prof['label']}: {', '.join(gone)}.",
            "backup": bk.close()}


def op_connector(pid, name, enabled):
    """Let a connector into the profile (remove its deny rules) or keep it out (a deny rule in settings.json)."""
    prof = profile(pid)
    if name not in connector_names(prof):
        raise ApiError(f"Unknown connector: {name}", 404)
    rules = connector_rules(name)
    files = settings_pair(prof, writing=True)
    changes = {}
    for which, (data, _) in files.items():
        deny = deny_list(data)
        if enabled and any(r in deny for r in rules):
            changes[which] = [r for r in deny if r not in rules]
        elif not enabled and which == "settings" and not any(r in deny_list(d) for d, _ in files.values() for r in rules):
            changes[which] = deny + [rules[0]]
    if not changes:
        return {"message": f"{name} is already {'on' if enabled else 'off'} in {prof['label']}."}
    bk = Backup("connector", f"claude.ai connector {name} {'on' if enabled else 'off'} ({prof['label']})")
    for which, deny in changes.items():
        data = files[which][0]
        perms = dict(data.get("permissions") if isinstance(data.get("permissions"), dict) else {})
        if deny:
            perms["deny"] = deny
        else:
            perms.pop("deny", None)
        if perms:
            data["permissions"] = perms
        else:
            data.pop("permissions", None)
        save_settings_file(prof, which, data, bk)
        bk.note(f"{'removed' if enabled else 'added'} deny {rules[0]} in {os.path.basename(settings_files(prof)[which])}")
    path = settings_files(prof)["settings"]
    msg = f"{name} {'allowed again' if enabled else 'blocked'} in {prof['label']}{shared_note(path)}." + session_hint(prof)
    return {"message": msg, "backup": bk.close()}


def op_connector_forget(pid, name):
    """Take a connector off the profile's list, for one removed or renamed on claude.ai.
    If it still exists, Claude Code adds it back at its next session."""
    prof = profile(pid)
    cfg = load_claude_json(prof)
    if name not in seen_connectors(cfg):
        raise ApiError(f"Unknown connector: {name}", 404)
    rules = connector_rules(name)
    if any(r in deny_list(d) for d, _ in settings_pair(prof).values() for r in rules):
        raise ApiError(f"{name} is blocked in {prof['label']}: turn it on first, so no deny rule is left behind")
    bk = Backup("connector-forget", f"Forget claude.ai connector {name} ({prof['label']})")
    bk.copy(prof["config_abs"], "claude.json")
    cfg[CONNECTORS_SEEN] = [n for n in cfg[CONNECTORS_SEEN] if n != CONNECTOR_PREFIX + name]
    write_json(prof["config_abs"], cfg)
    return {"message": f"{name} forgotten in {prof['label']}. If it is still connected on claude.ai, "
                       f"it comes back at the next Claude Code session.", "backup": bk.close()}


def op_connectors_all(pid, enabled):
    """Turn every claude.ai connector on or off in the profile, with disableClaudeAiConnectors."""
    prof = profile(pid)
    files = settings_pair(prof, writing=True)
    if enabled:
        targets = [which for which, (data, _) in files.items() if CONNECTORS_OFF in data]
    else:
        targets = [] if any(d.get(CONNECTORS_OFF) is True for d, _ in files.values()) else ["settings"]
    if not targets:
        return {"message": f"claude.ai connectors are already {'on' if enabled else 'off'} in {prof['label']}."}
    bk = Backup("connectors", f"claude.ai connectors {'on' if enabled else 'off'} ({prof['label']})")
    for which in targets:
        data = files[which][0]
        if enabled:
            data.pop(CONNECTORS_OFF, None)
        else:
            data[CONNECTORS_OFF] = True
        save_settings_file(prof, which, data, bk)
        bk.note(f"{CONNECTORS_OFF} {'removed from' if enabled else '= true in'} {os.path.basename(settings_files(prof)[which])}")
    msg = (f"claude.ai connectors {'on' if enabled else 'off'} in {prof['label']}"
           f"{shared_note(settings_files(prof)['settings'])}." + session_hint(prof))
    return {"message": msg, "backup": bk.close()}
