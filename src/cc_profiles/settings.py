# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Claude Code settings."""

import glob
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time

from .core import (
    ApiError,
    Backup,
    find_tool,
    load_settings,
    parse_memory,
    pretty,
    profile,
    profiles,
    read_json,
    tool_env,
    write_json,
    write_text,
)

# ---------------------------------------------------------------------------
# Claude Code settings
# ---------------------------------------------------------------------------
# Dropdown options come from the settings schema inside the Claude Code binary
# (version SCHEMA_VERSION): where the schema only accepts some values there is a
# dropdown, where it accepts any string a free text field.
SCHEMA_VERSION = "2.1.289"
# Built-in output styles and their descriptions, as in the Claude Code binary. "default"
# is left out: it is the same as no value ("— default —" in the UI); field_options()
# still lists it when a profile has it set explicitly.
BUILTIN_STYLES = [
    ("Proactive", "Proactive", "Executes immediately, minimizes interruptions and prefers action over planning"),
    ("Concise", "Concise", "Responds tersely, leading with results and skipping preamble and narration"),
    ("Explanatory", "Explanatory", "Explains its implementation choices and codebase patterns"),
    ("Learning", "Learning", "Pauses and asks you to write small pieces of code for hands-on practice"),
]
# The fields of Claude Code's /config panel, in groups, plus the attribution texts.
# "file": "global" marks the keys /config keeps in .claude.json (the profile's global
# config) instead of settings.json; "also_settings" ones are edited where a settings
# file already has them. "default" is Claude Code's value when the key is missing;
# "drop_default" fields are removed rather than set to it, as /config does.
_ON = {"type": "bool", "default": True}
_OFF = {"type": "bool", "default": False}
_GLOBAL = {"file": "global"}
SETTING_FIELDS = [
    # model and replies
    dict(_ON, group="Replies", key="alwaysThinkingEnabled", label="Thinking mode", drop_default=True,
         help="Claude reasons before answering"),
    {"group": "Replies", "key": "outputStyle", "type": "select", "label": "Output style",
     "default_desc": "Claude Code's standard behavior",
     "help": "Built-in styles plus the profile's custom ones (output-styles/)", "options": "styles"},
    {"group": "Replies", "key": "language", "type": "text", "label": "Language",
     "help": "Language of the replies, e.g. English, Italiano", "suggest": []},
    dict(_ON, group="Replies", key="promptSuggestionEnabled", label="Prompt suggestions", drop_default=True,
         help="Suggest what to ask next"),
    dict(_ON, group="Replies", key="awaySummaryEnabled", label="Session recap", drop_default=True,
         help="A summary of what happened while you were away"),
    dict(_ON, **_GLOBAL, group="Replies", key="autoCompactEnabled", label="Auto-compact",
         help="Compact the conversation when the context fills up"),
    dict(_ON, group="Replies", key="precomputeCompactionEnabled", label="Precompute compaction",
         help="Prepare the compaction in advance, so it takes less time"),
    dict(_ON, **_GLOBAL, group="Replies", key="fileCheckpointingEnabled", label="Rewind code (checkpoints)",
         help="Keep snapshots of the files Claude edits, to undo them with /rewind"),
    {"group": "Replies", "key": "permissions.defaultMode", "type": "select", "default": "default", "label": "Default permission mode",
     "help": "How a session starts: asking first, planning, or editing on its own",
     "options": [("default", "Ask before acting"), ("plan", "Plan mode"), ("acceptEdits", "Accept edits"),
                 ("auto", "Auto"), ("dontAsk", "Don't ask")]},
    dict(_ON, group="Replies", key="useAutoModeDuringPlan", label="Use auto mode during plan",
         help="Plan mode runs with auto mode's permissions"),
    # interface
    {"group": "Interface", "key": "theme", "type": "select", "default": "dark", "label": "Theme", "file": "global", "also_settings": True,
     "help": "Colors of the terminal UI; custom themes (custom:…) are kept",
     "options": [("auto", "Auto"), ("dark", "Dark"), ("light", "Light"), ("dark-daltonized", "Dark, colorblind-friendly"),
                 ("light-daltonized", "Light, colorblind-friendly"), ("dark-ansi", "Dark, ANSI colors only"),
                 ("light-ansi", "Light, ANSI colors only")]},
    dict(_ON, group="Interface", key="spinnerTipsEnabled", label="Show tips", help="Tips while Claude works"),
    dict(_OFF, group="Interface", key="prefersReducedMotion", label="Reduce motion", help="Fewer animations"),
    dict(_OFF, **_GLOBAL, group="Interface", key="verbose", label="Verbose output", help="Show tool calls and results in full"),
    dict(_ON, **_GLOBAL, group="Interface", key="terminalProgressBarEnabled", label="Terminal progress bar",
         help="Progress in the terminal's tab or title bar, where the terminal supports it"),
    dict(_ON, **_GLOBAL, group="Interface", key="showTurnDuration", label="Show turn duration",
         help="How long each reply took"),
    {"group": "Interface", "key": "timeFormat", "type": "select", "default": "auto", "label": "Time format", "help": "How times are shown",
     "options": [("auto", "Auto"), ("12-hour", "12-hour"), ("24-hour", "24-hour"), ("24-hour-utc", "24-hour, UTC")]},
    {"group": "Interface", "key": "defaultView", "type": "select", "label": "Default view",
     "help": "Show the whole transcript, or only the conversation",
     "options": [("transcript", "Transcript"), ("chat", "Chat")]},
    dict(_ON, **_GLOBAL, group="Interface", key="autoScrollEnabled", label="Auto-scroll", help="Follow the output as it arrives"),
    dict(_ON, **_GLOBAL, group="Interface", key="prStatusFooterEnabled", label="Show PR status footer",
         help="The status of the branch's pull request under the prompt"),
    # editor and files
    {"group": "Editor and files", "key": "editorMode", "type": "select", "default": "normal", "label": "Editor mode", "file": "global",
     "also_settings": True, "help": "Key bindings for the prompt input", "options": [("normal", "Normal"), ("vim", "Vim")]},
    dict(_ON, **_GLOBAL, group="Editor and files", key="respectGitignore", label="Respect .gitignore in file picker",
         help="Files ignored by git are left out of @ mentions"),
    dict(_OFF, **_GLOBAL, group="Editor and files", key="copyFullResponse", label="Skip the /copy picker",
         help="/copy copies the whole last reply at once"),
    dict(_ON, **_GLOBAL, group="Editor and files", key="copyOnSelect", label="Copy on select",
         help="Selecting text with the mouse copies it"),
    dict(_OFF, **_GLOBAL, group="Editor and files", key="externalEditorContext", label="Show last response in external editor",
         help="Ctrl+G opens the prompt with Claude's last reply above it"),
    {"group": "Editor and files", "key": "diffTool", "type": "select", "default": "auto", "label": "Diff tool", "file": "global",
     "help": "Where proposed edits are shown", "options": [("auto", "Auto (the IDE when connected)"), ("terminal", "Terminal")]},
    dict(_OFF, **_GLOBAL, group="Editor and files", key="autoConnectIde", label="Auto-connect to IDE (external terminal)",
         help="Connect to a running IDE when Claude Code starts in another terminal"),
    dict(_ON, **_GLOBAL, group="Editor and files", key="autoInstallIdeExtension", label="Auto-install IDE extension",
         help="Install the Claude Code extension in VS Code and JetBrains IDEs"),
    {"group": "Editor and files", "key": "worktree.baseRef", "type": "select", "default": "fresh", "label": "Worktree base ref",
     "help": "Where new worktrees start: the default branch fetched fresh, or the current commit",
     "options": [("fresh", "Fresh default branch"), ("head", "Current commit (HEAD)")]},
    # notifications and updates
    {"group": "Notifications and updates", "key": "preferredNotifChannel", "type": "select", "default": "auto", "label": "Notifications",
     "file": "global", "help": "How Claude Code tells you it needs you",
     "options": [("auto", "Auto"), ("iterm2", "iTerm2"), ("terminal_bell", "Terminal bell"),
                 ("iterm2_with_bell", "iTerm2 with bell"), ("kitty", "Kitty"), ("ghostty", "Ghostty"),
                 ("notifications_disabled", "Off")]},
    {"group": "Notifications and updates", "key": "autoUpdatesChannel", "type": "select", "default": "latest", "label": "Auto-update channel",
     "help": "Latest releases, or the stable ones that have been out for a while",
     "options": [("latest", "Latest"), ("stable", "Stable")]},
    # commits and pull requests: a switch. Off is an empty text, which Claude Code reads as
    # "no attribution"; on is the key's absence, its own attribution. A custom text counts as on and is kept.
    {"group": "Commits and pull requests", "key": "attribution.commit", "type": "bool", "default": True, "off_value": "",
     "label": "Commit attribution", "help": "Claude adds itself to its commits (Co-Authored-By)"},
    {"group": "Commits and pull requests", "key": "attribution.pr", "type": "bool", "default": True, "off_value": "",
     "label": "Pull request attribution", "help": "Claude mentions itself in the pull requests it opens"},
    {"group": "Commits and pull requests", "key": "includeCoAuthoredBy", "type": "bool", "label": "Co-authored-by in commits",
     "deprecated": True, "only_if_set": True,
     "help": "Replaced by Commit attribution and Pull request attribution: remove it with ×"},
]
FIELD_BY_KEY = {fd["key"]: fd for fd in SETTING_FIELDS}
GLOBAL_FIELDS = {"autoUpdates": "bool"}  # the only .claude.json keys the app edits


