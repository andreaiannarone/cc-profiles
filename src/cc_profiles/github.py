# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: a GitHub account per profile."""

import glob
import os
import re
import subprocess

from .core import (HOME, ApiError, Backup, find_tool, load_settings, pretty, profile, profiles, read_json,
                   session_hint, tool_env, write_json, write_text)
from .settings import save_settings_file, settings_files, shared_note

# ---------------------------------------------------------------------------
# GitHub accounts
# ---------------------------------------------------------------------------
# The GitHub CLI keeps its sign-in in a config folder (~/.config/gh, or the one in GH_CONFIG_DIR),
# with the token in the system keychain. A profile picks an account with GH_CONFIG_DIR in the "env"
# of its settings, which Claude Code passes to every command it runs; git follows when its
# credential helper is `gh auth git-credential` (`gh auth setup-git`). GIT_AUTHOR_* and
# GIT_COMMITTER_* set who the commits are by. Signing in is `gh auth login`, in a terminal:
# cc-profiles only reads which user each folder is signed in as, never a token.
GH_HOST = "github.com"
GH_ENV = "GH_CONFIG_DIR"
GIT_ENV = {"name": ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"), "email": ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL")}
EMAIL = re.compile(r"[^@\s]+@[^@\s]+")
TOKEN_LINE = re.compile(r"^\s*[A-Za-z_]*token[A-Za-z_]*\s*:", re.I)  # gh's insecure storage: never copied


def gh_default_dir():
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return os.path.join(xdg, "gh") if xdg else os.path.join(HOME, ".config", "gh")


def gh_user(folder):
    """The github.com user a gh config folder is signed in as (the `user:` line of hosts.yml), or None."""
    try:
        with open(os.path.join(folder, "hosts.yml")) as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    host = None
    for line in lines:
        if line and not line[0].isspace():
            host = line.rstrip(":").strip().strip("'\"")
        elif host == GH_HOST and line.strip().startswith("user:"):
            return line.split(":", 1)[1].strip().strip("'\"") or None
    return None


def profile_env(prof):
    """The profile's "env" from its settings files, and which file each key comes from (local wins)."""
    f = settings_files(prof)
    env, where = {}, {}
    for which in ("settings", "local"):
        data, _ = load_settings(f[which])
        for k, v in (data.get("env") if isinstance(data.get("env"), dict) else {}).items():
            env[k], where[k] = v, which
    return env, where


def gh_folders():
    """Every gh config folder: the default one, ~/.config/gh-*, and any a profile points to."""
    found = [gh_default_dir()] + sorted(glob.glob(os.path.join(HOME, ".config", "gh-*")))
    for p in profiles():
        d = profile_env(p)[0].get(GH_ENV)
        if isinstance(d, str) and d:
            found.append(os.path.expanduser(d))
    out, seen = [], set()
    for d in found:
        real = os.path.realpath(d)
        if real not in seen and (os.path.isdir(d) or d == gh_default_dir()):
            seen.add(real)
            out.append(d)
    return out


def git_uses_gh():
    """Whether git asks gh for github.com passwords: otherwise git push ignores GH_CONFIG_DIR."""
    git = find_tool("git")
    if not git:
        return None
    helpers = []
    for key in ("credential.https://github.com.helper", "credential.helper"):
        try:
            r = subprocess.run([git, "config", "--global", "--get-all", key], capture_output=True, text=True,
                               timeout=5, env=tool_env())
            helpers += r.stdout.split("\n")
        except (OSError, subprocess.TimeoutExpired):
            return None
    return any("gh auth git-credential" in h for h in helpers)


def profile_github(prof):
    """The GitHub account a profile's Claude Code sessions use: its GH_CONFIG_DIR, or the default folder."""
    d = profile_env(prof)[0].get(GH_ENV)
    folder = os.path.expanduser(d) if isinstance(d, str) and d else gh_default_dir()
    return {"user": gh_user(folder), "dir": pretty(folder), "own": bool(d)}


def new_profile_folder(pid):
    return os.path.join(HOME, ".config", f"gh-{pid}")


