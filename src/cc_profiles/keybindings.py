# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: keyboard shortcuts (keybindings.json)."""

import json
import os

from .core import ApiError, Backup, pretty, profile, profiles, read_json, session_hint, write_json
from .settings import no_targets, plan_message

# ---------------------------------------------------------------------------
# Keybindings
# ---------------------------------------------------------------------------
# <profile>/keybindings.json, as Claude Code reads it (/keybindings):
#   {"bindings": [{"context": "Chat", "bindings": {"ctrl+e": "chat:externalEditor", "ctrl+u": null}}]}
# a block per context; an action, "command:<name>" to run a slash command, or null to
# unbind the key. The contexts come from Claude Code (KEYBINDINGS_SCHEMA_VERSION): an
# unknown one is only a warning, as in Claude Code. The file is edited whole, as JSON.
KEYBINDINGS_SCHEMA_VERSION = "2.1.325"
CONTEXTS = ["Global", "Chat", "Autocomplete", "Confirmation", "Help", "ProactivityMenu", "Transcript", "HistorySearch",
            "Task", "ThemePicker", "Settings", "Tabs", "Attachments", "Footer", "AbovePrompt", "AbovePromptInput",
            "AbovePromptSelect", "Pane", "PaneField", "MessageSelector", "DiffDialog", "DiffPanel", "FeedbackSurvey",
            "SessionTabs", "ModelPicker", "EffortSlider", "Select", "Plugin", "Scroll", "Agents"]
TEMPLATE = {"bindings": [{"context": "Chat", "bindings": {}}]}


def keys_path(prof):
    return os.path.join(prof["dir_abs"], "keybindings.json")


def check_bindings(data):
    """(errors, warnings) of keybindings data, as Claude Code checks the file."""
    errors, warnings = [], []
    if not isinstance(data, dict) or not isinstance(data.get("bindings"), list):
        return ['keybindings.json must have a "bindings" array'], []
    for i, block in enumerate(data["bindings"], 1):
        if not isinstance(block, dict):
            errors.append(f"Block {i} is not an object")
            continue
        ctx = block.get("context")
        if not isinstance(ctx, str):
            errors.append(f'Block {i} has no "context"')
        elif ctx not in CONTEXTS:
            warnings.append(f'Unknown context "{ctx}" in block {i}')
        if not isinstance(block.get("bindings"), dict):
            errors.append(f'Block {i} has no "bindings" object')
            continue
        for key, action in block["bindings"].items():
            if action is not None and not isinstance(action, str):
                errors.append(f'"{key}" in block {i}: the action must be a string, or null to unbind the key')
            elif isinstance(action, str) and action.startswith("command:") and ctx != "Chat":
                warnings.append(f'"{key}" runs {action}: command bindings work only in the Chat context')
    return errors, warnings


def rows_of(data):
    out = []
    for block in data.get("bindings") if isinstance(data, dict) and isinstance(data.get("bindings"), list) else []:
        if isinstance(block, dict) and isinstance(block.get("bindings"), dict):
            for key, action in block["bindings"].items():
                out.append({"context": str(block.get("context", "")), "key": key,
                            "action": action if isinstance(action, str) or action is None else json.dumps(action)})
    return out


def read_keys(prof):
    """(data, error) of a profile's file: data None when it is missing or not JSON."""
    path = keys_path(prof)
    if not os.path.exists(path):
        return None, None
    data = read_json(path)
    if data is None:
        return None, "not valid JSON"
    errors, _ = check_bindings(data)
    return data, errors[0] if errors else None


def get_keybindings(pid):
    prof = profile(pid)
    path = keys_path(prof)
    data, err = read_keys(prof)
    raw = open(path, errors="replace").read() if os.path.exists(path) else json.dumps(TEMPLATE, indent=2) + "\n"
    warnings = check_bindings(data)[1] if data is not None else []
    return {"path": pretty(path), "exists": os.path.exists(path), "shared": os.path.islink(path), "error": err,
            "warnings": warnings, "rows": rows_of(data), "raw": raw, "contexts": CONTEXTS,
            "others": [{"id": o["id"], "label": o["label"], "count": len(rows_of(read_keys(o)[0])),
                        "same": read_keys(o)[0] == data}
                       for o in profiles() if o["id"] != pid],
            "schema_version": KEYBINDINGS_SCHEMA_VERSION}