def custom_styles(prof):
    """Custom output styles: .md files in <profile>/output-styles, name from frontmatter."""
    out = []
    for f in sorted(glob.glob(os.path.join(prof["dir_abs"], "output-styles", "*.md"))):
        try:
            meta = parse_memory(open(f).read())
        except OSError:
            continue
        name = meta.get("name") or os.path.basename(f)[:-3]
        desc = meta.get("description") or "No description"
        out.append((name, name, f"{desc} · output-styles/{os.path.basename(f)}", "Custom"))
    return out


def field_options(fd, prof, current):
    opts = fd.get("options")
    if opts is None:
        return None
    if opts == "styles":
        opts = [o + ("Built-in",) for o in BUILTIN_STYLES] + custom_styles(prof)
        if current == "default":
            opts.insert(0, ("default", "Default", "Claude Code's standard behavior, same as no value", "Built-in"))
    opts = [tuple(o) + (None,) * (4 - len(o)) for o in opts]  # (value, label, description, group)
    if isinstance(current, str) and current not in [o[0] for o in opts]:
        opts.append((current, f"{current} (current value)", "Not a known style: kept so it is not lost", None))
    return [{"value": v, "label": l, "desc": d, "group": g} for v, l, d, g in opts]


def get_key(data, key):
    """(found, value) of a key in settings data; "a.b" is key b inside the object a."""
    for part in key.split("."):
        if not isinstance(data, dict) or part not in data:
            return False, None
        data = data[part]
    return True, data


def set_key(data, key, value):
    *parents, last = key.split(".")
    for part in parents:
        if not isinstance(data.setdefault(part, {}), dict):
            raise ApiError(f"“{part}” is not an object in the settings: fix it in the advanced editor")
        data = data[part]
    data[last] = value


def pop_key(data, key):
    """Remove a key, and the objects that it leaves empty."""
    *parents, last = key.split(".")
    if parents:
        found, inner = get_key(data, ".".join(parents))
        if found and isinstance(inner, dict):
            inner.pop(last, None)
            if not inner:
                pop_key(data, ".".join(parents))
    else:
        data.pop(last, None)


def fields_for(profs):
    """The fields to show: a deprecated one only while some profile still has it."""
    return [fd for fd in SETTING_FIELDS
            if not fd.get("only_if_set") or any(effective(p, fd["key"])[1] for p in profs)]


def settings_files(prof):
    d = prof["dir_abs"]
    return {"settings": os.path.join(d, "settings.json"),
            "local": os.path.join(d, "settings.local.json"),
            "claude_md": os.path.join(d, "CLAUDE.md")}


def global_config(prof):
    """The profile's .claude.json, or {} when it is missing or unreadable."""
    data = read_json(prof["config_abs"], {})
    return data if isinstance(data, dict) else {}


def home_file(fd):
    """Where a field is written when no file has it yet."""
    return "global" if fd and fd.get("file") == "global" else "settings"


def effective(prof, key):
    """Value in use and the file it comes from: settings.local.json wins over settings.json;
    the keys /config keeps in .claude.json are read there ("global")."""
    fd = FIELD_BY_KEY.get(key)
    if home_file(fd) == "settings" or fd.get("also_settings"):
        f = settings_files(prof)
        for which in ("local", "settings"):
            found, value = get_key(load_settings(f[which])[0], key)
            if found:
                return value, which
    if home_file(fd) == "global":
        found, value = get_key(global_config(prof), key)
        if found:
            return value, "global"
    return None, None


