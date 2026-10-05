# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Command line."""

import argparse
import http.client
import os
import subprocess
import sys
import threading
import time
import webbrowser

from . import __version__
from . import core
from .core import CONFIG_FILE, DATA_DIR, expand, load_config, pretty, read_json
from .command import install_command
from .web import Handler, Server

# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def current_label():
    """Label of the profile Claude Code is using now (for status lines)."""
    d = os.path.realpath(expand(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")).rstrip("/")
    cfg = read_json(CONFIG_FILE, {}) or {}
    for p in cfg.get("profiles", []):
        if os.path.realpath(expand(p["dir"])).rstrip("/") == d:
            return p["label"]
    base = os.path.basename(d)
    return base[len(".claude-"):] if base.startswith(".claude-") else "default"


def serve(port, open_browser):
    core.PORT = port
    core.ALLOWED_HOSTS = {f"127.0.0.1:{port}", f"localhost:{port}"}
    load_config()
    try:
        srv = Server(("127.0.0.1", port), Handler)
    except OSError:
        print(f"Port {port} is busy: cc-profiles may already be running.")
        print(f"Open http://127.0.0.1:{port} or use --port {port + 1}.")
        sys.exit(1)
    url = f"http://127.0.0.1:{port}"
    print(f"cc-profiles {__version__} on {url}  (ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def is_running(port):
    """True if cc-profiles answers on the port (another program there does not count).
    http.client talks to 127.0.0.1 directly, without urllib's proxy handling."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        conn.request("GET", "/")
        return (conn.getresponse().getheader("Server") or "").startswith("cc-profiles/")
    except (OSError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def open_app(port, open_browser):
    """Start the server in the background unless it is running, then open the browser.

    Returns at once, so it can run from a Claude Code slash command."""
    url = f"http://127.0.0.1:{port}"
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
        print(f"cc-profiles started in the background on {url} (pid {proc.pid}). Stop it with: kill {proc.pid}")
    if open_browser:
        webbrowser.open(url)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cc-profiles", description="A local web UI to manage Claude Code profiles.")
    ap.add_argument("--version", action="version", version=f"cc-profiles {__version__}")
    ap.add_argument("--port", type=int, default=core.PORT, help="port to listen on (default: 4777, or CC_PROFILES_PORT)")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("label", help="print the label of the active profile (for status lines)")
    sub.add_parser("install-command", help="add the /cc-profiles command to Claude Code in every profile")
    op = sub.add_parser("open", help="start in the background if needed, open the browser and return")
    op.add_argument("--port", type=int, default=argparse.SUPPRESS, help="port to listen on")
    op.add_argument("--no-browser", action="store_true", default=argparse.SUPPRESS, help="do not open the browser")
    args = ap.parse_args(argv)
    if args.cmd == "label":
        print(current_label())
        return
    if os.name == "nt":
        print("cc-profiles supports macOS and Linux only for now.")
        sys.exit(1)
    if args.cmd == "install-command":
        lines, backup = install_command()
        print("\n".join(lines))
        if backup:
            print(f"Backup: {backup} (undo it from the Backups tab)")
        print("Restart Claude Code sessions that are already open to see /cc-profiles.")
        return
    if args.cmd == "open":
        open_app(args.port, not args.no_browser)
        return
    serve(args.port, not args.no_browser)


if __name__ == "__main__":
    main()
