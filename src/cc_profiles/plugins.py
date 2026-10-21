# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Plugins."""

import json
import os
import shutil

from .core import ApiError, Backup, load_settings, pretty, profile, read_json, session_hint, write_json
from .mods import installed_plugins, mod_info
from .settings import save_settings_file, settings_files, shared_note
from .transfer import share_note

# ---------------------------------------------------------------------------
# Plugins
# ---------------------------------------------------------------------------
# Installing and removing plugins is Claude Code's job (/plugin): here they are
# listed, enabled or disabled through enabledPlugins in the settings files, and copied
# to another profile as /plugin would have installed them there. Mods are plugins too (mods.py).
def plugin_switch(prof, name):
    """(value, file) of one plugin in enabledPlugins: settings.local.json wins."""
    f = settings_files(prof)
    for which in ("local", "settings"):
        data, _ = load_settings(f[which])
        ep = data.get("enabledPlugins")
        if isinstance(ep, dict) and name in ep:
            return ep[name], which
    return None, None


def list_plugins(pid):
    prof = profile(pid)
    pdir = os.path.join(prof["dir_abs"], "plugins")
    installed = installed_plugins(pdir)
    names = set(installed)
    for path in settings_files(prof).values():
        if path.endswith(".json"):
            ep = load_settings(path)[0].get("enabledPlugins")
            if isinstance(ep, dict):
                names |= set(ep)
    items = []
    for name in sorted(names):
        installs = installed.get(name) or []
        first = installs[0] if installs else {}
        plugin, _, market = name.partition("@")
        value, source = plugin_switch(prof, name)
        items.append({"name": name, "plugin": plugin, "marketplace": market,
                      "version": first.get("version", ""), "installed": (first.get("installedAt") or "")[:10],
                      "path": pretty(first.get("installPath", "")), "is_installed": bool(installs),
                      "scopes": sorted({i.get("scope", "user") for i in installs}),
                      "projects": [pretty(i["projectPath"]) for i in installs if i.get("projectPath")],
                      "enabled": value, "source": source, "mod": mod_info(first.get("installPath", ""))})
    markets = read_json(os.path.join(pdir, "known_marketplaces.json"), {}) or {}
    marketplaces = []
    for name, m in sorted(markets.items()):
        src = (m or {}).get("source") or {}
        marketplaces.append({"name": name, "source": src.get("repo") or src.get("url") or src.get("path") or "",
                             "updated": ((m or {}).get("lastUpdated") or "")[:10]})
    return {"plugins": items, "marketplaces": marketplaces, "dir": pretty(pdir),
            "shared": share_note(prof, "plugins")}


def op_plugin_enable(pid, name, enabled):
    if not isinstance(enabled, bool):
        raise ApiError("Invalid value: expected true or false")
    prof = profile(pid)
    if name not in {p["name"] for p in list_plugins(pid)["plugins"]}:
        raise ApiError(f"Plugin not found in {prof['label']}: {name}", 404)
    bk = Backup("plugin", f"{'Enable' if enabled else 'Disable'} plugin {name} ({prof['label']})")
    path = set_enabled(prof, name, enabled, bk)
    msg = f"{name} {'enabled' if enabled else 'disabled'} in {os.path.basename(path)}{shared_note(path)}."
    return {"message": msg + session_hint(prof), "backup": bk.close()}


def set_enabled(prof, name, enabled, bk):
    """enabledPlugins[name] in the file that already has it, else settings.json. Returns that file."""
    _, source = plugin_switch(prof, name)
    which = source or "settings"
    path = settings_files(prof)[which]
    data, err = load_settings(path)
    if err:
        raise ApiError(f"{os.path.basename(path)} of {prof['label']} has an error ({err}): fix it in the advanced editor")
    ep = data.get("enabledPlugins") if isinstance(data.get("enabledPlugins"), dict) else {}
    ep[name] = enabled
    data["enabledPlugins"] = ep
    save_settings_file(prof, which, data, bk)
    bk.note(f"enabledPlugins.{name} = {json.dumps(enabled)} in {os.path.basename(path)}")
    return path