def field_path(prof, which):
    return prof["config_abs"] if which == "global" else settings_files(prof)[which]


def file_error(prof, which):
    """Why a file cannot be edited, or None."""
    path = field_path(prof, which)
    if which == "global":
        return None if not os.path.exists(path) or isinstance(read_json(path), dict) else "invalid JSON"
    return load_settings(path)[1]


def write_field(prof, which, key, value, bk):
    """Set (or, with None, remove) a key in one of the profile's files, inside an open backup."""
    if which != "global":
        data, _ = load_settings(settings_files(prof)[which])
        pop_key(data, key) if value is None else set_key(data, key, value)
        return save_settings_file(prof, which, data, bk)
    path = prof["config_abs"]
    if file_error(prof, "global"):
        raise ApiError(f"{pretty(path)} cannot be read: it is not valid JSON")
    data = read_json(path, {})
    pop_key(data, key) if value is None else set_key(data, key, value)
    bk.copy(path, "claude.json")
    write_json(path, data)


def get_settings(pid):
    prof = profile(pid)
    f = settings_files(prof)
    files = {}
    for k in ("settings", "local"):
        _, err = load_settings(f[k])
        files[k] = {"path": pretty(f[k]), "exists": os.path.exists(f[k]), "shared": os.path.islink(f[k]),
                    "error": err, "raw": open(f[k]).read() if os.path.exists(f[k]) else "{}\n"}
    all_profs = profiles()
    others = [p for p in all_profs if p["id"] != pid]
    fields = []
    for fd in fields_for(all_profs):
        val, src = effective(prof, fd["key"])
        seen = {v for v in [effective(o, fd["key"])[0] for o in all_profs] if isinstance(v, str)}
        fields.append(dict({k: v for k, v in fd.items() if k != "options"}, value=val, source=src,
                           options=field_options(fd, prof, val),
                           suggest=sorted(set(fd.get("suggest", [])) | seen),
                           others=[{"id": o["id"], "label": o["label"], "value": effective(o, fd["key"])[0]}
                                   for o in others]))
    sett, _ = load_settings(f["settings"])
    local, _ = load_settings(f["local"])
    perms = sett.get("permissions") or {}
    cfg = read_json(prof["config_abs"], {}) or {}
    md = f["claude_md"]
    return {
        "files": files, "fields": fields, "schema_version": SCHEMA_VERSION,
        "permissions": {k: perms.get(k, []) for k in ("allow", "ask", "deny")},
        "permissions_local": {k: (local.get("permissions") or {}).get(k, []) for k in ("allow", "ask", "deny")},
        "claude_md": {"path": pretty(md), "exists": os.path.exists(md), "shared": os.path.islink(md),
                      "content": open(md).read() if os.path.exists(md) else ""},
        "global": {"path": pretty(prof["config_abs"]),
                   "autoUpdates": cfg.get("autoUpdates"),
                   "info": {"Account": (cfg.get("oauthAccount") or {}).get("emailAddress", ""),
                            "Install method": cfg.get("installMethod", ""),
                            "Startups": cfg.get("numStartups", ""),
                            "Local MCP servers": len(cfg.get("mcpServers") or {})}},
    }


def save_settings_file(prof, which, data, bk):
    path = settings_files(prof)[which]
    _, err = load_settings(path)
    if err:
        raise ApiError(f"{os.path.basename(path)} has an error ({err}): fix it in the advanced editor")
    bk.copy(path, os.path.basename(path))
    write_json(path, data)


def shared_note(path):
    return " (shared file: applies to the other profiles too)" if os.path.islink(path) else ""


def setting_field(key):
    fd = next((x for x in SETTING_FIELDS if x["key"] == key), None)
    if not fd:
        raise ApiError("This setting is not managed here: use the advanced editor")
    return fd


def check_setting_value(fd, prof, value):
    """The value to write (None removes the setting), checked against the field's type."""
    if value is None:
        return None
    if "off_value" in fd:  # a switch: true is the default, false the "off" text; a custom text is kept
        if isinstance(value, str):
            return value.strip() or fd["off_value"]
        if not isinstance(value, bool):
            raise ApiError("Invalid value: expected true or false")
        return None if value else fd["off_value"]
    if fd["type"] == "bool" and not isinstance(value, bool):
        raise ApiError("Invalid value: expected true or false")
    if fd["type"] == "number":
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ApiError("Invalid value: expected a whole number greater than zero")
    if fd["type"] == "text":
        value = str(value).strip() or None
    if fd.get("drop_default") and value == fd.get("default"):
        return None  # as /config does: the default is the key's absence
    if fd["type"] == "select":
        allowed = [o["value"] for o in field_options(fd, prof, effective(prof, fd["key"])[0])]
        if value not in allowed:
            raise ApiError(f"Invalid value for {fd['label'].lower()}: pick one of the options")
    return value


def op_setting(pid, key, value):
    prof = profile(pid)
    fd = setting_field(key)
    value = check_setting_value(fd, prof, value)
    _, src = effective(prof, key)
    which = src or home_file(fd)
    path = field_path(prof, which)
    bk = Backup("setting", f"{fd['label']} of {prof['label']}")
    write_field(prof, which, key, value, bk)
    if value is None:
        msg = f"{fd['label']}: back to the default."
    else:
        msg = f"Saved in {os.path.basename(path)}: {fd['label'].lower()} = {show_value(fd, prof, value)}{shared_note(path)}."
    bk.note(f"{key} = {json.dumps(value, ensure_ascii=False)} in {os.path.basename(path)}")
    return {"message": msg, "backup": bk.close()}


def op_settings_many(pid, values):
    """Save several fields of one profile at once: all are checked first, then written
    in one backup. Each goes where its value lives, as with a single save."""
    prof = profile(pid)
    if not isinstance(values, dict) or not values:
        raise ApiError("Nothing to save")
    checked = [(setting_field(k), check_setting_value(setting_field(k), prof, v)) for k, v in values.items()]
    bk = Backup("settings", f"{len(checked)} setting{'s' if len(checked) != 1 else ''} of {prof['label']}")
    shown = []
    for fd, value in checked:
        which = effective(prof, fd["key"])[1] or home_file(fd)
        write_field(prof, which, fd["key"], value, bk)
        bk.note(f"{fd['key']} = {json.dumps(value, ensure_ascii=False)} in {os.path.basename(field_path(prof, which))}")
        shown.append(f"{fd['label'].lower()} = {show_value(fd, prof, value)}")
    return {"message": f"Saved {len(checked)} setting{'s' if len(checked) != 1 else ''}: " + "; ".join(shown) + ".",
            "backup": bk.close()}


