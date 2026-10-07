# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Command line."""

import argparse
import http.client
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser

from . import __version__
from . import core
from .core import CONFIG_FILE, DATA_DIR, expand, find_tool, load_config, pretty, profiles, read_json
from .byfolder import add_parsers, run as run_byfolder
from .backups import AUTO_PRUNE, auto_prune, list_backups, recent_dir_size
from .command import ensure_command, install_command, set_command_off
from .projects import list_projects
from .search import warm_search
from .usage import warm_usage
from .web import Handler, Server

# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def open_url(url):
    """Open the app in the browser. Under WSL the browser is a Windows program that Python's
    webbrowser does not know: wslview (from wslu) if installed, else Windows' own handler."""
    if core.is_wsl():
        for cmd in (["wslview", url], ["cmd.exe", "/c", "start", "", url]):
            exe = find_tool(cmd[0])
            if exe:
                try:
                    subprocess.Popen([exe] + cmd[1:], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
                except OSError:
                    continue
    webbrowser.open(url)


def current_label():
    """Label of the profile Claude Code is using now (for status lines)."""
    d = os.path.realpath(expand(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")).rstrip("/")
    cfg = read_json(CONFIG_FILE, {}) or {}
    for p in cfg.get("profiles", []):
        if os.path.realpath(expand(p["dir"])).rstrip("/") == d:
            return p["label"]
    base = os.path.basename(d)
    return base[len(".claude-"):] if base.startswith(".claude-") else "default"


def cleanup_backups():
    """The automatic backup cleanup, if it is on (see backups.auto_prune)."""
    try:
        with core._lock:
            if auto_prune():
                print(f"Automatic backup cleanup: {AUTO_PRUNE['message']}")
    except Exception as e:  # noqa: BLE001 - a failed cleanup must not stop the server
        print(f"Automatic backup cleanup failed: {e}")


def cleanup_daily():
    while True:
        time.sleep(86400)
        cleanup_backups()


def warm_caches():
    """Read in the background what the first tabs need, so that they open fast on a
    large home. Read-only: it only fills the caches described in docs/architecture.md."""
    try:
        list_projects()
        list_backups()
        for p in profiles():
            recent_dir_size(p["dir_abs"])
        warm_search()
        warm_usage()
    except Exception:  # a cold cache is only slower, never wrong
        pass


def stop_gracefully(signum, frame):
    """SIGTERM (cc-profiles stop, restart, kill): let a write in progress finish, then exit."""
    core._lock.acquire(timeout=60)
    os._exit(0)


def serve(port, open_browser):
    core.PORT = port
    core.ALLOWED_HOSTS = {f"127.0.0.1:{port}", f"localhost:{port}"}
    load_config()
    try:  # /cc-profiles in every profile the first time, kept up to date after an update
        lines, backup = ensure_command() if os.environ.get("CC_PROFILES_AUTO_COMMAND") != "0" else ([], None)
        if lines:
            print("/cc-profiles in Claude Code: " + "; ".join(lines) + f" (backup {pretty(backup)})")
    except Exception as e:  # never a reason not to start
        core.abort_open_backups(str(e))
        print(f"Could not add the /cc-profiles command to Claude Code: {e}. Run: cc-profiles install-command")
    cleanup_backups()
    threading.Thread(target=cleanup_daily, daemon=True).start()
    signal.signal(signal.SIGTERM, stop_gracefully)
    try:
        srv = Server(("127.0.0.1", port), Handler)
    except OSError:
        print(f"Port {port} is busy: cc-profiles may already be running.")
        print(f"Open http://127.0.0.1:{port} or use --port {port + 1}.")
        sys.exit(1)
    url = f"http://127.0.0.1:{port}"
    print(f"cc-profiles {__version__} on {url}  (ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: open_url(url)).start()
    threading.Thread(target=warm_caches, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def probe(port):
    """(running, pid): whether cc-profiles answers on the port (another program there
    does not count) and the pid it reports (None before 0.4.1).
    http.client talks to 127.0.0.1 directly, without urllib's proxy handling."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        conn.request("GET", "/")
        res = conn.getresponse()
        if not (res.getheader("Server") or "").startswith("cc-profiles/"):
            return False, None
        pid = res.getheader("X-CC-Profiles-Pid") or ""
        return True, int(pid) if pid.isdigit() else None
    except (OSError, http.client.HTTPException):
        return False, None
    finally:
        conn.close()


def is_running(port):
    return probe(port)[0]


def listening_pid(port):
    """The pid listening on the port, from lsof: for servers too old to report it."""
    lsof = find_tool("lsof")
    if not lsof:
        return None
    r = subprocess.run([lsof, "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True)
    pids = [int(x) for x in r.stdout.split() if x.isdigit()]
    return pids[0] if len(pids) == 1 else None


def stop_app(port):
    """Stop the cc-profiles server on the port, if one is running. A write in progress
    finishes first. Exits with status 1 when it cannot be stopped."""
    url = f"http://127.0.0.1:{port}"
    running, pid = probe(port)
    if not running:
        print(f"cc-profiles is not running on {url}")
        return
    pid = pid or listening_pid(port)
    if not pid:
        print(f"cc-profiles is running on {url}, but its pid is unknown: stop it with kill and the pid it printed when it started.")
        sys.exit(1)
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 70  # stop_gracefully waits up to 60 s for a write to finish
    while time.time() < deadline and is_running(port):
        time.sleep(0.1)
    if is_running(port):
        print(f"cc-profiles on {url} (pid {pid}) did not stop. Try again, or kill {pid}.")
        sys.exit(1)
    print(f"Stopped cc-profiles on {url} (pid {pid}).")


def open_app(port, open_browser):
    """Start the server in the background unless it is running, then open the browser.

    Returns at once, so it can run from a Claude Code slash command."""
    url = f"http://127.0.0.1:{port}"
    port_arg = "" if port == core.PORT else f" --port {port}"
    if is_running(port):
        print(f"cc-profiles is already running on {url}")
    else:
        os.makedirs(DATA_DIR, exist_ok=True)
        log = os.path.join(DATA_DIR, "server.log")
        with open(log, "wb") as out:
            proc = subprocess.Popen(
                [sys.executable, "-m", "cc_profiles", "--port", str(port), "--no-browser"],
                stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
        deadline = time.time() + 15
        while time.time() < deadline and proc.poll() is None and not is_running(port):
            time.sleep(0.1)
        if not is_running(port):
            print(f"cc-profiles did not start. See {pretty(log)}:")
            print(open(log, errors="replace").read().strip())
            sys.exit(1)
        print(f"cc-profiles started in the background on {url} (pid {proc.pid}). Stop it with: cc-profiles stop{port_arg}")
    if open_browser:
        open_url(url)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cc-profiles", description="A local web UI to manage Claude Code profiles.")
    ap.add_argument("--version", action="version", version=f"cc-profiles {__version__}")
    ap.add_argument("--port", type=int, default=core.PORT, help="port to listen on (default: 4777, or CC_PROFILES_PORT)")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("label", help="print the label of the active profile (for status lines)")
    add_parsers(sub)  # which, shell-init: entry.main runs them without loading the server
    ic = sub.add_parser("install-command", help="add the /cc-profiles command to Claude Code in every profile "
                        "(cc-profiles does it by itself the first time it starts)")
    ic.add_argument("--off", action="store_true", help="stop adding and updating /cc-profiles in your profiles")
    op = sub.add_parser("open", help="start in the background if needed, open the browser and return")
    # The /cc-profiles command passes its arguments here: /cc-profiles restart, /cc-profiles stop
    op.add_argument("action", nargs="?", default="", metavar="restart|stop",
                    help="restart or stop the server instead (what /cc-profiles restart and /cc-profiles stop run)")
    op.add_argument("--port", type=int, default=argparse.SUPPRESS, help="port to listen on")
    op.add_argument("--no-browser", action="store_true", default=argparse.SUPPRESS, help="do not open the browser")
    for name, text in (("stop", "stop the server running in the background"),
                       ("restart", "stop the server and start it again in the background, e.g. after an update")):
        sp = sub.add_parser(name, help=text)
        sp.add_argument("--port", type=int, default=argparse.SUPPRESS, help="port it listens on")
    args = ap.parse_args(argv)
    if args.cmd == "label":
        print(current_label())
        return
    if args.cmd in ("which", "shell-init"):
        sys.exit(run_byfolder(args))
    if os.name == "nt":
        print("cc-profiles supports macOS and Linux only for now.")
        sys.exit(1)
    if args.cmd == "install-command" and args.off:
        backup = set_command_off()
        print("cc-profiles will no longer add or update /cc-profiles in your profiles. "
              "Files it already wrote stay: see https://cc-profiles.andreaia.com/uninstall.html to remove them.")
        if backup:
            print(f"Backup: {backup} (undo it from the Backups tab)")
        return
    if args.cmd == "install-command":
        lines, backup = install_command()
        print("\n".join(lines))
        if backup:
            print(f"Backup: {backup} (undo it from the Backups tab)")
        print("Restart Claude Code sessions that are already open to see /cc-profiles.")
        return
    action = args.cmd
    if args.cmd == "open":
        action = args.action.strip() or "open"
        if action not in ("open", "restart", "stop"):
            op.error(f"unknown action: {action}. Use cc-profiles open, cc-profiles open restart or cc-profiles open stop")
    if action == "open":
        open_app(args.port, not args.no_browser)
        return
    if action == "stop":
        stop_app(args.port)
        return
    if action == "restart":
        stop_app(args.port)
        open_app(args.port, False)
        print("Reload the page in your browser.")
        return
    serve(args.port, not args.no_browser)


if __name__ == "__main__":
    main()
