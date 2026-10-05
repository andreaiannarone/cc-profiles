# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Plugins."""

import json
import os

from .core import ApiError, Backup, load_settings, pretty, profile, read_json
from .settings import save_settings_file, settings_files, shared_note
from .extensions import session_hint
from .transfer import share_note

# ---------------------------------------------------------------------------
# Plugins
# ---------------------------------------------------------------------------
# Installing and removing plugins is Claude Code's job (/plugin): here they are
# listed, and enabled or disabled through enabledPlugins in the settings files.
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
    installed = (read_json(os.path.join(pdir, "installed_plugins.json"), {}) or {}).get("plugins") or {}
    names = set(installed)
    for path in settings_files(prof).values():
        if path.endswith(".json"):
            ep = load_settings(path)[0].get("enabledPlugins")
            if isinstance(ep, dict):
                names |= set(ep)
    items = []
    for name in sorted(names):
        installs = installed.get(name) or []
        if isinstance(installs, dict):  # an older format: one install per plugin
            installs = [installs]
        first = installs[0] if installs else {}
        plugin, _, market = name.partition("@")
        value, source = plugin_switch(prof, name)
        items.append({"name": name, "plugin": plugin, "marketplace": market,
                      "version": first.get("version", ""), "installed": (first.get("installedAt") or "")[:10],
                      "path": pretty(first.get("installPath", "")), "is_installed": bool(installs),
                      "scopes": sorted({i.get("scope", "user") for i in installs}),
                      "projects": [pretty(i["projectPath"]) for i in installs if i.get("projectPath")],
                      "enabled": value, "source": source})
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
    _, source = plugin_switch(prof, name)
    which = source or "settings"
    path = settings_files(prof)[which]
    data, _ = load_settings(path)
    bk = Backup("plugin", f"{'Enable' if enabled else 'Disable'} plugin {name} ({prof['label']})")
    ep = data.get("enabledPlugins") if isinstance(data.get("enabledPlugins"), dict) else {}
    ep[name] = enabled
    data["enabledPlugins"] = ep
    save_settings_file(prof, which, data, bk)
    bk.note(f"enabledPlugins.{name} = {json.dumps(enabled)} in {os.path.basename(path)}")
    msg = f"{name} {'enabled' if enabled else 'disabled'} in {os.path.basename(path)}{shared_note(path)}."
    return {"message": msg + session_hint(prof), "backup": bk.close()}