# ---------------------------------------------------------------------------
# Copy a plugin (a mod, often) to another profile
# ---------------------------------------------------------------------------
# What /plugin install leaves in a profile: the plugin's files under plugins/cache/, its entry
# in installed_plugins.json, its marketplace in known_marketplaces.json (with the marketplace's
# copy under plugins/marketplaces/, which /plugin update reads) and enabledPlugins in the settings.
# The copy writes the same in the target profile, with the paths moved to its folder.
def inside(path, folder):
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder + os.sep)


def moved(path, src_dir, dst_dir):
    """path, from inside src_dir to the same place inside dst_dir."""
    return os.path.join(dst_dir, os.path.relpath(os.path.realpath(path), os.path.realpath(src_dir)))


def copy_plan(pid, name, to_pid):
    src, dst = profile(pid), profile(to_pid)
    if src["id"] == dst["id"]:
        raise ApiError("Pick another profile")
    sdir, ddir = os.path.join(src["dir_abs"], "plugins"), os.path.join(dst["dir_abs"], "plugins")
    if os.path.isdir(ddir) and os.path.realpath(sdir) == os.path.realpath(ddir):
        raise ApiError(f"{dst['label']} already has it: the two profiles share their plugins")
    installs = [i for i in installed_plugins(sdir).get(name) or [] if i.get("scope", "user") == "user"]
    if not installs:
        raise ApiError(f"{name} is not installed for every project in {src['label']}: only those can be copied "
                       "(install it in the other profile with /plugin)", 404)
    if name in installed_plugins(ddir):
        raise ApiError(f"{dst['label']} already has {name}: remove it there with /plugin first")
    for i in installs:
        if not inside(i.get("installPath", ""), sdir) or not os.path.isdir(i["installPath"]):
            raise ApiError(f"The files of {name} are not in {pretty(sdir)}: install it in {dst['label']} with /plugin")
    market = name.partition("@")[2]
    known = read_json(os.path.join(ddir, "known_marketplaces.json"), {}) or {}
    src_market = (read_json(os.path.join(sdir, "known_marketplaces.json"), {}) or {}).get(market)
    return src, dst, sdir, ddir, installs, (market if market and market not in known and src_market else None)


def op_plugin_copy(pid, name, to_pid):
    src, dst, sdir, ddir, installs, market = copy_plan(pid, name, to_pid)
    bk = Backup("plugin-copy", f"Copy plugin {name}: {src['label']} → {dst['label']}")
    bk.mkdir(ddir)
    entries = []
    for i in installs:
        target = moved(i["installPath"], sdir, ddir)
        if not os.path.lexists(target):  # the same version may be in its cache already
            bk.mkdir(os.path.dirname(target))
            bk.created(target)
            shutil.copytree(os.path.realpath(i["installPath"]), target, symlinks=True)
        entries.append(dict(i, installPath=target))
    if market:
        kpath = os.path.join(ddir, "known_marketplaces.json")
        known = read_json(kpath, {}) or {}
        entry = dict((read_json(os.path.join(sdir, "known_marketplaces.json"), {}) or {})[market])
        where = entry.get("installLocation")
        if isinstance(where, str) and inside(where, sdir) and os.path.isdir(where):
            entry["installLocation"] = moved(where, sdir, ddir)
            if not os.path.lexists(entry["installLocation"]):
                bk.mkdir(os.path.dirname(entry["installLocation"]))
                bk.created(entry["installLocation"])
                shutil.copytree(os.path.realpath(where), entry["installLocation"], symlinks=True)
        bk.copy(kpath, "known_marketplaces.json")
        known[market] = entry
        write_json(kpath, known)
        bk.note(f"marketplace {market} added to {dst['label']}")
    ipath = os.path.join(ddir, "installed_plugins.json")
    data = read_json(ipath, None)
    data = data if isinstance(data, dict) else {"version": 2, "plugins": {}}
    bk.copy(ipath, "installed_plugins.json")
    data.setdefault("plugins", {})[name] = entries
    write_json(ipath, data)
    path = set_enabled(dst, name, True, bk)
    msg = f"{name} copied to {dst['label']} and enabled in {os.path.basename(path)}{shared_note(path)}."
    return {"message": msg + session_hint(dst), "backup": bk.close()}
