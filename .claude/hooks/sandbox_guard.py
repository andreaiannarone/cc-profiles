#!/usr/bin/env python3
"""PreToolUse hook: never start cc-profiles on the real home folder.

CLAUDE.md says to run the app only against a sandbox HOME, because even a first
start writes ~/.cc-profiles/config.json, and every operation writes into the real
Claude Code profiles. This hook turns that rule into a check: a Bash command that
runs cc-profiles (or python -m cc_profiles) without HOME=<another folder> in front
is blocked, and Claude gets the reason. Read-only commands (label, --version,
--help) and the test suite are allowed.
"""
import json
import os
import re
import shlex
import sys

READ_ONLY = {"label", "--version", "-h", "--help"}
REAL_HOMES = {os.path.expanduser("~"), "$HOME", "${HOME}", "~"}


def runs_app(words):
    """True if the simple command `words` starts cc-profiles."""
    if not words:
        return False
    name = os.path.basename(words[0])
    if name == "cc-profiles":
        args = words[1:]
    elif name.startswith("python") and words[1:3] == ["-m", "cc_profiles"]:
        args = words[3:]
    else:
        return False
    return not any(a in READ_ONLY for a in args)


SEPARATORS = ";&|()\n"


def simple_commands(command):
    """Split a shell command line into its simple commands, as lists of words.
    Quotes are read first, so a separator inside a string (a commit message
    over several lines, say) does not start a new command."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=SEPARATORS)
    lex.whitespace = " \t\r"  # a newline separates commands, like ;
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError:  # unbalanced quotes: fall back to a rough split
        return [s.split() for s in re.split(r"[;&|()\n]", command)]
    out, words = [], []
    for t in tokens:
        if t and all(c in SEPARATORS for c in t):
            out.append(words)
            words = []
        else:
            words.append(t)
    out.append(words)
    return out


def blocked(command):
    sandbox = False
    for words in simple_commands(command):
        if words and words[0] in ("env", "export"):
            words = words[1:]
            while words and words[0].startswith("-"):  # env -i, export -n, …
                words = words[1:]
        home = None
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            key, _, value = words.pop(0).partition("=")
            if key == "HOME":
                home = value
        here = sandbox if home is None else home.rstrip("/") not in REAL_HOMES
        if not words:  # a bare assignment or export: it holds for the commands that follow
            sandbox = here
        elif runs_app(words) and not here:  # HOME=… before a command holds for that command only
            return True
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    command = (data.get("tool_input") or {}).get("command") or ""
    if blocked(command):
        sys.stderr.write(
            "Blocked by .claude/hooks/sandbox_guard.py: this starts cc-profiles on the real home folder, "
            "which writes ~/.cc-profiles and the real Claude Code profiles. Run it on a sandbox instead, "
            "e.g. HOME=\"$(mktemp -d)\" .venv/bin/cc-profiles --port 4799, or use the /sandbox skill.\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