def give_gh_folder(new, pid, bk):
    """A GitHub CLI folder of its own for a new profile, ~/.config/gh-<id>, signed in as the default
    folder's account for now, and GH_CONFIG_DIR in the profile's settings.json. Only hosts.yml without
    any token line and config.yml are copied: gh keeps the token in the keychain, under the user's
    name, so the new folder finds it. Returns a note for the message, or None when nothing was done."""
    settings = os.path.join(new, "settings.json")
    if os.path.islink(settings):
        return "its settings.json is shared, so its GitHub account is too: pick another one in the GitHub section"
    src, dst = gh_default_dir(), new_profile_folder(pid)
    user, needs_login = gh_user(src), False
    if not os.path.lexists(dst):
        if not user:
            return None  # gh is not signed in: nothing to give it yet
        bk.mkdir(os.path.dirname(dst))
        bk.created(dst)
        os.mkdir(dst, 0o700)
        with open(os.path.join(src, "hosts.yml")) as f:
            lines = f.read().splitlines()
        needs_login = any(TOKEN_LINE.match(l) for l in lines)  # that token stays behind
        write_text(os.path.join(dst, "hosts.yml"), "\n".join(l for l in lines if not TOKEN_LINE.match(l)) + "\n")
        os.chmod(os.path.join(dst, "hosts.yml"), 0o600)
        if os.path.isfile(os.path.join(src, "config.yml")):
            with open(os.path.join(src, "config.yml")) as f:
                write_text(os.path.join(dst, "config.yml"), f.read())
    elif not gh_user(dst):
        needs_login = True
    data = read_json(settings, {}) if os.path.exists(settings) else {}
    data = data if isinstance(data, dict) else {}
    env = dict(data.get("env") if isinstance(data.get("env"), dict) else {})
    env[GH_ENV] = dst
    data["env"] = env
    write_json(settings, data)  # inside the new profile's folder: restoring removes it with the folder
    bk.note(f"{GH_ENV} = {pretty(dst)}")
    if needs_login:
        return f"sign in to GitHub for it with GH_CONFIG_DIR={pretty(dst)} gh auth login"
    return f"GitHub as {gh_user(dst)} from {pretty(dst)}: to change account, GH_CONFIG_DIR={pretty(dst)} gh auth login"


def github_state():
    accounts = [{"dir": pretty(d), "path": d, "user": gh_user(d), "default": d == gh_default_dir()}
                for d in gh_folders()]
    by_path = {os.path.realpath(a["path"]): a for a in accounts}
    rows = []
    for p in profiles():
        env, where = profile_env(p)
        d = env.get(GH_ENV)
        acc = by_path.get(os.path.realpath(os.path.expanduser(d))) if isinstance(d, str) and d else \
            by_path.get(os.path.realpath(gh_default_dir()))
        rows.append({"id": p["id"], "label": p["label"], "dir": pretty(acc["path"]) if acc else d,
                     "own": bool(d), "user": acc["user"] if acc else None,
                     "name": env.get(GIT_ENV["name"][0], ""), "email": env.get(GIT_ENV["email"][0], ""),
                     "files": sorted({where[k] for k in (GH_ENV,) + GIT_ENV["name"] + GIT_ENV["email"] if k in where})})
    return {"gh": bool(find_tool("gh")), "git_uses_gh": git_uses_gh(), "accounts": accounts, "profiles": rows,
            "new_dir": pretty(new_profile_folder("<name>")), "default_user": gh_user(gh_default_dir())}


def op_github(pid, folder, name, email):
    """Point a profile to a gh config folder (None: the default one) and set who its commits are by."""
    prof = profile(pid)
    name, email = (name or "").strip(), (email or "").strip()
    if "\n" in name or "\n" in email:
        raise ApiError("Name and email must be one line each")
    if bool(name) != bool(email):
        raise ApiError("Write both the name and the email for commits, or neither")
    if email and not EMAIL.fullmatch(email):
        raise ApiError(f"Not an email address: {email}")
    path = None
    if folder:
        path = next((d for d in gh_folders() if pretty(d) == folder or d == folder), None)
        if path is None:
            raise ApiError(f"Unknown GitHub CLI folder: {folder}. Sign in there first with gh auth login")
        if not gh_user(path):
            raise ApiError(f"{pretty(path)} is not signed in to github.com: run GH_CONFIG_DIR={pretty(path)} gh auth login")
        if os.path.realpath(path) == os.path.realpath(gh_default_dir()):
            path = None  # the default folder needs no variable
    want = {GH_ENV: path}
    for k in GIT_ENV["name"]:
        want[k] = name or None
    for k in GIT_ENV["email"]:
        want[k] = email or None

    f = settings_files(prof)
    files = {which: load_settings(f[which]) for which in ("settings", "local")}
    for which, (_, err) in files.items():
        if err:
            raise ApiError(f"{os.path.basename(f[which])} has an error ({err}): fix it in the advanced editor")
    changed = set()
    for k, v in want.items():
        holders = [w for w, (d, _) in files.items() if isinstance(d.get("env"), dict) and k in d["env"]]
        if v is None:
            targets = holders
        else:  # where the key already is, otherwise settings.json
            targets = [w for w in holders if files[w][0]["env"][k] != v] if holders else ["settings"]
        for w in targets:
            data = files[w][0]
            env = dict(data.get("env") if isinstance(data.get("env"), dict) else {})
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
            if env:
                data["env"] = env
            else:
                data.pop("env", None)
            changed.add(w)
    if not changed:
        return {"message": f"{prof['label']} already uses these GitHub settings."}
    user = gh_user(path or gh_default_dir())
    bk = Backup("github", f"GitHub account of {prof['label']}")
    for w in sorted(changed):
        save_settings_file(prof, w, files[w][0], bk)
    bk.note(f"{GH_ENV} = {pretty(path) if path else '(default)'}; commits by {name or '(git config)'} <{email}>")
    msg = (f"{prof['label']} uses GitHub as {user or 'nobody yet'}"
           + (f", commits by {name} <{email}>" if name else "")
           + f"{shared_note(f['settings'])}." + session_hint(prof))
    return {"message": msg, "backup": bk.close()}
