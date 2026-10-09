# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: subagents."""

import json
import os
import re

from .core import ApiError, Backup, pretty, profile, profiles, read_json, session_hint, write_text
from .sharing import primary, share_state
from .settings import no_targets, plan_message
from .info import names_in

# ---------------------------------------------------------------------------
# Subagents
# ---------------------------------------------------------------------------
# A subagent is <profile>/agents/<name>.md: YAML frontmatter, then the agent's system prompt.
# The fields and their values come from the frontmatter schema compiled into Claude Code
# (checked against AGENT_SCHEMA_VERSION, like SETTING_FIELDS): name and description are
# required; tools replaces the default set, disallowedTools removes from it. The form edits
# the fields in AGENT_FIELDS; any other key (hooks, mcpServers, skills, memory…) is kept as
# written, and the file editor edits everything. Plugins bring agents of their own, read-only.
AGENT_SCHEMA_VERSION = "2.1.294"
AGENT_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
AGENT_MODELS = [("inherit", "Same as the conversation"), ("sonnet", "Sonnet"), ("opus", "Opus"),
                ("haiku", "Haiku"), ("fable", "Fable")]
AGENT_EFFORTS = [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("max", "Max")]
AGENT_MODES = [("default", "Ask before acting"), ("plan", "Plan mode"), ("acceptEdits", "Accept edits"),
               ("auto", "Auto"), ("dontAsk", "Don't ask"), ("bypassPermissions", "Bypass permissions")]
AGENT_COLORS = ["red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"]
# The fields the form shows, in the order they are written: (key, kind)
AGENT_FIELDS = [("name", "text"), ("description", "text"), ("tools", "list"), ("disallowedTools", "list"),
                ("model", "select"), ("effort", "select"), ("permissionMode", "select"), ("maxTurns", "number"),
                ("color", "select")]
TOOL_SUGGESTIONS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebFetch", "WebSearch", "Agent",
                    "TodoWrite", "NotebookEdit", "Skill"]


# --- frontmatter --------------------------------------------------------------
def split_agent(text):
    """(entries, prompt): entries are (key, [lines]) for every top-level key of the frontmatter,
    in order, with the indented lines that belong to it. None when there is no frontmatter."""
    m = re.match(r"^---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)", text, re.S)
    if not m:
        return None, text
    entries = []
    for line in m.group(1).split("\n"):
        km = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:", line)
        if km:
            entries.append((km.group(1), [line]))
        elif entries:
            entries[-1][1].append(line)
        elif line.strip():
            entries.append(("", [line]))  # something before the first key: kept as it is
    return entries, text[m.end():]


def entry_value(lines):
    """A frontmatter value: a string, or a list for `- item` lines and [a, b]."""
    first = lines[0].split(":", 1)[1].strip()
    items = [re.sub(r"^\s*-\s*", "", l).strip() for l in lines[1:] if re.match(r"^\s*-\s", l)]
    if not first and items:
        return [unquote(i) for i in items]
    if first.startswith("[") and first.endswith("]"):
        return [unquote(i.strip()) for i in first[1:-1].split(",") if i.strip()]
    if not first and len(lines) > 1:  # a block scalar or a nested map: shown as text
        return "\n".join(l.strip() for l in lines[1:]).strip()
    return unquote(first)


def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        try:
            return json.loads(v)
        except ValueError:
            return v[1:-1]
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def as_list(v):
    """tools and disallowedTools: a YAML list, or a comma-separated string."""
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


def yaml_scalar(v):
    """A value on one line, quoted only when YAML would read it otherwise."""
    v = str(v)
    if v == "" or re.search(r":\s|\s#|^[\s\-?:,\[\]{}#&*!|>'\"%@`]|\s$", v) or v.lower() in ("true", "false", "null", "yes", "no"):
        return json.dumps(v, ensure_ascii=False)
    return v


def agent_fields(entries):
    out = {}
    for key, lines in entries or []:
        if key in dict(AGENT_FIELDS):
            v = entry_value(lines)
            out[key] = as_list(v) if dict(AGENT_FIELDS)[key] == "list" else (v if isinstance(v, str) else ", ".join(v))
    return out


def build_agent(fields, prompt, entries=None):
    """The file: the form's fields in AGENT_FIELDS order, then every other key of the old file as
    it was, then the prompt."""
    lines = []
    for key, kind in AGENT_FIELDS:
        v = fields.get(key)
        if kind == "list":
            v = as_list(v)
            if v:
                lines.append(f"{key}: {', '.join(v)}")
        elif v not in (None, ""):
            lines.append(f"{key}: {yaml_scalar(v)}")
    for key, raw in entries or []:
        if key not in dict(AGENT_FIELDS):
            lines += raw
    prompt = prompt.strip("\n")
    return "---\n" + "\n".join(lines) + "\n---\n" + (prompt + "\n" if prompt else "")


