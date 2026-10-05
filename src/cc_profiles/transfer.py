# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Export and import."""

import json
import os
import shutil
import stat
import tempfile
import time
import zipfile

from . import __version__
from .core import (
    ApiError,
    Backup,
    CONFIG_FILE,
    HOME,
    LAUNCHER_DIR,
    pretty,
    profile,
    profiles,
    read_json,
    san,
    write_json,
)
from .sharing import SHARE_ITEMS, primary, share_state
from .command import command_state, write_command
from .launchers import launcher_dir_in_path, write_launcher
from .newprofile import PROJECT_DATA, RUNTIME, add_profile_to_config, check_new_profile

# ---------------------------------------------------------------------------
# Export and import
# ---------------------------------------------------------------------------
# A profile travels as a .zip: profile/… (its folder), claude.json (its .claude.json),
# home-memory/… (the general memory, which lives under the home folder's project)
# and cc-profiles-export.json (the manifest). Login credentials never travel: a
# copied token can be invalidated when the original refreshes it.
EXPORT_FORMAT = 1
EXPORT_MANIFEST = "cc-profiles-export.json"
DIR_PLACEHOLDER = "__CC_PROFILES_PROFILE_DIR__"
IMPORT_MAX = 500 * 1024 * 1024          # size of the uploaded zip
IMPORT_MAX_UNPACKED = 5 * 1024 ** 3     # size once unpacked: refuse zip bombs
NEVER_EXPORT = {".credentials.json"}    # at any depth
# A template (see templates.py) is an export with only these top-level items, and with
# only the MCP servers from .claude.json: no conversations, memories or credentials.
TEMPLATE_ITEMS = {"settings.json", "settings.local.json", "CLAUDE.md", "skills", "agents", "commands",
                  "output-styles"}


def holds_profile_paths(rel):
    """Files whose text holds absolute paths to the profile folder (see CLAUDE.md)."""
    return rel == "settings.local.json" or (rel.startswith("plugins/") and rel.count("/") == 1
                                            and rel.endswith(".json"))


def share_note(prof, item):
    """Who else uses this item of the profile through sharing."""
    src = primary()
    if prof["id"] != src["id"]:
        return f"shared with {src['label']}" if share_state(prof, item, "dir")["shared"] else ""
    users = [p["label"] for p in profiles()[1:] if share_state(p, item, "dir")["shared"]]
    return f"shared with {', '.join(users)}" if users else ""


