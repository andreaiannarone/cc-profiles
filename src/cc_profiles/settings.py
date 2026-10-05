# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Claude Code settings."""

import glob
import json
import os
import shlex
import subprocess
import tempfile

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
    {"group": "Model and replies", "key": "model", "type": "text", "label": "Model",
     "help": "An alias (opus, sonnet, haiku) or a full model name", "suggest": ["opus", "sonnet", "haiku"]},
    dict(_ON, group="Model and replies", key="alwaysThinkingEnabled", label="Thinking mode", drop_default=True,
         help="Claude reasons before answering"),
    {"group": "Model and replies", "key": "outputStyle", "type": "select", "label": "Output style",
     "default_desc": "Claude Code's standard behavior",
     "help": "Built-in styles plus the profile's custom ones (output-styles/)", "options": "styles"},
    {"group": "Model and replies", "key": "language", "type": "text", "label": "Language",
     "help": "Language of the replies, e.g. English, Italiano", "suggest": []},
    dict(_ON, group="Model and replies", key="promptSuggestionEnabled", label="Prompt suggestions", drop_default=True,
         help="Suggest what to ask next"),
    dict(_ON, group="Model and replies", key="awaySummaryEnabled", label="Session recap", drop_default=True,
         help="A summary of what happened while you were away"),
    dict(_ON, **_GLOBAL, group="Model and replies", key="autoCompactEnabled", label="Auto-compact",
         help="Compact the conversation when the context fills up"),
    dict(_ON, group="Model and replies", key="precomputeCompactionEnabled", label="Precompute compaction",
         help="Prepare the compaction in advance, so it takes less time"),
    dict(_ON, **_GLOBAL, group="Model and replies", key="fileCheckpointingEnabled", label="Rewind code (checkpoints)",
         help="Keep snapshots of the files Claude edits, to undo them with /rewind"),
    {"group": "Model and replies", "key": "permissions.defaultMode", "type": "select", "default": "default", "label": "Default permission mode",
     "help": "How a session starts: asking first, planning, or editing on its own",
     "options": [("default", "Ask before acting"), ("plan", "Plan mode"), ("acceptEdits", "Accept edits"),
                 ("auto", "Auto"), ("dontAsk", "Don't ask")]},
    dict(_ON, group="Model and replies", key="useAutoModeDuringPlan", label="Use auto mode during plan",
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
    # commits and pull requests: an empty text is a value of its own, Claude Code then adds nothing
    {"group": "Commits and pull requests", "key": "attribution.commit", "type": "text", "blank": True,
     "label": "Commit attribution",
     "help": "Text Claude adds to its commits, trailers included (e.g. Co-Authored-By: …). Empty: none"},
    {"group": "Commits and pull requests", "key": "attribution.pr", "type": "text", "blank": True,
     "label": "Pull request attribution", "help": "Text Claude adds to the pull requests it opens. Empty: none"},
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
    if fd["type"] == "bool" and not isinstance(value, bool):
        raise ApiError("Invalid value: expected true or false")
    if fd["type"] == "number":
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ApiError("Invalid value: expected a whole number greater than zero")
    if fd["type"] == "text":
        value = str(value).strip() or ("" if fd.get("blank") else None)
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


# Apply to all profiles: one operation, one backup for every profile it changes. The plan
# says which profiles change and which are skipped, with the reason; the UI shows it first.
def show_value(fd, prof, value):
    if value is None:
        return "the default"
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
STATUS_PARTS = [
    ("profile", "Profile", "Default"),
    ("model", "Model", "Opus"),
    ("folder", "Folder", "api"),
    ("branch", "Git branch", "main"),
    ("context", "Context used", "ctx 42%"),
    ("cost", "Session cost", "$1.27"),
    ("limit", "5-hour limit used", "5h 18%"),
]
STATUS_SNIPPETS = {
    "profile": 'label=$(jq -r --arg d "$dir" --arg h "$HOME" \'.profiles[]? | select((.dir | sub("^~"; $h)) == $d) | .label\' '
               '"$HOME/.cc-profiles/config.json" 2>/dev/null | head -n 1)\nadd "${label:-$name}"',
    "model": 'add "$(j .model.display_name)"',
    "folder": '[ -n "$cwd" ] && add "$(basename "$cwd")"',
    "branch": '[ -n "$cwd" ] && add "$(git -C "$cwd" branch --show-current 2>/dev/null)"',
    "context": 'v=$(j .context_window.used_percentage); [ -n "$v" ] && add "ctx $(printf \'%.0f\' "$v")%"',
    "cost": 'v=$(j .cost.total_cost_usd); [ -n "$v" ] && add "$(printf \'$%.2f\' "$v")"',
    "limit": 'v=$(j .rate_limits.five_hour.used_percentage); [ -n "$v" ] && add "5h $(printf \'%.0f\' "$v")%"',
}
STATUS_SAMPLE = {
    "model": {"id": "claude-opus-5-5", "display_name": "Opus"},
    "context_window": {"used_percentage": 42},
    "cost": {"total_cost_usd": 1.27},
    "rate_limits": {"five_hour": {"used_percentage": 18}},
}


def status_script(parts):
    """The status line script for these parts, in STATUS_PARTS order."""
    parts = [p for p, _, _ in STATUS_PARTS if p in parts]
    body = "\n".join(STATUS_SNIPPETS[p] for p in parts)
    return f"""#!/bin/sh
{STATUS_MARK}
# parts: {" ".join(parts)}
# Made in the Settings tab of cc-profiles, which rewrites it. To edit it by hand, delete the first two lines.
export LC_NUMERIC=C
input=$(cat)
dir=$(cd "${{CLAUDE_CONFIG_DIR:-$HOME/.claude}}" 2>/dev/null && pwd -P)
name=$(basename "$dir"); case $name in .claude-*) name=${{name#.claude-}} ;; *) name=default ;; esac
if ! command -v jq >/dev/null 2>&1; then printf '%s (install jq for the rest)' "$name"; exit 0; fi
j() {{ printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null; }}
out=
add() {{ [ -n "$1" ] && out="${{out:+$out · }}$1"; return 0; }}
cwd=$(j .workspace.current_dir)
{body}
printf '%s' "$out"
"""


def status_script_path(prof):
    return os.path.join(prof["dir_abs"], "statusline.sh")


def status_script_parts(path):
    """The parts of a script cc-profiles wrote, or None for any other file."""
    try:
        with open(path) as f:
            head = f.read(400).split("\n")
    except OSError:
        return None
    if len(head) < 3 or head[1] != STATUS_MARK or not head[2].startswith("# parts:"):
        return None
    return head[2][len("# parts:"):].split()


def status_command(prof):
    return "sh " + shlex.quote(status_script_path(prof))


def get_statusline(pid):
    prof = profile(pid)
    value, src = effective(prof, "statusLine")
    value = value if isinstance(value, dict) else None
    path = status_script_path(prof)
    parts = status_script_parts(path)
    mode = "off"
    if value:
        mode = "builtin" if value.get("command") == status_command(prof) and parts is not None else "custom"
    return {"value": value, "source": src, "mode": mode, "parts": parts or ["profile", "model", "folder", "branch", "context"],
            "script": pretty(path), "script_is_other": os.path.exists(path) and parts is None,
            "jq": bool(find_tool("jq")), "parts_available": [{"id": i, "label": l, "sample": s} for i, l, s in STATUS_PARTS]}


def statusline_preview(pid, parts):
    """What the script prints on sample data, run in a temporary file: read-only."""
    prof = profile(pid)
    parts = [p for p in parts.split(",") if p in STATUS_SNIPPETS]
    if not parts:
        return {"text": ""}
    sample = dict(STATUS_SAMPLE, workspace={"current_dir": os.getcwd()})
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write(status_script(parts))
    env = dict(tool_env(), CLAUDE_CONFIG_DIR=prof["dir_abs"])
    try:
        r = subprocess.run(["sh", f.name], input=json.dumps(sample), capture_output=True, text=True, timeout=5, env=env)
        return {"text": r.stdout.strip()}
    except (OSError, subprocess.SubprocessError) as e:
        return {"text": "", "error": str(e)}
    finally:
        os.unlink(f.name)


def statusline_value(prof, body):
    """The statusLine object a request asks for, checked; None turns it off."""
    mode = body.get("mode")
    if mode == "off":
        return None, None
    if mode == "builtin":
        parts = [p for p in body.get("parts") or [] if p in STATUS_SNIPPETS]
        if not parts:
            raise ApiError("Pick at least one thing to show")
        command = status_command(prof)
    elif mode == "custom":
        command, parts = str(body.get("command") or "").strip(), None
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
    return value, parts


def write_statusline(prof, value, parts, bk):
    """Write a profile's statusLine (and its script for the built-in one), inside a backup."""
    path = status_script_path(prof)
    if parts is not None:
        if os.path.exists(path) and status_script_parts(path) is None:
            raise ApiError(f"{pretty(path)} exists and was not made by cc-profiles: rename it, or use it as your own command")
        bk.copy(path, "statusline.sh")
        write_text(path, status_script(parts))
    elif status_script_parts(path) is not None:
        bk.stash(path, "statusline.sh")  # the old built-in script is no longer used
    targets = setting_targets(prof, "statusLine", value) if value is None else [effective(prof, "statusLine")[1] or "settings"]
    for which in targets:
        write_field(prof, which, "statusLine", value, bk)


def op_statusline(pid, body):
    prof = profile(pid)
    value, parts = statusline_value(prof, body)
    bk = Backup("statusline", f"Status line of {prof['label']}")
    write_statusline(prof, value, parts, bk)
    bk.note(f"statusLine = {json.dumps(value)}")
    msg = "Status line turned off." if value is None else "Status line saved: it shows from the next Claude Code session."
    return {"message": msg, "backup": bk.close()}


def statusline_all_plan(pid):
    """Which profiles get this profile's status line, and which are skipped, with the reason."""
    prof = profile(pid)
    cur = get_statusline(pid)
    apply, skip, written = [], [], {}
    for o in profiles():
        if o["id"] == pid:
            continue
        mine = get_statusline(o["id"])
        target = field_path(o, effective(o, "statusLine")[1] or "settings")
        same = mine["mode"] == cur["mode"] and (
            mine["mode"] == "off" or (cur["mode"] == "builtin" and mine["parts"] == cur["parts"]
                                      and {k: v for k, v in mine["value"].items() if k != "command"}
                                      == {k: v for k, v in cur["value"].items() if k != "command"})
            or mine["value"] == cur["value"])
        if same:
            reason = "already has it"
        elif file_error(o, effective(o, "statusLine")[1] or "settings"):
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
    bk = Backup("statusline-all", f"Status line of {plan['from']} in every profile")
    for t in plan["apply"]:
        o = profile(t["id"])
        if cur["mode"] == "off":
            value, parts = None, None
        elif cur["mode"] == "builtin":
            value, parts = dict(cur["value"], command=status_command(o)), cur["parts"]
        else:
            value, parts = dict(cur["value"]), None
        write_statusline(o, value, parts, bk)
        bk.note(f"{o['label']}: {t['detail']}")
    for s in plan["skip"]:
        bk.note(f"skipped {s['label']}: {s['reason']}")
    return {"message": plan_message("Status line set", plan), "backup": bk.close()}