def parse(content):
    try:
        data = json.loads(content)
    except ValueError as e:
        raise ApiError(f"Invalid JSON at line {getattr(e, 'lineno', '?')}: {getattr(e, 'msg', e)}")
    errors, _ = check_bindings(data)
    if errors:
        raise ApiError(errors[0])
    return data


def op_keybindings_save(pid, content):
    prof = profile(pid)
    data = parse(content)
    path = keys_path(prof)
    bk = Backup("keybindings", f"Keyboard shortcuts of {prof['label']}")
    bk.copy(path, "keybindings.json")
    write_json(path, data)
    n = len(rows_of(data))
    return {"message": f"keybindings.json saved: {n} shortcut{'s' if n != 1 else ''}." + session_hint(prof),
            "backup": bk.close()}


def op_keybindings_delete(pid):
    prof = profile(pid)
    path = keys_path(prof)
    if not os.path.lexists(path):
        raise ApiError(f"{prof['label']} has no keybindings.json")
    bk = Backup("keybindings-delete", f"Delete keyboard shortcuts of {prof['label']}")
    bk.stash(path, "keybindings.json")
    return {"message": f"keybindings.json removed: {prof['label']} uses Claude Code's default shortcuts.",
            "backup": bk.close()}


def keybindings_plan(pid, only=None):
    """Which profiles giving this profile's keybindings.json changes, and which it skips."""
    src = profile(pid)
    data, err = read_keys(src)
    if data is None or err:
        raise ApiError(f"{src['label']} has no valid keybindings.json to copy")
    written = {os.path.realpath(keys_path(src)): src["label"]}
    apply, skip = [], []
    for o in profiles():
        if o["id"] == pid or (only and o["id"] != only):
            continue
        real = os.path.realpath(keys_path(o))
        theirs, _ = read_keys(o)
        if real in written:
            reason = f"shares keybindings.json with {written[real]}"
        elif theirs == data:
            reason = "already has the same shortcuts"
        else:
            written[real] = o["label"]
            n = len(rows_of(theirs))
            apply.append({"id": o["id"], "label": o["label"],
                          "detail": f"replaces its {n} shortcut{'s' if n != 1 else ''}" if os.path.exists(keys_path(o))
                          else "keybindings.json created"})
            continue
        skip.append({"id": o["id"], "label": o["label"], "reason": reason})
    return {"from": src["label"], "data": data, "apply": apply, "skip": skip}


def keybindings_all_plan(pid):
    return {k: v for k, v in keybindings_plan(pid).items() if k != "data"}


def copy_keys(plan, title):
    if not plan["apply"]:
        raise no_targets(plan)
    bk = Backup("keybindings-copy", title)
    for t in plan["apply"]:
        path = keys_path(profile(t["id"]))
        bk.copy(path, "keybindings.json")
        write_json(path, plan["data"])
        bk.note(f"{t['label']}: {t['detail']}")
    for s in plan["skip"]:
        bk.note(f"skipped {s['label']}: {s['reason']}")
    return bk.close()


def op_keybindings_copy(pid, to):
    dst = profile(to)
    if dst["id"] == profile(pid)["id"]:
        raise ApiError("Pick another profile")
    plan = keybindings_plan(pid, only=dst["id"])
    if plan["skip"]:
        raise ApiError(f"{dst['label']} {plan['skip'][0]['reason']}")
    backup = copy_keys(plan, f"Copy keyboard shortcuts: {plan['from']} → {dst['label']}")
    return {"message": f"Keyboard shortcuts copied to {dst['label']}." + session_hint(dst), "backup": backup}


def op_keybindings_copy_all(pid):
    plan = keybindings_plan(pid)
    backup = copy_keys(plan, f"Keyboard shortcuts of {plan['from']} in every profile")
    return {"message": plan_message("Keyboard shortcuts copied", plan), "backup": backup}
