# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: custom slash commands."""

import os
import re

from .core import ApiError, Backup, pretty, profile, profiles, read_json, session_hint, write_text
from .command import COMMAND_MARK
from .sharing import primary, share_state
from .settings import no_targets, plan_message
from .agents import entry_value, split_agent, unquote

# ---------------------------------------------------------------------------
# Custom slash commands
# ---------------------------------------------------------------------------
# <profile>/commands/<name>.md is the command /<name>; a subfolder adds a namespace:
# commands/frontend/test.md is /frontend:test. The file is a prompt, with optional
# frontmatter (description, argument-hint, allowed-tools, model…) that Claude Code reads.
# The editor edits the whole file. /cc-profiles (COMMAND_MARK) is cc-profiles' own, kept
# up to date at start: shown, never edited or deleted here. Plugins bring commands of their own.
SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
FRONT_KEYS = ("description", "argument-hint", "allowed-tools", "model", "disable-model-invocation")
NEW_COMMAND = "---\ndescription: \nargument-hint: \n---\n\n$ARGUMENTS\n"


def commands_dir(prof):
    return os.path.join(prof["dir_abs"], "commands")


def check_name(name):
    """A command name: folders and file, without .md, separated by /."""
    parts = str(name or "").strip().strip("/").split("/")
    if len(parts) > 3 or not all(SEGMENT.fullmatch(p) and ".." not in p for p in parts) or parts[-1].endswith(".md"):
        raise ApiError("Invalid name: letters, digits, dots, dashes and underscores; a folder/name for a namespace")
    return "/".join(parts)


def command_path(prof, name, must_exist=True):
    name = check_name(name)
    path = os.path.join(commands_dir(prof), *name.split("/")) + ".md"
    if must_exist and not os.path.isfile(path):
        raise ApiError(f"Command not found in {prof['label']}: /{slash(name)}", 404)
    return path


def slash(name):
    return name.replace("/", ":")


def command_names(prof):
    """Every command file of the profile, as names: frontend/test for commands/frontend/test.md."""
    root = commands_dir(prof)
    out = []
    for cur, dirs, files in os.walk(root, followlinks=True):
        rel = os.path.relpath(cur, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and depth < 2)
        for f in sorted(files):
            if f.endswith(".md") and not f.startswith("."):
                n = f[:-3] if rel == "." else rel.replace(os.sep, "/") + "/" + f[:-3]
                try:
                    out.append(check_name(n))
                except ApiError:
                    continue
    return sorted(out)


def is_managed(text):
    return COMMAND_MARK in text[:400]


def commands_note(prof):
    """Who else sees a change to this profile's commands."""
    src = primary()
    if prof["id"] != src["id"]:
        return f"shared with {src['label']}" if share_state(prof, "commands", "dir")["shared"] else ""
    users = [p["label"] for p in profiles()[1:] if share_state(p, "commands", "dir")["shared"]]
    return f"shared with {', '.join(users)}" if users else ""


def front(text):
    """The frontmatter keys Claude Code reads, as text."""
    entries, body = split_agent(text)
    out = {}
    for key, lines in entries or []:
        if key in FRONT_KEYS:
            v = entry_value(lines) if key == "allowed-tools" else unquote(lines[0].split(":", 1)[1])
            out[key] = ", ".join(v) if isinstance(v, list) else v
    if not out.get("description"):  # Claude Code falls back to the first line of the prompt
        first = next((l.strip().lstrip("#").strip() for l in body.splitlines() if l.strip()), "")
        out["fallback"] = first[:200]
    return out


def command_summary(name, text, linked=False):
    f = front(text)
    return {"name": name, "slash": "/" + slash(name), "description": f.get("description", ""),
            "fallback": f.get("fallback", ""), "hint": f.get("argument-hint", ""), "model": f.get("model", ""),
            "tools": f.get("allowed-tools", ""), "linked": linked, "managed": is_managed(text)}


def plugin_commands(prof):
    """Commands that installed plugins bring: /plugin:name, read-only."""
    inst = read_json(os.path.join(prof["dir_abs"], "plugins", "installed_plugins.json"), {}) or {}
    out = []
    for plugin, installs in sorted((inst.get("plugins") or {}).items() if isinstance(inst.get("plugins"), dict) else []):
        installs = [installs] if isinstance(installs, dict) else (installs or [])
        path = (installs[0] if installs and isinstance(installs[0], dict) else {}).get("installPath") or ""
        for n in command_names({"dir_abs": path}) if path else []:
            try:
                text = open(os.path.join(path, "commands", *n.split("/")) + ".md", errors="replace").read(8000)
            except OSError:
                continue
            item = command_summary(n, text)
            item.update(plugin=plugin, slash=f"/{plugin.split('@')[0]}:{slash(n)}")
            out.append(item)
    return out


