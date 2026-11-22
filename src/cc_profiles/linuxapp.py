# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: the Linux app (cc-profiles install-app on Linux)."""

import os
import subprocess
import sys

from . import __version__, core
from .core import CONFIG_FILE, HOME, ApiError, Backup, find_tool, load_config, pretty, write_json, write_text
from .macapp import icon_png, launch_command

# ---------------------------------------------------------------------------
# The Linux app
# ---------------------------------------------------------------------------
# No program of its own: a desktop entry (the freedesktop.org standard every Linux desktop reads)
# puts cc-profiles in the applications menu with its icon, and runs `cc-profiles open`. With the
# entry there, `open` shows the page in a window of its own: a Chromium-based browser in app mode
# (--app=URL: no tabs, no address bar), else the default browser. The entry has DESKTOP_MARK: only
# an entry with it is rewritten or removed. The server rewrites it at start when the command, the
# version or the port changes (ensure_app), as it does the Mac app.
DATA_HOME = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
DESKTOP_PATH = os.path.join(DATA_HOME, "applications", "cc-profiles.desktop")
ICON_PATH = os.path.join(DATA_HOME, "icons", "hicolor", "256x256", "apps", "cc-profiles.png")
DESKTOP_MARK = "X-CC-Profiles-Managed=true"
# Chromium-based browsers that open a page as an app window, in order of preference
APP_BROWSERS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                "microsoft-edge", "microsoft-edge-stable", "brave-browser", "vivaldi")


def supported():
    """Linux with a desktop (not WSL, where Windows draws the windows). Tests set
    CC_PROFILES_LINUX_APP: 0 (child_env) leaves it out, 1 forces it on any system."""
    forced = os.environ.get("CC_PROFILES_LINUX_APP")
    if forced in ("0", "1"):
        return forced == "1"
    return sys.platform.startswith("linux") and not core.is_wsl()


def quote(arg):
    """One argument of the Exec line, quoted as the Desktop Entry spec asks when needed."""
    if arg and not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    return '"' + "".join("\\" + c if c in '"`$\\' else c for c in arg) + '"'


def desktop_text(port):
    cmd = launch_command() + ["open", "--port", str(port)]
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=cc-profiles",
        "GenericName=Claude Code profiles",
        "Comment=Manage your Claude Code profiles, projects and memories",
        "Exec=" + " ".join(quote(a).replace("%", "%%") for a in cmd),
        f"Icon={ICON_PATH}",
        "Terminal=false",
        "Categories=Development;Utility;",
        "Keywords=claude;claude code;profiles;",
        "StartupNotify=false",
        "StartupWMClass=cc-profiles",
        DESKTOP_MARK,
        f"X-CC-Profiles-Version={__version__}",
        f"X-CC-Profiles-Port={port}",
        ""])


