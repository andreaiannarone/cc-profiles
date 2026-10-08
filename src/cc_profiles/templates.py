# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Profile templates."""

import json
import os
import re
import shutil
import zipfile

from .core import ApiError, Backup, DATA_DIR, pretty, profile
from .sharing import SHARE_ITEMS
from .transfer import EXPORT_MANIFEST, export_profile, op_import_profile

# ---------------------------------------------------------------------------
# Profile templates
# ---------------------------------------------------------------------------
# A template is an export without projects (see TEMPLATE_ITEMS in transfer.py): settings,
# CLAUDE.md, permissions, skills, agents, commands, output styles and MCP servers. It is
# stored as ~/.cc-profiles/templates/<name>.zip and creates new profiles through the
# import code. Never conversations, memories or login credentials.
TEMPLATE_DIR = os.path.join(DATA_DIR, "templates")
TEMPLATE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,47}")


def template_path(name, must_exist=True):
    """Path of a template, protected against path traversal."""
    if not isinstance(name, str) or not TEMPLATE_NAME.fullmatch(name) or ".." in name:
        raise ApiError("Invalid template name: letters, digits, spaces, dots, dashes and underscores, up to 48")
    p = os.path.join(TEMPLATE_DIR, name + ".zip")
    if must_exist and not os.path.isfile(p):
        raise ApiError(f"Template not found: {name}", 404)
    return p


def list_templates():
    out = []
    if not os.path.isdir(TEMPLATE_DIR):
        return {"templates": out, "dir": pretty(TEMPLATE_DIR)}
    for f in sorted(os.listdir(TEMPLATE_DIR), key=str.lower):
        if not f.endswith(".zip") or f.startswith("."):
            continue
        p = os.path.join(TEMPLATE_DIR, f)
        try:
            with zipfile.ZipFile(p) as z:
                man = json.loads(z.read(EXPORT_MANIFEST))
                names = z.namelist()
                mcp = len((json.loads(z.read("claude.json")) if "claude.json" in names else {}).get("mcpServers") or {})
        except (zipfile.BadZipFile, KeyError, ValueError, OSError):
            continue  # not a template: listed nowhere, deleted by nobody
        items = sorted({n.split("/")[1] for n in names if n.startswith("profile/") and n.count("/") >= 1})
        skills = len({n.split("/")[2] for n in names if n.startswith("profile/skills/") and n.count("/") >= 3})
        # what each shareable item holds, so New profile can say what sharing it skips
        counts = {}
        for item, kind, _ in SHARE_ITEMS:
            if kind == "dir":
                n = len({x.split("/")[2] for x in names if x.startswith(f"profile/{item}/") and x.count("/") >= 2})
            else:
                n = int(f"profile/{item}" in names)
            if n:
                counts[item] = n
        out.append({"name": f[:-4], "from": man.get("label", ""), "created": man.get("created", ""),
                    "items": items, "skills": skills, "mcp": mcp, "counts": counts, "size": os.path.getsize(p)})
    return {"templates": out, "dir": pretty(TEMPLATE_DIR)}


def op_template_save(pid, name):
    prof = profile(pid)
    name = (name or "").strip()
    path = template_path(name, must_exist=False)
    if os.path.lexists(path):
        raise ApiError(f"There is already a template called {name}: delete it first or pick another name")
    tmp, _ = export_profile(pid, False, template=True)
    try:
        bk = Backup("template-save", f"Save template {name} from {prof['label']}")
        bk.mkdir(TEMPLATE_DIR)
        bk.copy(path)  # absent: restoring removes the template
        part = path + f".tmp-{os.getpid()}"
        shutil.copyfile(tmp, part)
        os.replace(part, path)
    finally:
        os.unlink(tmp)
    bk.note(f"from {prof['label']} ({pretty(prof['dir_abs'])})")
    return {"message": f"Template {name} saved from {prof['label']}: pick it in New profile.", "backup": bk.close()}


def op_template_delete(name):
    path = template_path(name)
    bk = Backup("template-delete", f"Delete template {name}")
    bk.stash(path, f"template-{name}.zip")
    return {"message": f"Template {name} deleted.", "backup": bk.close()}


def op_create_from_template(name, label, pid, share=None, github=False):
    """share: items linked to the source profile instead of being filled from the template."""
    return op_import_profile(template_path(name), label, pid, template=name, share=share, github=github)
