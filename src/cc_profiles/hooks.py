# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: hooks, the commands Claude Code runs on its own events."""

import hashlib
import json
import os

from .core import ApiError, Backup, load_settings, pretty, profile, profiles, read_json, session_hint
from .settings import (effective, no_targets, plan_message, save_settings_file, settings_files)

# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------
# The "hooks" key of settings.json and settings.local.json:
#   {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "…", "timeout": 30}]}]}
# an event, then groups with a matcher, then the hooks of each group. The events and the
# command hook's fields come from the schema inside Claude Code (HOOKS_SCHEMA_VERSION). The
# form edits command hooks (command, timeout, async, status message) and keeps every other
# key of the hook as written; other hook types (prompt, agent, http, mcp_tool) are listed,
# copied and deleted here, and edited in the advanced editor. A hook is named by where it is
# (file, event, group, index) plus a fingerprint of its content, so a file changed since the
# page loaded it is never edited in the wrong place. Plugins bring hooks of their own, read-only.
HOOKS_SCHEMA_VERSION = "2.1.325"
HOOK_EVENTS = [
    ("PreToolUse", "Before a tool runs: can block it"),
    ("PostToolUse", "After a tool succeeds"),
    ("PostToolUseFailure", "After a tool fails"),
    ("PostToolBatch", "After a batch of tool calls"),
    ("PermissionRequest", "When Claude Code would ask for permission: can answer"),
    ("PermissionDenied", "When a tool call is denied"),
    ("UserPromptSubmit", "When you send a prompt, before Claude sees it"),
    ("UserPromptExpansion", "When a command expands into a prompt"),
    ("Notification", "When Claude Code notifies you"),
    ("MessageDisplay", "When a message is shown"),
    ("Stop", "When Claude finishes replying"),
    ("StopFailure", "When a reply ends with an error"),
    ("SubagentStart", "When a subagent starts"),
    ("SubagentStop", "When a subagent finishes"),
    ("SessionStart", "When a session starts or resumes"),
    ("SessionEnd", "When a session ends"),
    ("Setup", "When Claude Code sets up a repository"),
    ("PreCompact", "Before the conversation is compacted"),
    ("PostCompact", "After the conversation is compacted"),
    ("PreModelSwitch", "Before the model changes"),
    ("PostModelSwitch", "After the model changes"),
    ("TaskCreated", "When a task is created"),
    ("TaskCompleted", "When a task is completed"),
    ("TeammateIdle", "When a teammate agent is idle"),
    ("Elicitation", "When an MCP server asks you for input"),
    ("ElicitationResult", "After you answer an MCP server"),
    ("ConfigChange", "When a settings file changes"),
    ("InstructionsLoaded", "When CLAUDE.md or rules are loaded"),
    ("CwdChanged", "When the working folder changes"),
    ("FileChanged", "When a watched file changes"),
    ("DirectoryAdded", "When a folder is added to the session"),
    ("WorktreeCreate", "When a worktree is created"),
    ("WorktreeRemove", "When a worktree is removed"),
]
EVENT_NAMES = [e for e, _ in HOOK_EVENTS]
# What the matcher is matched against, per event: suggestions in the form, any text is accepted
TOOL_MATCHERS = ["Bash", "Edit|Write", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch", "Agent", "mcp__.*"]
MATCHERS = {"SessionStart": ["startup", "resume", "clear", "compact"], "SessionEnd": ["clear", "logout", "prompt_input_exit", "other"],
            "PreCompact": ["manual", "auto"], "PostCompact": ["manual", "auto"],
            "Notification": ["permission_prompt", "idle_prompt", "auth_success", "elicitation_dialog"]}
for _e in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied"):
    MATCHERS[_e] = TOOL_MATCHERS
FILES = ("settings", "local")
FILE_NAMES = {"settings": "settings.json", "local": "settings.local.json"}


def fingerprint(event, matcher, hook):
    return hashlib.sha1(json.dumps([event, matcher, hook], sort_keys=True).encode()).hexdigest()[:12]


def hook_text(h):
    """What a hook runs, on one line."""
    for k in ("command", "prompt", "url"):
        if isinstance(h.get(k), str):
            return h[k]
    if h.get("type") == "mcp_tool":
        return " ".join(str(h.get(k, "")) for k in ("server", "tool")).strip() or json.dumps(h)
    return json.dumps(h, ensure_ascii=False)


def groups_of(data):
    """event → list of groups, only the well-formed ones."""
    hooks = data.get("hooks") if isinstance(data, dict) else None
    out = {}
    for event, groups in (hooks.items() if isinstance(hooks, dict) else []):
        if isinstance(groups, list):
            out[event] = groups
    return out


def hook_rows(data, which=None, plugin=None):
    rows = []
    for event, groups in groups_of(data).items():
        for gi, g in enumerate(groups):
            if not isinstance(g, dict) or not isinstance(g.get("hooks"), list):
                continue
            matcher = g.get("matcher", "") if isinstance(g.get("matcher", ""), str) else ""
            for hi, h in enumerate(g["hooks"]):
                if not isinstance(h, dict):
                    continue
                row = {"event": event, "matcher": matcher, "group": gi, "index": hi, "type": h.get("type", ""),
                       "text": hook_text(h), "timeout": h.get("timeout"), "async": h.get("async") is True,
                       "status": h.get("statusMessage", ""), "fp": fingerprint(event, matcher, h),
                       "other": sorted(k for k in h if k not in ("type", "command", "timeout", "async", "statusMessage"))}
                if which:
                    row["file"] = which
                if plugin:
                    row["plugin"] = plugin
                rows.append(row)
    order = {e: i for i, e in enumerate(EVENT_NAMES)}
    return sorted(rows, key=lambda r: (order.get(r["event"], len(order)), r["event"]))


def plugin_hooks(prof):
    """Hooks that installed plugins bring (hooks/hooks.json): read-only, the plugin manages them."""
    inst = read_json(os.path.join(prof["dir_abs"], "plugins", "installed_plugins.json"), {}) or {}
    rows = []
    for plugin, installs in sorted((inst.get("plugins") or {}).items() if isinstance(inst.get("plugins"), dict) else []):
        installs = [installs] if isinstance(installs, dict) else (installs or [])
        path = (installs[0] if installs and isinstance(installs[0], dict) else {}).get("installPath") or ""
        data = read_json(os.path.join(path, "hooks", "hooks.json"), {}) if path else {}
        rows += hook_rows(data if isinstance(data, dict) else {}, plugin=plugin)
    return rows


def list_hooks(pid):
    prof = profile(pid)
    f = settings_files(prof)
    rows, files = [], {}
    for which in FILES:
        data, err = load_settings(f[which])
        files[which] = {"path": pretty(f[which]), "error": err, "shared": os.path.islink(f[which])}
        rows += hook_rows(data, which)
    off, src = effective(prof, "disableAllHooks")
    return {"hooks": rows, "files": files, "plugins": plugin_hooks(prof), "disabled": off is True,
            "disabled_in": FILE_NAMES.get(src, ""), "events": [{"name": e, "desc": d, "matchers": MATCHERS.get(e, [])}
                                                               for e, d in HOOK_EVENTS],
            "schema_version": HOOKS_SCHEMA_VERSION}


# --- writing --------------------------------------------------------------------
def load_file(prof, which):
    if which not in FILES:
        raise ApiError("Pick settings.json or settings.local.json")
    path = settings_files(prof)[which]
    data, err = load_settings(path)
    if err:
        raise ApiError(f"{os.path.basename(path)} has an error ({err}): fix it in the advanced editor")
    return data


def find_hook(prof, at):
    """(data, group list, group, hook) of the hook a client names, checked against its fingerprint."""
    if not isinstance(at, dict):
        raise ApiError("Invalid hook")
    data = load_file(prof, at.get("file"))
    groups = groups_of(data).get(at.get("event"))
    try:
        g = groups[int(at.get("group"))]
        h = g["hooks"][int(at.get("index"))]
        matcher = g.get("matcher", "") if isinstance(g.get("matcher", ""), str) else ""
        ok = isinstance(h, dict) and fingerprint(at["event"], matcher, h) == at.get("fp")
    except (TypeError, ValueError, IndexError, KeyError, AttributeError):
        ok = False
    if not ok:
        raise ApiError(f"This hook changed in {FILE_NAMES[at['file']]} since the page loaded it: reload and try again", 409)
    return data, groups, g, h


def remove_hook(data, event, g, h):
    """Take a hook out, then the group, the event and the hooks key it leaves empty."""
    g["hooks"].remove(h)
    groups = data["hooks"][event]
    if not g["hooks"]:
        groups.remove(g)
    if not groups:
        del data["hooks"][event]
    if not data["hooks"]:
        del data["hooks"]


def add_hook(data, event, matcher, hook):
    """Into the group with the same matcher, or a new group at the end."""
    hooks = data.get("hooks")
    if hooks is None:
        hooks = data["hooks"] = {}
    if not isinstance(hooks, dict):
        raise ApiError("“hooks” is not an object in the settings: fix it in the advanced editor")
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        raise ApiError(f"hooks.{event} is not a list: fix it in the advanced editor")
    for g in groups:
        if isinstance(g, dict) and isinstance(g.get("hooks"), list) and (g.get("matcher") or "") == matcher:
            g["hooks"].append(hook)
            return
    groups.append(dict({"matcher": matcher} if matcher else {}, hooks=[hook]))


def check_form(h):
    """The form's values: (file, event, matcher, fields of a command hook)."""
    if not isinstance(h, dict):
        raise ApiError("Invalid hook")
    event = str(h.get("event") or "")
    if event not in EVENT_NAMES:
        raise ApiError("Pick an event")
    matcher = str(h.get("matcher") or "").strip()
    command = str(h.get("command") or "").strip()
    if not command:
        raise ApiError("Write the command to run, e.g. npx prettier --write \"$CLAUDE_FILE_PATHS\"")
    if "\n" in matcher:
        raise ApiError("The matcher must be one line")
    fields = {"type": "command", "command": command}
    timeout = h.get("timeout")
    if timeout not in (None, ""):
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            timeout = 0
        if timeout <= 0:
            raise ApiError("Timeout: a whole number of seconds above 0, or empty")
        fields["timeout"] = timeout
    if h.get("async") is True:
        fields["async"] = True
    status = str(h.get("statusMessage") or "").strip()
    if status:
        fields["statusMessage"] = status
    which = h.get("file") or "settings"
    if which not in FILES:
        raise ApiError("Pick settings.json or settings.local.json")
    return which, event, matcher, fields


def op_hook_save(pid, hook, at=None):
    """Add a command hook (no at) or save the form of an existing one, moving it when its file,
    event or matcher changes. The hook's other keys are kept."""
    prof = profile(pid)
    which, event, matcher, fields = check_form(hook)
    path = settings_files(prof)
    datas = {}
    if at:
        datas[at.get("file")], _, g, old = find_hook(prof, at)
        if old.get("type", "command") != "command":
            raise ApiError(f"A {old.get('type')} hook is edited in the advanced editor")
        new = {k: v for k, v in old.items() if k not in ("timeout", "async", "statusMessage")}
        new.update(fields)
        same_place = which == at["file"] and event == at["event"] and matcher == (g.get("matcher") or "")
        if same_place:
            g["hooks"][int(at["index"])] = new
        else:
            remove_hook(datas[at["file"]], at["event"], g, old)
    else:
        new, same_place = fields, False
    if not same_place:
        if which not in datas:
            datas[which] = load_file(prof, which)
        add_hook(datas[which], event, matcher, new)
    title = f"{'Edit' if at else 'New'} hook {event}{' ' + matcher if matcher else ''} ({prof['label']})"
    bk = Backup("hook-save" if at else "hook-add", title)
    for w, data in datas.items():
        save_settings_file(prof, w, data, bk)
    bk.note(f"{event} [{matcher or 'every'}] → {new['command']} in {FILE_NAMES[which]}")
    shared = " (shared file: applies to the other profiles too)" if os.path.islink(path[which]) else ""
    return {"message": f"Hook {'saved' if at else 'added'} in {FILE_NAMES[which]}{shared}." + session_hint(prof),
            "backup": bk.close()}


def op_hook_delete(pid, at):
    prof = profile(pid)
    data, _, g, h = find_hook(prof, at)
    remove_hook(data, at["event"], g, h)
    bk = Backup("hook-delete", f"Delete hook {at['event']} ({prof['label']})")
    save_settings_file(prof, at["file"], data, bk)
    bk.note(f"{at['event']}: {hook_text(h)}")
    return {"message": f"Hook removed from {FILE_NAMES[at['file']]}.", "backup": bk.close()}


def has_hook(prof, event, matcher, hook):
    """Whether a profile already runs this hook for this event and matcher, in either file."""
    f = settings_files(prof)
    for which in FILES:
        for r in hook_rows(load_settings(f[which])[0], which):
            if r["event"] == event and r["matcher"] == matcher and r["fp"] == fingerprint(event, matcher, hook):
                return True
    return False


def hook_copy_plan(pid, at, only=None):
    """Which profiles copying a hook into their settings.json changes, and which it skips."""
    src = profile(pid)
    _, _, g, h = find_hook(src, at)
    matcher = g.get("matcher") or ""
    written = {os.path.realpath(settings_files(src)[at["file"]]): src["label"]}
    apply, skip = [], []
    for o in profiles():
        if o["id"] == pid or (only and o["id"] != only):
            continue
        path = settings_files(o)["settings"]
        real = os.path.realpath(path)
        if real in written:
            reason = f"shares settings.json with {written[real]}"
        elif has_hook(o, at["event"], matcher, h):
            reason = "already has this hook"
        elif load_settings(path)[1]:
            reason = "settings.json has an error: fix it in the advanced editor"
        else:
            written[real] = o["label"]
            apply.append({"id": o["id"], "label": o["label"], "detail": f"added to {at['event']} in settings.json"})
            continue
        skip.append({"id": o["id"], "label": o["label"], "reason": reason})
    return {"event": at["event"], "matcher": matcher, "text": hook_text(h), "hook": h, "from": src["label"],
            "apply": apply, "skip": skip}


def hook_all_plan(pid, at):
    plan = hook_copy_plan(pid, at)
    return {k: v for k, v in plan.items() if k != "hook"}


def copy_hook(plan, title):
    if not plan["apply"]:
        raise no_targets(plan)
    bk = Backup("hook-copy", title)
    for t in plan["apply"]:
        o = profile(t["id"])
        data = load_file(o, "settings")
        add_hook(data, plan["event"], plan["matcher"], plan["hook"])
        save_settings_file(o, "settings", data, bk)
        bk.note(f"{o['label']}: {t['detail']}")
    for s in plan["skip"]:
        bk.note(f"skipped {s['label']}: {s['reason']}")
    return bk.close()


def op_hook_copy(pid, at, to):
    dst = profile(to)
    if dst["id"] == profile(pid)["id"]:
        raise ApiError("Pick another profile")
    plan = hook_copy_plan(pid, at, only=dst["id"])
    if plan["skip"]:
        raise ApiError(f"{dst['label']} {plan['skip'][0]['reason']}")
    backup = copy_hook(plan, f"Copy hook {plan['event']}: {plan['from']} → {dst['label']}")
    return {"message": f"Hook copied to {dst['label']}'s settings.json." + session_hint(dst), "backup": backup}


def op_hook_copy_all(pid, at):
    plan = hook_copy_plan(pid, at)
    backup = copy_hook(plan, f"Copy hook {plan['event']} from {plan['from']} to every profile")
    return {"message": plan_message("Hook added", plan), "backup": backup}