# Apply to all profiles: one operation, one backup for every profile it changes. The plan
# says which profiles change and which are skipped, with the reason; the UI shows it first.
def show_value(fd, prof, value):
    if value is None:
        return "the default"
    if "off_value" in fd:
        return "off" if value == fd["off_value"] else "custom text"
    if value == "":
        return "none"
    if isinstance(value, bool):
        return "on" if value else "off"
    opt = next((o for o in field_options(fd, prof, value) or [] if o["value"] == value), None)
    return opt["label"] if opt else json.dumps(value, ensure_ascii=False)


def setting_targets(prof, key, value):
    """The files of a profile to write so that its value of key becomes value: where the
    value lives, or every file that has it when the value goes back to the default."""
    f, fd = settings_files(prof), FIELD_BY_KEY.get(key)
    if value is None:
        found = [w for w in ("local", "settings") if get_key(load_settings(f[w])[0], key)[0]]
        if home_file(fd) == "global" and get_key(global_config(prof), key)[0]:
            found.append("global")
        return found
    return [effective(prof, key)[1] or home_file(fd)]


def no_targets(plan):
    return ApiError("No profile to change: " + "; ".join(f"{s['label']}: {s['reason']}" for s in plan["skip"]))


def plan_message(what, plan):
    n = len(plan["apply"])
    msg = f"{what} in {n} profile{'s' if n != 1 else ''}"
    return msg + (f", {len(plan['skip'])} skipped." if plan["skip"] else ".")


def setting_all_plan(pid, key):
    """Which profiles applying a profile's value of a setting to every other profile
    changes, and which it skips, with the reason. Changes nothing."""
    prof = profile(pid)
    fd = setting_field(key)
    value, _ = effective(prof, key)
    try:  # the type only: whether an option exists is checked in each profile
        if "off_value" not in fd:  # a switch stored as text: its stored value is copied as it is
            value = check_setting_value(dict(fd, type="text" if fd["type"] == "select" else fd["type"]), prof, value)
    except ApiError:
        raise ApiError(f"The value in {prof['label']} is not valid: fix it there first")
    apply, skip = [], []
    written = {}  # real file → the profile it is written for: a shared file is written once
    for o in profiles():
        if o["id"] == pid:
            continue
        cur, _ = effective(o, key)
        targets = setting_targets(o, key, value)
        paths = [field_path(o, w) for w in targets]
        errs = [os.path.basename(field_path(o, w)) for w in targets if file_error(o, w)]
        shared = next((written[os.path.realpath(p)] for p in paths if os.path.realpath(p) in written), None)
        if json.dumps(cur) == json.dumps(value):
            reason = f"already {show_value(fd, o, value)}"
        elif errs:
            reason = f"{errs[0]} has an error: fix it in the advanced editor"
        elif fd["type"] == "select" and value is not None and \
                value not in [x["value"] for x in field_options(fd, o, cur)]:
            reason = f"{value} is not available in this profile"
        elif shared:
            reason = f"shares {os.path.basename(paths[0])} with {shared}"
        else:
            for p in paths:
                written[os.path.realpath(p)] = o["label"]
            apply.append({"id": o["id"], "label": o["label"],
                          "detail": f"{show_value(fd, o, cur)} → {show_value(fd, o, value)} in "
                                    + ", ".join(os.path.basename(p) for p in paths)})
            continue
        skip.append({"id": o["id"], "label": o["label"], "reason": reason})
    return {"key": key, "label": fd["label"], "value": value, "shown": show_value(fd, prof, value),
            "from": prof["label"], "apply": apply, "skip": skip}


def op_setting_all(pid, key):
    plan = setting_all_plan(pid, key)
    if not plan["apply"]:
        raise no_targets(plan)
    value = plan["value"]
    bk = Backup("setting-all", f"{plan['label']} = {plan['shown']} in every profile")
    for t in plan["apply"]:
        o = profile(t["id"])
        for which in setting_targets(o, key, value):
            write_field(o, which, key, value, bk)
        bk.note(f"{o['label']}: {t['detail']}")
    for s in plan["skip"]:
        bk.note(f"skipped {s['label']}: {s['reason']}")
    return {"message": plan_message(f"{plan['label']} set to {plan['shown']}", plan), "backup": bk.close()}


PERMISSION_LISTS = ("allow", "ask", "deny")


def permission_all_plan(kind, rule):
    """Which profiles adding a permission rule to every profile changes, and which it skips."""
    if kind not in PERMISSION_LISTS:
        raise ApiError("Pick allow, ask or deny")
    rule = rule.strip() if isinstance(rule, str) else ""
    if not rule or "\n" in rule:
        raise ApiError("Write one rule, e.g. Bash(npm run test:*)")
    apply, skip = [], []
    written = {}
    for o in profiles():
        path = settings_files(o)["settings"]
        data, err = load_settings(path)
        perms = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
        real = os.path.realpath(path)
        if rule in (perms.get(kind) or []):
            reason = f"already in {kind}"
        elif err:
            reason = "settings.json has an error: fix it in the advanced editor"
        elif real in written:
            reason = f"shares settings.json with {written[real]}"
        else:
            written[real] = o["label"]
            also = [k for k in PERMISSION_LISTS if k != kind and rule in (perms.get(k) or [])]
            apply.append({"id": o["id"], "label": o["label"],
                          "detail": f"added to {kind} in settings.json"
                                    + (f" (also in {', '.join(also)}: deny wins over ask, ask over allow)" if also else "")})
            continue
        skip.append({"id": o["id"], "label": o["label"], "reason": reason})
    return {"list": kind, "rule": rule, "apply": apply, "skip": skip}


def op_permission_all(kind, rule):
    plan = permission_all_plan(kind, rule)
    if not plan["apply"]:
        raise no_targets(plan)
    bk = Backup("permission-all", f"Permission {kind} {plan['rule']} in every profile")
    for t in plan["apply"]:
        o = profile(t["id"])
        data, _ = load_settings(settings_files(o)["settings"])
        perms = dict(data.get("permissions") if isinstance(data.get("permissions"), dict) else {})
        perms[kind] = list(perms.get(kind) or []) + [plan["rule"]]
        data["permissions"] = perms
        save_settings_file(o, "settings", data, bk)
        bk.note(f"{o['label']}: {t['detail']}")
    for s in plan["skip"]:
        bk.note(f"skipped {s['label']}: {s['reason']}")
    return {"message": plan_message(f"{plan['rule']} added to {kind}", plan), "backup": bk.close()}


