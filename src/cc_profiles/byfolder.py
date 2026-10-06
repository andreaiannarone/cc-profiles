# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Profile by folder (`cc-profiles which` and `cc-profiles shell-init`).

Once the shell function is installed, `cc-profiles which` runs every time the user
starts `claude`. So this module imports nothing from the package and only light
standard modules: no server, no core. It is also where rules are matched (core and
paths use san() and match_rule() from here), so `which` and the Projects tab always
agree on a project's profile. Read-only: it never writes anything.
"""

import json
import os
import re
import sys

SHELLS = ("zsh", "bash")
SHELL_MARK = "# cc-profiles: profile by folder"


def san(path):
    """Directory name Claude Code uses in projects/: every non-alphanumeric char -> '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def match_rule(rules, path, dirname):
    """The profile id the rules give a project ('shared' included), or None.
    `path` may be None when only the folder name in projects/ is known.
    Exact rules first, then the first `match` rule whose text is in the path."""
    for r in rules:
        if "exact" in r:
            target = os.path.expanduser(r["exact"]).rstrip("/") or "/"
            if path == target or (path is None and dirname == san(target)):
                return r["profile"]
    for r in rules:
        m = r.get("match")
        if not m:
            continue
        if path is not None and m in path:
            return r["profile"]
        if path is None and san(m) in dirname:
            return r["profile"]
    return None


def config_file():
    """The same file as core.CONFIG_FILE, without importing core."""
    data = os.path.expanduser(os.environ.get("CC_PROFILES_HOME", "~/.cc-profiles"))
    return os.path.join(data, "config.json")


def read_config():
    """config.json, or {} when it is missing or broken. Never creates it."""
    try:
        with open(config_file()) as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def pick(cfg, path):
    """(profile id from the rules or None, the profile `claude` gets in `path` or None).
    The profile is None when no rule matches, when the rule says "shared", or when it
    names a profile that is not in the config any more."""
    rules = [r for r in cfg.get("rules") or [] if isinstance(r, dict) and "profile" in r]
    pid = match_rule(rules, path, san(path))
    if pid and pid != "shared":
        for p in cfg.get("profiles") or []:
            if isinstance(p, dict) and p.get("id") == pid and p.get("dir"):
                return pid, p
    return pid, None


def resolve(path=None):
    """The absolute, real path `which` matches: the current folder by default.
    Claude Code records the real path (symlinks resolved), so do the same."""
    if not path:
        return os.getcwd()
    return os.path.realpath(os.path.expanduser(path))


def profile_dir(p):
    """A profile's config folder as an absolute path, without a trailing slash."""
    return os.path.expanduser(p["dir"]).rstrip("/") or "/"


def shell_line(shell):
    """The line that turns the feature on in a shell's startup file."""
    return f'eval "$(cc-profiles shell-init {shell})"  {SHELL_MARK}'


def shell_function(shell):
    """The `claude` function for zsh or bash. `function claude {` instead of
    `claude() {`, so that an alias called claude does not break the definition in zsh.
    The default profile (~/.claude) leaves CLAUDE_CONFIG_DIR unset, as Claude Code
    expects: set to ~/.claude, it would read ~/.claude/.claude.json instead of ~/.claude.json."""
    return f"""{SHELL_MARK} ({shell})
# `claude` starts in the profile the cc-profiles rules give the current folder.
# A CLAUDE_CONFIG_DIR you set yourself always wins; without cc-profiles, claude runs as usual.
function claude {{
  if [ -z "${{CLAUDE_CONFIG_DIR:-}}" ] && command -v cc-profiles >/dev/null 2>&1; then
    local __ccp_dir
    __ccp_dir="$(cc-profiles which --dir 2>/dev/null)"
    if [ -n "$__ccp_dir" ] && [ "$__ccp_dir" != "${{HOME%/}}/.claude" ]; then
      CLAUDE_CONFIG_DIR="$__ccp_dir" command claude "$@"
      return
    fi
  fi
  command claude "$@"
}}
"""


def default_shell():
    name = os.path.basename(os.environ.get("SHELL", ""))
    return name if name in SHELLS else "bash"


def add_parsers(sub):
    """The `which` and `shell-init` subcommands, for cli.main and for the fast path."""
    w = sub.add_parser("which", help="print the profile the rules give a folder (default: the current one)")
    w.add_argument("path", nargs="?", default="", help="folder to check (default: the current folder)")
    w.add_argument("--dir", action="store_true", help="print the profile's config folder instead of its name")
    s = sub.add_parser("shell-init", help="print the shell function that starts claude in the folder's profile")
    s.add_argument("shell", nargs="?", choices=SHELLS, default=None, help="zsh or bash (default: from $SHELL)")


def run(args):
    """Run `which` or `shell-init`. Returns the exit status."""
    if args.cmd == "shell-init":
        sys.stdout.write(shell_function(args.shell or default_shell()))
        return 0
    try:
        path = resolve(args.path)
    except OSError:  # the current folder was deleted
        return 1
    pid, p = pick(read_config(), path)
    if p is None:
        if not args.dir:
            why = "a rule says it belongs to every profile" if pid == "shared" else "no rule matches it"
            sys.stderr.write(f"No profile for {path}: {why}.\n")
        return 1
    print(profile_dir(p) if args.dir else p.get("label") or p["id"])
    return 0


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="cc-profiles")
    add_parsers(ap.add_subparsers(dest="cmd"))
    return run(ap.parse_args(argv))