def check_fields(f):
    """The form's values, checked against the schema; raises ApiError with what to fix."""
    if not isinstance(f, dict):
        raise ApiError("Invalid agent")
    out = {}
    for key, kind in AGENT_FIELDS:
        v = f.get(key)
        if kind == "list":
            items = as_list(v)
            if any("\n" in i for i in items):
                raise ApiError(f"{key}: one tool per comma")
            out[key] = items
        else:
            v = "" if v is None else str(v).strip()
            if "\n" in v:
                raise ApiError(f"{key} must be one line")
            out[key] = v
    if not AGENT_NAME.fullmatch(out["name"]):
        raise ApiError("Invalid name: lowercase letters, digits and dashes, up to 64")
    if not out["description"]:
        raise ApiError("Write a description: Claude reads it to decide when to use the agent")
    if out["maxTurns"] and not (out["maxTurns"].isdigit() and int(out["maxTurns"]) > 0):
        raise ApiError("Max turns must be a whole number above 0, or empty")
    if out["effort"] and out["effort"] not in dict(AGENT_EFFORTS) and not out["effort"].isdigit():
        raise ApiError("Effort: low, medium, high, max or a number")
    return out


def check_raw(content, name):
    """A file written in the editor: frontmatter with name (the file's own) and a description."""
    entries, _ = split_agent(content or "")
    if entries is None:
        raise ApiError("The file must start with frontmatter between --- lines")
    f = agent_fields(entries)
    if f.get("name") != name:
        raise ApiError(f"name must stay {name}: rename the agent from the form")
    if not f.get("description"):
        raise ApiError("The frontmatter needs a description: Claude reads it to decide when to use the agent")
    return content if content.endswith("\n") else content + "\n"


# --- files --------------------------------------------------------------------
def agents_dir(prof):
    return os.path.join(prof["dir_abs"], "agents")


def agent_path(prof, name, must_exist=True):
    """Path of an agent file, protected against path traversal."""
    if not name or "/" in name or name.startswith(".") or "\\" in name:
        raise ApiError("Invalid agent name")
    path = os.path.join(agents_dir(prof), name + ".md")
    if must_exist and not os.path.isfile(path):
        raise ApiError(f"Agent not found in {prof['label']}: {name}", 404)
    return path


def agents_note(prof):
    """Who else sees a change to this profile's agents."""
    src = primary()
    if prof["id"] != src["id"]:
        return f"shared with {src['label']}" if share_state(prof, "agents", "dir")["shared"] else ""
    users = [p["label"] for p in profiles()[1:] if share_state(p, "agents", "dir")["shared"]]
    return f"shared with {', '.join(users)}" if users else ""


def summary(name, text, linked=False):
    entries, prompt = split_agent(text)
    f = agent_fields(entries)
    return {"name": name, "title": f.get("name") or name, "description": f.get("description", ""),
            "model": f.get("model", ""), "color": f.get("color", ""), "tools": f.get("tools", []),
            "disallowed": f.get("disallowedTools", []), "effort": f.get("effort", ""),
            "valid": entries is not None and bool(f.get("description")), "linked": linked,
            "lines": len(prompt.strip().splitlines())}


def plugin_agents(prof):
    """Agents that installed plugins bring: read-only, the plugin manages them."""
    inst = read_json(os.path.join(prof["dir_abs"], "plugins", "installed_plugins.json"), {}) or {}
    out = []
    for plugin, installs in sorted((inst.get("plugins") or {}).items()):
        installs = [installs] if isinstance(installs, dict) else (installs or [])
        path = (installs[0] if installs else {}).get("installPath") or ""
        d = os.path.join(path, "agents")
        for n in names_in(d, ".md") if path and os.path.isdir(d) else []:
            try:
                text = open(os.path.join(d, n + ".md"), errors="replace").read(8000)
            except OSError:
                continue
            out.append(dict(summary(n, text), plugin=plugin))
    return out


def list_agents(pid):
    prof = profile(pid)
    d = agents_dir(prof)
    items = []
    for n in names_in(d, ".md"):
        path = os.path.join(d, n + ".md")
        try:
            items.append(summary(n, open(path, errors="replace").read(20000), os.path.islink(path)))
        except OSError:
            continue
    return {"agents": items, "dir": pretty(d), "shared": agents_note(prof), "plugins": plugin_agents(prof),
            "options": {"model": AGENT_MODELS, "effort": AGENT_EFFORTS, "permissionMode": AGENT_MODES,
                        "color": [(c, c.capitalize()) for c in AGENT_COLORS]},
            "tools": TOOL_SUGGESTIONS, "schema_version": AGENT_SCHEMA_VERSION}


def agent_read(pid, name):
    path = agent_path(profile(pid), name)
    content = open(path, errors="replace").read()
    entries, prompt = split_agent(content)
    return {"content": content, "fields": agent_fields(entries), "prompt": prompt.strip("\n"),
            "valid": entries is not None, "other": [k for k, _ in entries or [] if k and k not in dict(AGENT_FIELDS)]}