def list_commands(pid):
    prof = profile(pid)
    items = []
    for n in command_names(prof):
        path = command_path(prof, n)
        try:
            items.append(command_summary(n, open(path, errors="replace").read(20000), os.path.islink(path)))
        except OSError:
            continue
    return {"commands": items, "dir": pretty(commands_dir(prof)), "shared": commands_note(prof),
            "plugins": plugin_commands(prof), "template": NEW_COMMAND}


def command_read(pid, name):
    prof = profile(pid)
    path = command_path(prof, name)
    content = open(path, errors="replace").read()
    return dict(command_summary(check_name(name), content, os.path.islink(path)), content=content)


def check_content(content):
    if not isinstance(content, str) or not content.strip():
        raise ApiError("Write the prompt the command sends")
    entries, _ = split_agent(content)
    if content.lstrip().startswith("---") and entries is None:
        raise ApiError("The frontmatter is not closed: end it with a --- line")
    if is_managed(content):
        raise ApiError("Remove the line “" + COMMAND_MARK + "”: it marks cc-profiles' own command")
    return content if content.endswith("\n") else content + "\n"


def op_command_save(pid, name, content, new=False):
    """Create a command (new) or save the file of an existing one."""
    prof = profile(pid)
    name = check_name(name)
    path = command_path(prof, name, must_exist=not new)
    if new and os.path.lexists(path):
        raise ApiError(f"{prof['label']} already has /{slash(name)}")
    if not new and is_managed(open(path, errors="replace").read(400)):
        raise ApiError("/cc-profiles is cc-profiles' own command: it is kept up to date at every start")
    text = check_content(content)
    bk = Backup("command-create" if new else "command-save", f"{'New' if new else 'Edit'} command /{slash(name)} ({prof['label']})")
    bk.mkdir(os.path.dirname(path))
    bk.copy(path, os.path.basename(path))
    write_text(path, text)
    verb = "created" if new else "saved"
    return {"message": f"/{slash(name)} {verb} in {prof['label']}." + session_hint(prof), "backup": bk.close()}


def op_command_delete(pid, name):
    prof = profile(pid)
    path = command_path(prof, name)
    if is_managed(open(path, errors="replace").read(400)):
        raise ApiError("/cc-profiles is cc-profiles' own command: turn it off with cc-profiles install-command --off")
    linked = os.path.islink(path)
    bk = Backup("command-delete", f"Delete command /{slash(check_name(name))} ({prof['label']})")
    bk.stash(path, "command-" + os.path.basename(path))
    msg = f"/{slash(check_name(name))} removed from {prof['label']}" + (" (only the link; its file is untouched)." if linked else ".")
    return {"message": msg, "backup": bk.close()}


def command_copy_plan(pid, name, only=None):
    src = profile(pid)
    path = command_path(src, name)
    if is_managed(open(path, errors="replace").read(400)):
        raise ApiError("/cc-profiles is cc-profiles' own command: every profile gets it at start")
    written = {os.path.realpath(commands_dir(src)): src["label"]}
    apply, skip = [], []
    for o in profiles():
        if o["id"] == pid or (only and o["id"] != only):
            continue
        t = command_path(o, name, must_exist=False)
        root = os.path.realpath(commands_dir(o))
        if root in written:
            reason = f"shares its commands with {written[root]}"
        elif os.path.lexists(t):
            reason = f"already has /{slash(check_name(name))}"
        else:
            written[root] = o["label"]
            apply.append({"id": o["id"], "label": o["label"], "detail": f"copied to {pretty(t)}"})
            continue
        skip.append({"id": o["id"], "label": o["label"], "reason": reason})
    return {"name": check_name(name), "from": src["label"], "apply": apply, "skip": skip}


def copy_command(pid, plan, title):
    if not plan["apply"]:
        raise no_targets(plan)
    text = open(os.path.realpath(command_path(profile(pid), plan["name"])), errors="replace").read()
    bk = Backup("command-copy", title)
    for t in plan["apply"]:
        dst = command_path(profile(t["id"]), plan["name"], must_exist=False)
        bk.mkdir(os.path.dirname(dst))
        bk.copy(dst)
        write_text(dst, text)
        bk.note(f"{t['label']}: {t['detail']}")
    for s in plan["skip"]:
        bk.note(f"skipped {s['label']}: {s['reason']}")
    return bk.close()


def op_command_copy(pid, name, to):
    dst = profile(to)
    if dst["id"] == profile(pid)["id"]:
        raise ApiError("Pick another profile")
    plan = command_copy_plan(pid, name, only=dst["id"])
    if plan["skip"]:
        raise ApiError(f"{dst['label']} {plan['skip'][0]['reason']}")
    backup = copy_command(pid, plan, f"Copy command /{slash(plan['name'])}: {plan['from']} → {dst['label']}")
    return {"message": f"/{slash(plan['name'])} copied to {dst['label']}." + session_hint(dst), "backup": backup}


def op_command_copy_all(pid, name):
    plan = command_copy_plan(pid, name)
    backup = copy_command(pid, plan, f"Copy command /{slash(plan['name'])} from {plan['from']} to every profile")
    return {"message": plan_message(f"/{slash(plan['name'])} copied", plan), "backup": backup}