def op_permissions(pid, rules):
    prof = profile(pid)
    clean = {}
    for k in ("allow", "ask", "deny"):
        items = rules.get(k) or []
        if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
            raise ApiError("Invalid permissions format")
        clean[k] = [x.strip() for x in items if x.strip()]
    f = settings_files(prof)
    data, _ = load_settings(f["settings"])
    perms = dict(data.get("permissions") or {})  # keeps defaultMode and other keys
    for k, v in clean.items():
        if v:
            perms[k] = v
        else:
            perms.pop(k, None)
    if perms:
        data["permissions"] = perms
    else:
        data.pop("permissions", None)
    bk = Backup("permissions", f"Permissions of {prof['label']}")
    save_settings_file(prof, "settings", data, bk)
    bk.note(", ".join(f"{k}: {len(v)}" for k, v in clean.items()))
    return {"message": "Permissions saved: " + ", ".join(f"{len(v)} {k}" for k, v in clean.items())
                       + shared_note(f["settings"]) + ".", "backup": bk.close()}


def op_settings_raw(pid, which, content):
    if which not in ("settings", "local"):
        raise ApiError("Invalid file")
    prof = profile(pid)
    try:
        data = json.loads(content)
    except ValueError as e:
        raise ApiError(f"Invalid JSON at line {getattr(e, 'lineno', '?')}: {getattr(e, 'msg', e)}")
    if not isinstance(data, dict):
        raise ApiError("The file must contain a JSON object: { … }")
    path = settings_files(prof)[which]
    bk = Backup("settings-advanced", f"{os.path.basename(path)} of {prof['label']}")
    bk.copy(path, os.path.basename(path))
    write_json(path, data)
    return {"message": f"{os.path.basename(path)} saved{shared_note(path)}.", "backup": bk.close()}


def op_claude_md(pid, content):
    prof = profile(pid)
    path = settings_files(prof)["claude_md"]
    bk = Backup("claude-md", f"CLAUDE.md of {prof['label']}")
    bk.copy(path, "CLAUDE.md")
    write_text(path, content if content.endswith("\n") or not content else content + "\n")
    return {"message": "CLAUDE.md saved" + shared_note(path) + ". It applies from the next Claude Code session.",
            "backup": bk.close()}


def op_global(pid, key, value):
    if GLOBAL_FIELDS.get(key) != "bool" or not isinstance(value, bool):
        raise ApiError("This global setting cannot be changed here")
    prof = profile(pid)
    cfg = read_json(prof["config_abs"])
    if cfg is None:
        raise ApiError(f"{pretty(prof['config_abs'])} cannot be read")
    bk = Backup("global-setting", f"{key} of {prof['label']}")
    bk.copy(prof["config_abs"], "claude.json")
    cfg[key] = value
    write_json(prof["config_abs"], cfg)
    return {"message": f"{key}: {'on' if value else 'off'}.", "backup": bk.close()}


# ---------------------------------------------------------------------------
# Status line
# ---------------------------------------------------------------------------
# statusLine in settings.json runs a command that prints one line. cc-profiles can write
# that command itself: a POSIX sh script in the profile folder that reads the JSON Claude
# Code sends on stdin with jq. It finds the profile's label at run time (in
# ~/.cc-profiles/config.json), so a script reached through a shared settings.json still
# names the right profile. Only a script with STATUS_MARK on its first line is rewritten.
STATUS_MARK = "# managed by cc-profiles: status line"
# Tokens since the last prompt typed by the user (a user line whose content is a string, not
# a tool result) and in the whole session, from the usage of every assistant line of the
# conversation file. Lines that do not parse (one being written) are skipped.
STATUS_TOKENS_JQ = (
    'def h: if . >= 1000000 then ((. * 10 / 1000000 | floor) / 10 | tostring) + "M" '
    'elif . >= 1000 then (. / 1000 | floor | tostring) + "k" else tostring end; '
    'reduce (inputs | fromjson? | objects) as $l ({s: 0, t: 0}; '
    'if $l.type == "user" and ($l.message.content | type) == "string" then .t = 0 '
    'elif $l.type == "assistant" then ($l.message.usage // {}) as $u '
    '| (($u.input_tokens // 0) + ($u.cache_creation_input_tokens // 0) + ($u.cache_read_input_tokens // 0) + ($u.output_tokens // 0)) as $x '
    '| .s += $x | .t += $x else . end) | "question:\\(.t | h) session:\\(.s | h)"')