def entry_values(path=DESKTOP_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    return dict(l.split("=", 1) for l in lines if "=" in l)


def is_our_entry(path=DESKTOP_PATH):
    v = entry_values(path)
    return bool(v) and v.get("X-CC-Profiles-Managed") == "true"


def entry_port():
    try:
        return int((entry_values() or {}).get("X-CC-Profiles-Port", ""))
    except ValueError:
        return None


def app_state():
    """missing, current, outdated (another version, command or port) or foreign."""
    if not os.path.lexists(DESKTOP_PATH):
        return "missing"
    if not is_our_entry():
        return "foreign"
    port = entry_port() or core.PORT
    try:
        same = open(DESKTOP_PATH, encoding="utf-8").read() == desktop_text(port)
    except OSError:
        same = False
    return "current" if same and os.path.isfile(ICON_PATH) else "outdated"


def write_entry(port, bk):
    for folder in (os.path.dirname(DESKTOP_PATH), os.path.dirname(ICON_PATH)):
        bk.mkdir(folder)
    bk.copy(ICON_PATH, "cc-profiles.png")
    with open(ICON_PATH + ".tmp", "wb") as f:
        f.write(icon_png(256))
    os.replace(ICON_PATH + ".tmp", ICON_PATH)
    bk.copy(DESKTOP_PATH, "cc-profiles.desktop")
    write_text(DESKTOP_PATH, desktop_text(port))
    os.chmod(DESKTOP_PATH, 0o755)  # some desktops only trust an executable entry
    refresh_menu()


def refresh_menu():
    """Ask the desktop to read the applications folder again; most watch it anyway."""
    tool = find_tool("update-desktop-database")
    if tool and os.environ.get("CC_PROFILES_LINUX_APP") != "1":
        try:
            subprocess.run([tool, os.path.dirname(DESKTOP_PATH)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass


def remember_app(on, bk):
    """"linux_app" in config.json: the server adds the entry only once, never against the user's choice."""
    cfg = load_config()
    if cfg.get("linux_app") is not on:
        bk.copy(CONFIG_FILE, "config.json")
        cfg["linux_app"] = on
        write_json(CONFIG_FILE, cfg)


def install_app(port):
    """cc-profiles install-app on Linux. Returns (lines to print, backup path)."""
    if not supported():
        raise ApiError(f"The app needs Linux with a desktop: open http://127.0.0.1:{port} in your browser")
    state = app_state()
    if state == "foreign":
        raise ApiError(f"{pretty(DESKTOP_PATH)} exists and was not created by cc-profiles: move it away first")
    if state == "current" and entry_port() == port:
        if load_config().get("linux_app") is not True:
            bk = Backup("linux-app", "Keep the Linux app")
            remember_app(True, bk)
            return ["cc-profiles is already in your applications menu."], bk.close()
        return ["cc-profiles is already in your applications menu."], None
    bk = Backup("linux-app", "Update the Linux app" if state != "missing" else "Add the Linux app")
    remember_app(True, bk)
    write_entry(port, bk)
    bk.note(f"Linux app: {pretty(DESKTOP_PATH)}, port {port}")
    verb = "Updated" if state != "missing" else "Added"
    return [f"{verb} cc-profiles in your applications menu ({pretty(DESKTOP_PATH)})."
            + ("" if app_browser() else " No Chrome, Chromium, Edge or Brave found: it opens in your browser.")], bk.close()


def app_status():
    if not supported():
        return {"supported": False}
    state = app_state()
    port = entry_port()
    if state == "current" and port != core.PORT:
        state = "outdated"
    return {"supported": True, "kind": "linux", "state": state, "path": pretty(DESKTOP_PATH), "port": port,
            "window": bool(app_browser())}


def op_install_app():
    lines, backup = install_app(core.PORT)
    return dict(app_status(), message=lines[0], backup=backup)


def set_app_off():
    if load_config().get("linux_app") is False:
        return None
    bk = Backup("linux-app-off", "Stop adding the Linux app")
    remember_app(False, bk)
    return bk.close()


def ensure_app():
    """At every start, on Linux: the first time the entry is added; after that one the user
    removed stays removed, and one cc-profiles made is rewritten when it is outdated."""
    state = app_state() if supported() else None
    if state not in ("missing", "outdated"):
        return [], None
    wanted = load_config().get("linux_app")
    auto = os.environ.get("CC_PROFILES_AUTO_APP") != "0"
    if state == "missing" and wanted is None and auto:
        bk = Backup("linux-app", "Add the Linux app")
        remember_app(True, bk)
        write_entry(core.PORT, bk)
        bk.note(f"Linux app: {pretty(DESKTOP_PATH)}, port {core.PORT}")
        return ["added cc-profiles to your applications menu"], bk.close()
    if state != "outdated":
        return [], None
    bk = Backup("linux-app", "Update the Linux app")
    if wanted is None:
        remember_app(True, bk)
    write_entry(entry_port() or core.PORT, bk)
    return ["updated the applications menu entry"], bk.close()


def uninstall_paths():
    """What cc-profiles uninstall removes: the entry, if it is ours, and its icon."""
    return [p for p in (DESKTOP_PATH, ICON_PATH) if os.path.lexists(p)] if is_our_entry() else []


def app_browser():
    """A browser that opens a page as an app window (tests: CC_PROFILES_APP_BROWSER)."""
    forced = os.environ.get("CC_PROFILES_APP_BROWSER")
    if forced is not None:
        return forced or None
    return next((b for b in map(find_tool, APP_BROWSERS) if b), None)


def window_for(port):
    """With our entry on this port, on Linux: the command that shows the page in a window. None otherwise."""
    if not supported() or not is_our_entry() or entry_port() != port:
        return None
    b = app_browser()
    return [b, f"--app=http://127.0.0.1:{port}", "--class=cc-profiles"] if b else None
