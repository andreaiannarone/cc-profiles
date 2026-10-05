# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Claude Code settings."""

import glob
import json
import os

from .core import (
    ApiError,
    Backup,
    load_settings,
    parse_memory,
    pretty,
    profile,
    profiles,
    read_json,
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
SETTING_FIELDS = [
    {"key": "model", "type": "text", "label": "Model",
     "help": "An alias (opus, sonnet, haiku) or a full model name", "suggest": ["opus", "sonnet", "haiku"]},
    {"key": "effortLevel", "type": "select", "label": "Effort level",
     "help": "How much the model reasons before answering",
     "options": [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("xhigh", "Extra high")]},
    {"key": "outputStyle", "type": "select", "label": "Output style",
     "default_desc": "Claude Code's standard behavior",
     "help": "Built-in styles plus the profile's custom ones (output-styles/)", "options": "styles"},
    {"key": "language", "type": "text", "label": "Response language", "help": "Free text, e.g. English, Italiano",
     "suggest": []},
    {"key": "theme", "type": "select", "label": "Theme", "help": "Colors of the terminal UI; custom themes (custom:…) are kept",
     "options": [("auto", "Auto"), ("dark", "Dark"), ("light", "Light"), ("dark-daltonized", "Dark, colorblind-friendly"),
                 ("light-daltonized", "Light, colorblind-friendly"), ("dark-ansi", "Dark, ANSI colors only"),
                 ("light-ansi", "Light, ANSI colors only")]},
    {"key": "editorMode", "type": "select", "label": "Editor mode", "help": "Key bindings for the prompt input",
     "options": [("normal", "Normal"), ("vim", "Vim")]},
    {"key": "tui", "type": "select", "label": "Renderer", "help": "How the UI is drawn in the terminal",
     "options": [("default", "Classic"), ("fullscreen", "Fullscreen, flicker-free")]},
    {"key": "includeCoAuthoredBy", "type": "bool", "label": "Co-authored-by in commits", "deprecated": True,
     "help": "Deprecated by Claude Code: replaced by “attribution” (advanced editor)"},
    {"key": "cleanupPeriodDays", "type": "number", "label": "Days to keep conversations",
     "help": "Older conversations are deleted (default 30, minimum 1)"},
    {"key": "prefersReducedMotion", "type": "bool", "label": "Reduce motion", "help": "Fewer animations in the UI"},
]
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


def settings_files(prof):
    d = prof["dir_abs"]
    return {"settings": os.path.join(d, "settings.json"),
            "local": os.path.join(d, "settings.local.json"),
            "claude_md": os.path.join(d, "CLAUDE.md")}


def effective(prof, key):
    """Value in use and the file it comes from: settings.local.json wins over settings.json."""
    f = settings_files(prof)
    local, _ = load_settings(f["local"])
    if key in local:
        return local[key], "local"
    sett, _ = load_settings(f["settings"])
    if key in sett:
        return sett[key], "settings"
    return None, None


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
    for fd in SETTING_FIELDS:
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
        value = str(value).strip() or None
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
    which = src or "settings"
    f = settings_files(prof)
    data, _ = load_settings(f[which])
    bk = Backup("setting", f"{fd['label']} of {prof['label']}")
    if value is None:
        data.pop(key, None)
        msg = f"{fd['label']}: back to the default."
    else:
        data[key] = value
        msg = f"Saved in {os.path.basename(f[which])}: {fd['label'].lower()} = {value}{shared_note(f[which])}."
    save_settings_file(prof, which, data, bk)
    bk.note(f"{key} = {json.dumps(value, ensure_ascii=False)} in {os.path.basename(f[which])}")
    return {"message": msg, "backup": bk.close()}


# Apply to all profiles: one operation, one backup for every profile it changes. The plan
# says which profiles change and which are skipped, with the reason; the UI shows it first.
def show_value(fd, prof, value):
    if value is None:
        return "the default"
    opt = next((o for o in field_options(fd, prof, value) or [] if o["value"] == value), None)
    return opt["label"] if opt else json.dumps(value, ensure_ascii=False)


def setting_targets(prof, key, value):
    """The files of a profile to write so that its value of key becomes value: where the
    value lives, or every file that has it when the value goes back to the default."""
    f = settings_files(prof)
    if value is None:
        return [w for w in ("local", "settings") if key in load_settings(f[w])[0]]
    return [effective(prof, key)[1] or "settings"]


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
        f = settings_files(o)
        paths = [f[w] for w in setting_targets(o, key, value)]
        errs = [os.path.basename(p) for p in paths if load_settings(p)[1]]
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
        f = settings_files(o)
        for which in setting_targets(o, key, value):
            data, _ = load_settings(f[which])
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
            save_settings_file(o, which, data, bk)
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