def export_profile(pid, projects, template=False):
    """Write the profile into a temporary zip. Returns (path, download name).
    template: only TEMPLATE_ITEMS and the MCP servers (projects is ignored)."""
    prof = profile(pid)
    d = prof["dir_abs"]
    if not os.path.isdir(d):
        raise ApiError(f"{pretty(d)} does not exist")
    projects = projects and not template
    skip = RUNTIME | NEVER_EXPORT | (set() if projects else PROJECT_DATA)
    shared = [i for i, _, _ in SHARE_ITEMS if os.path.islink(os.path.join(d, i))]
    dirs = sorted({d, os.path.realpath(d)}, key=len, reverse=True)
    fd, tmp = tempfile.mkstemp(prefix="cc-profiles-export-", suffix=".zip")
    os.close(fd)
    seen, count = set(), [0]
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            def add(src, arc, rel=None):
                if rel is not None and holds_profile_paths(rel):
                    text = open(src, errors="replace").read()
                    for x in dirs:
                        text = text.replace(x, DIR_PLACEHOLDER)
                    z.writestr(arc, text)
                else:
                    z.write(src, arc)
                count[0] += 1

            def walk(src, rel):
                # Links are followed (shared items, skills linked from elsewhere): the
                # export holds real files. Each real folder is written once, so a loop stops.
                real = os.path.realpath(src)
                if real in seen:
                    return
                seen.add(real)
                for name in sorted(os.listdir(src)):
                    if rel == "" and (name in skip or (template and name not in TEMPLATE_ITEMS)):
                        continue
                    if name in NEVER_EXPORT or name == ".trash":
                        continue
                    p = os.path.join(src, name)
                    if os.path.islink(p) and not os.path.realpath(p).startswith(os.path.realpath(HOME) + os.sep):
                        continue  # a link out of the home folder: never pull system files into an export
                    if os.path.isdir(p):
                        walk(p, rel + name + "/")
                    elif os.path.isfile(p):
                        add(p, "profile/" + rel + name, rel + name)

            walk(d, "")
            cfg = read_json(prof["config_abs"], {}) or {}
            for k in ("oauthAccount", "userID"):  # account data belongs to the login
                cfg.pop(k, None)
            if not projects:
                cfg.pop("projects", None)  # per-project settings go with the projects
            if template:
                cfg = {"mcpServers": cfg["mcpServers"]} if isinstance(cfg.get("mcpServers"), dict) else {}
            z.writestr("claude.json", json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
            home_memory = os.path.join(d, "projects", san(HOME), "memory")
            has_home_memory = not projects and not template and os.path.isdir(home_memory)
            if has_home_memory:
                for f in sorted(os.listdir(home_memory)):
                    if os.path.isfile(os.path.join(home_memory, f)):
                        add(os.path.join(home_memory, f), "home-memory/" + f)
            z.writestr(EXPORT_MANIFEST, json.dumps({
                "app": "cc-profiles", "format": EXPORT_FORMAT, "version": __version__,
                "label": prof["label"], "id": prof["id"], "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "projects": bool(projects), "home_memory": has_home_memory, "template": bool(template),
                "shared": shared, "files": count[0]}, indent=2) + "\n")
    except Exception:
        os.unlink(tmp)
        raise
    return tmp, f"cc-profiles-{prof['id']}-{time.strftime('%Y-%m-%d')}.zip"


def check_zip_entry(info):
    name = info.filename
    parts = name.split("/")
    if not name or name.startswith("/") or "\\" in name or ".." in parts or ":" in parts[0]:
        raise ApiError(f"Unsafe path in the archive: {name}. Nothing was imported.")
    kind = (info.external_attr >> 16) & 0o170000
    if kind and kind not in (stat.S_IFREG, stat.S_IFDIR):
        raise ApiError(f"Not a plain file in the archive (a link or a device): {name}. Nothing was imported.")
    if name not in (EXPORT_MANIFEST, "claude.json") and parts[0] not in ("profile", "home-memory"):
        raise ApiError(f"Unexpected entry in the archive: {name}. Nothing was imported.")


def op_import_profile(zip_path, label, pid, template=None):
    """Create a profile from an export. template: the name of the template it comes from."""
    try:
        z = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError):
        raise ApiError("This is not a zip file. Export the profile from cc-profiles and try again.")
    with z:
        infos = z.infolist()
        for info in infos:  # check everything before writing anything
            check_zip_entry(info)
        try:
            man = json.loads(z.read(EXPORT_MANIFEST))
        except (KeyError, ValueError):
            raise ApiError("This zip was not exported by cc-profiles: it has no cc-profiles-export.json.")
        if man.get("app") != "cc-profiles" or man.get("format") != EXPORT_FORMAT:
            raise ApiError("This export was made by a newer cc-profiles: update cc-profiles and try again.")
        if sum(i.file_size for i in infos) > IMPORT_MAX_UNPACKED:
            raise ApiError("The archive is too big once unpacked (over 5 GB).")
        if template:  # the template's own label and id belong to the profile it was saved from
            label, pid, new, command = check_new_profile(label, pid)
            bk = Backup("new-profile", f"New profile {label} from template {template} ({pretty(new)})")
        else:
            label, pid, new, command = check_new_profile(label or man.get("label"), pid or man.get("id"))
            bk = Backup("import-profile", f"Import profile {label} ({pretty(new)})")
        bk.copy(CONFIG_FILE, "config.json")
        bk.created(new)  # journaled first: a failure while unpacking leaves a folder that Restore removes
        os.makedirs(new)
        try:
            for info in infos:
                if info.is_dir():
                    continue
                top, _, rest = info.filename.partition("/")
                if top == "profile":
                    dst = os.path.join(new, rest)
                elif top == "home-memory":
                    dst = os.path.join(new, "projects", san(HOME), "memory", rest)
                else:
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                data = z.read(info)
                if top == "profile" and holds_profile_paths(rest):
                    data = data.decode(errors="replace").replace(DIR_PLACEHOLDER, new).encode()
                with open(dst, "wb") as f:
                    f.write(data)
            cfg = json.loads(z.read("claude.json")) if "claude.json" in z.namelist() else {}
            for k in ("oauthAccount", "userID"):
                cfg.pop(k, None)
            write_json(os.path.join(new, ".claude.json"), cfg)
            if command_state(new) in ("missing", "outdated"):
                write_command(new, bk, pid)
            write_launcher(command, f"~/.claude-{pid}", label, bk)
        except Exception:
            shutil.rmtree(new, ignore_errors=True)  # nothing else was changed yet
            raise
    add_profile_to_config(label, pid, command)
    if template:
        bk.note(f"from the template {template}, saved from {man.get('label')} ({man.get('created', '?')})")
        msg = f"Profile {label} created from the template {template}. Run {command} and log in with /login."
    else:
        bk.note(f"from the export of {man.get('label')} ({man.get('created', '?')}), "
                f"conversations: {'yes' if man.get('projects') else 'no'}")
        msg = f"Profile {label} imported. It is not logged in: run {command} and log in with /login."
    if not launcher_dir_in_path():
        msg += f" Note: {pretty(LAUNCHER_DIR)} is not in your PATH yet."
    return {"message": msg, "backup": bk.close()}