# (id, label, sample, brackets by default, sh code). The code reads the JSON with j and
# adds one piece with add TEXT [SGR color]; $cwd is the session's folder, $cfg the
# profile's .claude.json. Colors are the terminal's own 16 (90 is its grey).
STATUS_PARTS = [
    ("path", "Path", "~/code/api", "none",
     'if [ -n "$cwd" ]; then case $cwd in "$HOME") p="~" ;; "$HOME"/*) p="~${cwd#"$HOME"}" ;; *) p=$cwd ;; esac; add "$p" 36; fi'),
    ("folder", "Folder", "api", "none", '[ -n "$cwd" ] && add "$(basename "$cwd")" 36'),
    ("branch", "Git branch (* when changed)", "main*", "round",
     'if [ -n "$cwd" ]; then b=$(git -C "$cwd" --no-optional-locks branch --show-current 2>/dev/null)\n'
     '[ -z "$b" ] && b=$(git -C "$cwd" --no-optional-locks rev-parse --short HEAD 2>/dev/null)\n'
     'if [ -n "$b" ]; then git -C "$cwd" --no-optional-locks diff --quiet --ignore-submodules HEAD 2>/dev/null || b="$b*"; '
     'add "$b" "2;36"; fi; fi'),
    ("profile", "Profile", "Default", "round",
     'label=$(jq -r --arg d "$dir" --arg h "$(cd "$HOME" 2>/dev/null && pwd -P)" \'.profiles[]? | select((.dir | sub("^~"; $h) | rtrimstr("/")) == $d) | .label\' '
     '"$HOME/.cc-profiles/config.json" 2>/dev/null | head -n 1)\nadd "${label:-$name}" 1'),
    ("email", "Account email", "me@example.com", "none", 'add "$(jq -r \'.oauthAccount.emailAddress // empty\' "$cfg" 2>/dev/null)" 90'),
    ("model", "Model", "Opus", "square", 'add "$(j .model.display_name)" 35'),
    ("effort", "Effort", "high", "none", 'add "$(j .effort.level)" 35'),
    ("style", "Output style", "Explanatory", "curly", 'add "$(j .output_style.name)" 33'),
    ("pr", "Pull request", "PR #42", "none", 'v=$(j .pr.number); [ -n "$v" ] && add "PR #$v" 35'),
    ("context", "Context used", "ctx:42%", "angle",
     'v=$(j \'.context_window.used_percentage | floor\'); if [ -n "$v" ]; then c=34; [ "$v" -ge 70 ] && c=33; '
     '[ "$v" -ge 90 ] && c=31; add "ctx:$v%" $c; fi'),
    ("cost", "Session cost", "$1.27", "none", 'v=$(j .cost.total_cost_usd); [ -n "$v" ] && add "$(printf \'$%.2f\' "$v")" 32'),
    ("lines", "Lines changed", "+120 -34", "none",
     'a=$(j .cost.total_lines_added); r=$(j .cost.total_lines_removed)\n'
     'if [ -n "$a$r" ]; then if [ "$C" = 1 ]; then add "$(printf \'\\033[32m+%s\\033[0m \\033[31m-%s\\033[0m\' "${a:-0}" "${r:-0}")"; '
     'else add "+${a:-0} -${r:-0}"; fi; fi'),
    ("duration", "Session time", "12m", "none",
     'v=$(j \'.cost.total_duration_ms | floor\'); if [ -n "$v" ]; then m=$((v / 60000)); '
     'if [ "$m" -ge 60 ]; then add "$((m / 60))h $(printf %02d $((m % 60)))m" 2; else add "${m}m" 2; fi; fi'),
    ("tokens", "Tokens (reads the whole conversation file at each refresh)", "question:12k session:340k", "none",
     't=$(j .transcript_path); if [ -n "$t" ] && [ -f "$t" ]; then v=$(jq -n -R -r \'' + STATUS_TOKENS_JQ + '\' "$t" 2>/dev/null)\n'
     'add "$v" 90; fi'),
    ("limit", "5-hour limit", "5h:78%", "none", 'lim five_hour 5h'),
    ("week", "Weekly limit", "7d:41%", "none", 'lim seven_day 7d'),
    ("terminal", "Terminal", "iTerm", "round",
     'case $TERM_PROGRAM in Apple_Terminal) t=Terminal ;; iTerm.app) t=iTerm ;; WarpTerminal) t=Warp ;; vscode) t="VS Code" ;; '
     'ghostty) t=Ghostty ;; "") t=$TERM ;; *) t=$TERM_PROGRAM ;; esac; add "$t" 32'),
    ("time", "Time", "14:05", "none", 'add "$(date +%H:%M)" 2'),
]
STATUS_CODE = {x[0]: x[4] for x in STATUS_PARTS}
STATUS_DEFAULT_BRACKETS = {x[0]: x[3] for x in STATUS_PARTS}
STATUS_DEFAULT_PARTS = ["path", "branch", "profile", "model", "context"]
STATUS_SEPARATORS = {"space": " ", "dot": " · ", "bar": " | ", "arrow": " › "}
STATUS_BRACKETS = {"none": ("", ""), "round": ("(", ")"), "square": ("[", "]"), "curly": ("{", "}"), "angle": ("⟨", "⟩")}
# How the 5-hour and weekly limits read: the share used, or the share left with the time
# until the reset when half or less is left. Scripts without it in their header show "used".
STATUS_LIMITS = ("used", "left")
STATUS_SAMPLE_LEFT = {"limit": "5h:22%→1h20m", "week": "7d:59%"}
# The preview's data. No transcript_path: the preview adds one to a sample conversation of its
# own, so it never reads a file it did not write. resets_at is added relative to now.
STATUS_SAMPLE = {
    "model": {"id": "claude-opus-5-5", "display_name": "Opus"},
    "effort": {"level": "high"},
    "output_style": {"name": "Explanatory"},
    "pr": {"number": 42},
    "context_window": {"used_percentage": 42.4},
    "cost": {"total_cost_usd": 1.27, "total_lines_added": 120, "total_lines_removed": 34, "total_duration_ms": 754000},
    "rate_limits": {"five_hour": {"used_percentage": 78}, "seven_day": {"used_percentage": 41}},
}
# The preview's conversation: 12k tokens since the last prompt, 340k in all (a tool result
# is not a prompt).
STATUS_SAMPLE_TRANSCRIPT = [
    {"type": "user", "message": {"role": "user", "content": "add a login page"}},
    {"type": "assistant", "message": {"usage": {"input_tokens": 3000, "cache_creation_input_tokens": 20000,
                                                "cache_read_input_tokens": 290000, "output_tokens": 15000}}},
    {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}},
    {"type": "user", "message": {"role": "user", "content": "now the tests"}},
    {"type": "assistant", "message": {"usage": {"input_tokens": 1000, "cache_read_input_tokens": 9000, "output_tokens": 2000}}},
]


def status_parts(items):
    """[(id, brackets)] from "id" or "id:brackets" items: unknown ids and repeats dropped."""
    out, seen = [], set()
    for item in items:
        pid, _, br = str(item).partition(":")
        if pid not in STATUS_CODE or pid in seen:
            continue
        if br and br not in STATUS_BRACKETS:
            raise ApiError("Unknown brackets")
        seen.add(pid)
        out.append((pid, br or STATUS_DEFAULT_BRACKETS[pid]))
    return out


def status_style(separator, colors, limits="used"):
    if separator not in STATUS_SEPARATORS:
        raise ApiError("Unknown separator")
    if limits not in STATUS_LIMITS:
        raise ApiError("Unknown way to show the rate limits: expected used or left")
    return separator, bool(colors), limits