def op_agent_save(pid, fields, prompt, old_name=None):
    """Create an agent (no old_name) or save the form of an existing one, renaming its file
    when the name changes. Keys the form does not show are kept."""
    prof = profile(pid)
    f = check_fields(fields)
    name = f["name"]
    path = agent_path(prof, name, must_exist=False)
    entries = None
    if old_name:
        old = agent_path(prof, old_name)
        entries, _ = split_agent(open(old, errors="replace").read())
        if name != old_name and os.path.lexists(path):
            raise ApiError(f"{prof['label']} already has an agent called {name}")
    elif os.path.lexists(path):
        raise ApiError(f"{prof['label']} already has an agent called {name}")
    text = build_agent(f, prompt or "", entries)
    title = (f"Edit agent {old_name}" + (f" → {name}" if name != old_name else "")) if old_name else f"New agent {name}"
    bk = Backup("agent-save" if old_name else "agent-create", f"{title} ({prof['label']})")
    bk.mkdir(agents_dir(prof))
    bk.copy(path, f"{name}.md")
    write_text(path, text)
    if old_name and name != old_name:
        bk.stash(old, f"{old_name}.md")
    verb = "saved" if old_name else "created"
    return {"message": f"Agent {name} {verb} in {prof['label']}." + session_hint(prof), "backup": bk.close()}


def op_agent_save_raw(pid, name, content):
    prof = profile(pid)
    path = agent_path(prof, name)
    text = check_raw(content, name)
    bk = Backup("agent-save", f"Edit agent {name} ({prof['label']})")
    bk.copy(path, f"{name}.md")
    write_text(path, text)
    return {"message": f"Agent {name} saved." + session_hint(prof), "backup": bk.close()}


def op_agent_delete(pid, name):
    prof = profile(pid)
    path = agent_path(prof, name)
    linked = os.path.islink(path)
    bk = Backup("agent-delete", f"Delete agent {name} ({prof['label']})")
    bk.stash(path, f"agent-{name}.md")
    msg = f"Agent {name} removed from {prof['label']}" + (" (only the link; its file is untouched)." if linked else ".")
    return {"message": msg, "backup": bk.close()}


def op_agent_copy(pid, name, to_pid):
    src, dst = profile(pid), profile(to_pid)
    path = agent_path(src, name)
    if src["id"] == dst["id"]:
        raise ApiError("Pick another profile")
    t = agent_path(dst, name, must_exist=False)
    if os.path.realpath(os.path.dirname(t)) == os.path.realpath(os.path.dirname(path)):
        raise ApiError(f"{dst['label']} already has it: the two profiles share their agents")
    if os.path.lexists(t):
        raise ApiError(f"{dst['label']} already has an agent called {name}: delete it there first")
    bk = Backup("agent-copy", f"Copy agent {name}: {src['label']} → {dst['label']}")
    bk.mkdir(os.path.dirname(t))
    bk.copy(t)
    write_text(t, open(os.path.realpath(path), errors="replace").read())
    return {"message": f"Agent {name} copied to {dst['label']}." + session_hint(dst), "backup": bk.close()}


def agent_all_plan(pid, name):
    """Which profiles copying an agent to every profile that lacks it changes, and which it skips."""
    src = profile(pid)
    path = agent_path(src, name)
    written = {os.path.realpath(os.path.dirname(path)): src["label"]}
    apply, skip = [], []
    for o in profiles():
        if o["id"] == pid:
            continue
        t = agent_path(o, name, must_exist=False)
        root = os.path.realpath(os.path.dirname(t))
        if root in written:
            reason = f"shares its agents with {written[root]}"
        elif os.path.lexists(t):
            reason = f"already has an agent called {name}"
        else:
            written[root] = o["label"]
            apply.append({"id": o["id"], "label": o["label"], "detail": f"copied to {pretty(t)}"})
            continue
        skip.append({"id": o["id"], "label": o["label"], "reason": reason})
    return {"name": name, "from": src["label"], "apply": apply, "skip": skip}


def op_agent_copy_all(pid, name):
    plan = agent_all_plan(pid, name)
    if not plan["apply"]:
        raise no_targets(plan)
    src = profile(pid)
    text = open(os.path.realpath(agent_path(src, name)), errors="replace").read()
    bk = Backup("agent-copy-all", f"Copy agent {name} from {src['label']} to every profile")
    for t in plan["apply"]:
        o = profile(t["id"])
        dst = agent_path(o, name, must_exist=False)
        bk.mkdir(os.path.dirname(dst))
        bk.copy(dst)
        write_text(dst, text)
        bk.note(f"{o['label']}: {t['detail']}")
    for s in plan["skip"]:
        bk.note(f"skipped {s['label']}: {s['reason']}")
    return {"message": plan_message(f"Agent {name} copied", plan), "backup": bk.close()}


def agent_texts(prof):
    """name -> file content, for the comparison of two profiles."""
    d = agents_dir(prof)
    out = {}
    for n in names_in(d, ".md"):
        try:
            out[n] = open(os.path.join(d, n + ".md"), errors="replace").read()
        except OSError:
            pass
    return out