def status_script(parts, separator="space", colors=True, limits="used"):
    """The status line script: parts are (id, brackets) in the order to show them."""
    body = "\n".join(f"L='{STATUS_BRACKETS[br][0]}' R='{STATUS_BRACKETS[br][1]}'\n{STATUS_CODE[pid]}" for pid, br in parts)
    return f"""#!/bin/sh
{STATUS_MARK}
# parts: {" ".join(f"{pid}:{br}" for pid, br in parts)}
# style: separator={separator} colors={1 if colors else 0} limits={limits}
# Made in the Settings tab of cc-profiles, which rewrites it. To edit it by hand, delete the second line.
# Bytes stay bytes (LC_ALL=C): the shell cannot mangle ⟨ ⟩ or · whatever the terminal's locale.
export LC_ALL=C
C={1 if colors else 0}
LIM={limits}
SEP='{STATUS_SEPARATORS[separator]}'
[ "$C" = 1 ] && SEP=$(printf '\\033[2m%s\\033[0m' "$SEP")
input=$(cat)
dir=$(cd "${{CLAUDE_CONFIG_DIR:-$HOME/.claude}}" 2>/dev/null && pwd -P)
name=$(basename "$dir"); case $name in .claude-*) name=${{name#.claude-}} ;; *) name=default ;; esac
cfg="$dir/.claude.json"; [ -f "$cfg" ] || cfg="$HOME/.claude.json"  # the default profile keeps it in the home
if ! command -v jq >/dev/null 2>&1; then printf '%s (install jq for the rest)' "$name"; exit 0; fi
j() {{ printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null; }}
out=
add() {{
  [ -n "$1" ] || return 0
  s="$L$1$R"
  [ "$C" = 1 ] && [ -n "$2" ] && s=$(printf '\\033[%sm%s\\033[0m' "$2" "$s")
  out="${{out:+$out$SEP}}$s"
}}
# lim KEY LABEL: a rate limit, used or left (LIM), yellow from 70% used, red from 90%
lim() {{
  v=$(j ".rate_limits.$1.used_percentage | floor"); [ -n "$v" ] || return 0
  c=90; [ "$v" -ge 70 ] && c=33; [ "$v" -ge 90 ] && c=31
  if [ "$LIM" != left ]; then add "$2:$v%" $c; return 0; fi
  s="$2:$((100 - v))%"
  r=$(j ".rate_limits.$1.resets_at | floor")
  if [ "$v" -ge 50 ] && [ -n "$r" ]; then  # half or less left: the time until the reset
    d=$((r - $(date +%s)))
    if [ "$d" -ge 86400 ]; then s=$(printf '%s→%sd%sh' "$s" $((d / 86400)) $((d % 86400 / 3600)))
    elif [ "$d" -ge 3600 ]; then s=$(printf '%s→%sh%sm' "$s" $((d / 3600)) $((d % 3600 / 60)))
    elif [ "$d" -gt 0 ]; then s=$(printf '%s→%sm' "$s" $((d / 60))); fi
  fi
  add "$s" $c
}}
cwd=$(j .workspace.current_dir)
{body}
printf '%s' "$out"
"""


def status_script_path(prof):
    return os.path.join(prof["dir_abs"], "statusline.sh")


def status_script_info(path):
    """{parts: [(id, brackets)], separator, colors, limits} of a script cc-profiles wrote, or
    None for any other file. Scripts from before per-piece brackets list bare ids, and those
    from before limits=left show the limits used."""
    try:
        with open(path) as f:
            head = f.read(800).split("\n")
    except OSError:
        return None
    if len(head) < 3 or head[1] != STATUS_MARK or not head[2].startswith("# parts:"):
        return None
    old = ":" not in head[2][len("# parts:"):]
    try:
        parts = status_parts(head[2][len("# parts:"):].split())
    except ApiError:
        return None
    if old:
        parts = [(pid, "none") for pid, _ in parts]
    info = {"parts": parts, "separator": "dot", "colors": False, "limits": "used"}
    if len(head) > 3 and head[3].startswith("# style:"):
        style = dict(x.split("=", 1) for x in head[3][len("# style:"):].split() if "=" in x)
        info["separator"] = style.get("separator") if style.get("separator") in STATUS_SEPARATORS else "dot"
        info["colors"] = style.get("colors") == "1"
        info["limits"] = style.get("limits") if style.get("limits") in STATUS_LIMITS else "used"
    return info


def status_command(prof):
    return "sh " + shlex.quote(status_script_path(prof))


def get_statusline(pid):
    prof = profile(pid)
    value, src = effective(prof, "statusLine")
    value = value if isinstance(value, dict) else None
    path = status_script_path(prof)
    info = status_script_info(path)
    mode = "off"
    if value:
        mode = "builtin" if value.get("command") == status_command(prof) and info is not None else "custom"
    info = info or {"parts": status_parts(STATUS_DEFAULT_PARTS), "separator": "space", "colors": True, "limits": "used"}
    return {"value": value, "source": src, "mode": mode, "parts": [f"{pid}:{br}" for pid, br in info["parts"]],
            "separator": info["separator"], "colors": info["colors"], "limits": info["limits"], "script": pretty(path), "script_is_other": os.path.exists(path) and not status_script_info(path),
            "jq": bool(find_tool("jq")), "separators": [{"id": k, "text": v} for k, v in STATUS_SEPARATORS.items()],
            "brackets": [{"id": k, "left": v[0], "right": v[1]} for k, v in STATUS_BRACKETS.items()],
            "parts_available": [dict({"id": x[0], "label": x[1], "sample": x[2], "brackets": x[3]},
                                     **({"sample_left": STATUS_SAMPLE_LEFT[x[0]]} if x[0] in STATUS_SAMPLE_LEFT else {}))
                                for x in STATUS_PARTS]}


def statusline_sample(tmp):
    """STATUS_SAMPLE with its conversation written in tmp and the limits resetting from now."""
    transcript = os.path.join(tmp, "sample.jsonl")
    with open(transcript, "w") as f:
        f.write("".join(json.dumps(x) + "\n" for x in STATUS_SAMPLE_TRANSCRIPT))
    now = int(time.time())
    limits = {k: dict(v, resets_at=now + secs) for (k, v), secs in
              zip(STATUS_SAMPLE["rate_limits"].items(), (80 * 60 + 30, (3 * 24 + 11) * 3600 + 30))}
    # a sample project: a fresh git repository on main, so the branch shows as "main*"
    project = os.path.join(tmp, "code", "api")
    os.makedirs(project)
    git = find_tool("git")
    if git:
        subprocess.run([git, "init", "-q", "-b", "main", project], capture_output=True, timeout=5)
    return dict(STATUS_SAMPLE, workspace={"current_dir": project}, transcript_path=transcript, rate_limits=limits)


def statusline_preview(pid, parts, separator="space", colors="1", limits="used"):
    """What the script prints on sample data, and the script itself. It runs from a
    temporary folder, never the profile's, on a sample conversation of its own: read-only."""
    prof = profile(pid)
    parts = status_parts(x for x in parts.split(",") if x)
    separator, colors, limits = status_style(separator, colors == "1", limits)
    script = status_script(parts, separator, colors, limits)
    if not parts:
        return {"text": "", "script": script}
    tmp = tempfile.mkdtemp(prefix="cc-profiles-statusline-")
    try:
        path = os.path.join(tmp, "statusline.sh")
        with open(path, "w") as f:
            f.write(script)
        env = dict(tool_env(), CLAUDE_CONFIG_DIR=prof["dir_abs"])
        r = subprocess.run(["sh", path], input=json.dumps(statusline_sample(tmp)), capture_output=True, text=True,
                           timeout=5, env=env)
        # the sample project lives in a temporary folder: show it where a real one would be
        text = r.stdout.strip("\n")
        for prefix in {os.path.realpath(tmp), tmp}:
            text = text.replace(prefix, "~")
        return {"text": text, "script": script}
    except (OSError, subprocess.SubprocessError) as e:
        return {"text": "", "script": script, "error": str(e)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def statusline_value(prof, body):
    """(statusLine object, script info) a request asks for, checked. (None, None) turns it off;
    the info is None for a command of the user's own."""
    mode = body.get("mode")
    if mode == "off":
        return None, None
    if mode == "builtin":
        parts = status_parts(body.get("parts") or [])
        if not parts:
            raise ApiError("Pick at least one thing to show")
        separator, colors, limits = status_style(body.get("separator") or "space", body.get("colors", True),
                                                 body.get("limits") or "used")
        info = {"parts": parts, "separator": separator, "colors": colors, "limits": limits}
        command = status_command(prof)
    elif mode == "custom":
        command, info = str(body.get("command") or "").strip(), None
        if not command:
            raise ApiError("Write the command that prints the status line")
    else:
        raise ApiError("Unknown status line mode")
    value = {"type": "command", "command": command}
    for key, low in (("padding", 0), ("refreshInterval", 1)):
        n = body.get(key)
        if n in (None, ""):
            continue
        if not isinstance(n, int) or isinstance(n, bool) or n < low:
            raise ApiError(f"Invalid {'padding' if key == 'padding' else 'refresh interval'}: expected a whole number from {low}")
        value[key] = n
    if body.get("hideVimModeIndicator") is True:
        value["hideVimModeIndicator"] = True
    return value, info


def write_statusline(prof, value, info, bk):
    """Write a profile's statusLine (and its script for the built-in one), inside a backup."""
    path = status_script_path(prof)
    if info is not None:
        if os.path.exists(path) and status_script_info(path) is None:
            raise ApiError(f"{pretty(path)} exists and was not made by cc-profiles: rename it, or use it as your own command")
        bk.copy(path, "statusline.sh")
        write_text(path, status_script(info["parts"], info["separator"], info["colors"], info["limits"]))
    elif status_script_info(path) is not None:
        bk.stash(path, "statusline.sh")  # the old built-in script is no longer used
    targets = setting_targets(prof, "statusLine", value) if value is None else [effective(prof, "statusLine")[1] or "settings"]
    for which in targets:
        write_field(prof, which, "statusLine", value, bk)


def op_statusline(pid, body):
    prof = profile(pid)
    value, info = statusline_value(prof, body)
    bk = Backup("statusline", f"Status line of {prof['label']}")
    write_statusline(prof, value, info, bk)
    bk.note(f"statusLine = {json.dumps(value)}" + (f", script: {' '.join(p for p, _ in info['parts'])}" if info else ""))
    msg = "Status line turned off." if value is None else "Status line saved: it shows from the next Claude Code session."
    return {"message": msg, "backup": bk.close()}


def status_signature(sl):
    """What makes two profiles' status lines the same, the script's own path aside."""
    if sl["mode"] == "off":
        return ("off",)
    rest = {k: v for k, v in sl["value"].items() if k != "command" or sl["mode"] == "custom"}
    script = (sl["parts"], sl["separator"], sl["colors"], sl["limits"]) if sl["mode"] == "builtin" else None
    return (sl["mode"], json.dumps(rest, sort_keys=True), script)


def statusline_all_plan(pid):
    """Which profiles get this profile's status line, and which are skipped, with the reason."""
    prof = profile(pid)
    cur = get_statusline(pid)
    apply, skip, written = [], [], {}
    for o in profiles():
        if o["id"] == pid:
            continue
        mine = get_statusline(o["id"])
        where = effective(o, "statusLine")[1] or "settings"
        target = field_path(o, where)
        if status_signature(mine) == status_signature(cur):
            reason = "already has it"
        elif file_error(o, where):
            reason = f"{os.path.basename(target)} has an error: fix it in the advanced editor"
        elif cur["mode"] == "builtin" and mine["script_is_other"]:
            reason = f"{mine['script']} was not made by cc-profiles"
        elif os.path.realpath(target) in written:
            reason = f"shares {os.path.basename(target)} with {written[os.path.realpath(target)]}"
        else:
            written[os.path.realpath(target)] = o["label"]
            apply.append({"id": o["id"], "label": o["label"], "detail": f"{mine['mode']} → {cur['mode']}"})
            continue
        skip.append({"id": o["id"], "label": o["label"], "reason": reason})
    return {"from": prof["label"], "mode": cur["mode"], "apply": apply, "skip": skip}


def op_statusline_all(pid):
    plan = statusline_all_plan(pid)
    if not plan["apply"]:
        raise no_targets(plan)
    cur = get_statusline(pid)
    info = ({"parts": status_parts(cur["parts"]), "separator": cur["separator"], "colors": cur["colors"], "limits": cur["limits"]}
            if cur["mode"] == "builtin" else None)
    bk = Backup("statusline-all", f"Status line of {plan['from']} in every profile")
    for t in plan["apply"]:
        o = profile(t["id"])
        if cur["mode"] == "off":
            value = None
        elif cur["mode"] == "builtin":
            value = dict(cur["value"], command=status_command(o))
        else:
            value = dict(cur["value"])
        write_statusline(o, value, info, bk)
        bk.note(f"{o['label']}: {t['detail']}")
    for x in plan["skip"]:
        bk.note(f"skipped {x['label']}: {x['reason']}")
    return {"message": plan_message("Status line set", plan), "backup": bk.close()}
