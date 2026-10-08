# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: a GitHub account per profile."""

import os
import re
import subprocess

from .core import (HOME, ApiError, Backup, find_tool, load_settings, pretty, profile, profiles, read_json,
                   session_hint, tool_env, write_json, write_text)
from .settings import save_settings_file, settings_files, shared_note

# ---------------------------------------------------------------------------
# GitHub accounts
# ---------------------------------------------------------------------------
# The GitHub CLI keeps its sign-in in a config folder (~/.config/gh, or the one in GH_CONFIG_DIR):
# hosts.yml lists the users signed in there and the active one; the tokens are in the system
# keychain under each user's name. Every profile has a folder of its own: Default uses
# ~/.config/gh (the same as your terminal), ~/.claude-<id> uses ~/.config/gh-<id> through
# GH_CONFIG_DIR in the "env" of its settings.json, which Claude Code passes to every command it
# runs; git follows when its credential helper is `gh auth git-credential` (`gh auth setup-git`).
# Picking an account makes it the active user of the profile's folder: any user signed in in
# some folder works, because the keychain finds the token by the name. GIT_AUTHOR_* and
# GIT_COMMITTER_* set who the commits are by. cc-profiles never reads a token, and never copies a
# token line (gh's insecure storage writes them in hosts.yml).
GH_HOST = "github.com"
GH_ENV = "GH_CONFIG_DIR"
GIT_ENV = {"name": ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"), "email": ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL")}
EMAIL = re.compile(r"[^@\s]+@[^@\s]+")
USER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")  # GitHub user names
TOKEN_LINE = re.compile(r"^\s*[A-Za-z_]*token[A-Za-z_]*\s*:", re.I)


def gh_default_dir():
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return os.path.join(xdg, "gh") if xdg else os.path.join(HOME, ".config", "gh")


def is_default(prof):
    return os.path.realpath(prof["dir_abs"]) == os.path.realpath(os.path.join(HOME, ".claude"))


def own_folder(prof):
    """The GitHub CLI folder that belongs to a profile."""
    return gh_default_dir() if is_default(prof) else os.path.join(HOME, ".config", f"gh-{prof['id']}")


def hosts_lines(folder):
    try:
        with open(os.path.join(folder, "hosts.yml")) as f:
            return f.read().splitlines()
    except OSError:
        return []


def github_block(lines):
    """(start, end, indent) of the github.com entry in hosts.yml lines, or None."""
    for i, line in enumerate(lines):
        if line.rstrip() in (GH_HOST + ":", f'"{GH_HOST}":', f"'{GH_HOST}':"):
            end = next((j for j in range(i + 1, len(lines)) if lines[j] and not lines[j][0].isspace()), len(lines))
            indent = min((len(l) - len(l.lstrip()) for l in lines[i + 1:end] if l.strip()), default=4)
            return i, end, indent
    return None


def parse_users(lines):
    """(active user or None, every user signed in, whether a token is written in the file)."""
    block = github_block(lines)
    if not block:
        return None, [], False
    start, end, indent = block
    active, users, in_users = None, [], False
    for line in lines[start + 1:end]:
        depth, text = len(line) - len(line.lstrip()), line.strip()
        if not text:
            continue
        if depth == indent:
            in_users = text == "users:"
            if text.startswith("user:"):
                active = text.split(":", 1)[1].strip().strip("'\"") or None
        elif in_users and text.endswith(":") and USER.fullmatch(text[:-1].strip("'\"")):
            users.append(text[:-1].strip("'\""))
    if active and active not in users:
        users.append(active)
    return active, users, any(TOKEN_LINE.match(l) for l in lines[start + 1:end])


def gh_users(folder):
    return parse_users(hosts_lines(folder))


def gh_user(folder):
    """The github.com user a folder is signed in as, or None."""
    return gh_users(folder)[0]


def with_active_user(lines, user):
    """hosts.yml lines with user signed in and active on github.com (no token is added)."""
    lines = list(lines)
    block = github_block(lines)
    if not block:
        return lines + [f"{GH_HOST}:", "    git_protocol: https", "    users:", f"        {user}:", f"    user: {user}"]
    start, end, indent = block
    pad = " " * indent
    if user not in parse_users(lines)[1]:
        at = next((i for i in range(start + 1, end) if lines[i] == pad + "users:"), None)
        new = [pad * 2 + f"{user}:"] if at is not None else [pad + "users:", pad * 2 + f"{user}:"]
        at = at + 1 if at is not None else start + 1
        lines[at:at] = new
        end += len(new)
    at = next((i for i in range(start + 1, end) if lines[i].startswith(pad + "user:")), None)
    if at is None:
        lines.insert(end, pad + f"user: {user}")
    else:
        lines[at] = pad + f"user: {user}"
    return lines


def profile_env(prof):
    """The profile's "env" from its settings files, and which file each key comes from (local wins)."""
    f = settings_files(prof)
    env, where = {}, {}
    for which in ("settings", "local"):
        data, _ = load_settings(f[which])
        for k, v in (data.get("env") if isinstance(data.get("env"), dict) else {}).items():
            env[k], where[k] = v, which
    return env, where


def used_folder(prof):
    """The folder a profile's Claude Code sessions use now: its GH_CONFIG_DIR, or the default one."""
    d = profile_env(prof)[0].get(GH_ENV)
    return os.path.expanduser(d) if isinstance(d, str) and d else gh_default_dir()


def profile_github(prof):
    folder = used_folder(prof)
    return {"user": gh_user(folder), "dir": pretty(folder)}


def shares_settings(prof):
    return not is_default(prof) and os.path.islink(settings_files(prof)["settings"])


def set_up(prof):
    """Whether the profile uses its own folder (or cannot have one: its settings.json is shared)."""
    if is_default(prof) or shares_settings(prof):
        return True
    own = own_folder(prof)
    return os.path.isdir(own) and os.path.realpath(used_folder(prof)) == os.path.realpath(own)


def known_users():
    """Users signed in in some profile's folder with their token in the keychain: any of them can
    become a profile's account without signing in again."""
    out, written = [], set()  # written: users whose token is in a hosts.yml, not in the keychain
    for p in profiles():
        _, users, insecure = gh_users(own_folder(p))
        if insecure:
            written.update(users)
        out += [u for u in users if u not in out]
    return [u for u in out if u not in written]


def copy_folder(src, dst, bk):
    """A new GitHub CLI folder with src's settings and users, and no token line."""
    bk.mkdir(os.path.dirname(dst))
    bk.created(dst)  # journaled first: restoring removes the folder with what is in it
    os.mkdir(dst, 0o700)
    lines = [l for l in hosts_lines(src) if not TOKEN_LINE.match(l)]
    if lines:
        write_text(os.path.join(dst, "hosts.yml"), "\n".join(lines) + "\n")
        os.chmod(os.path.join(dst, "hosts.yml"), 0o600)
    if os.path.isfile(os.path.join(src, "config.yml")):
        with open(os.path.join(src, "config.yml")) as f:
            write_text(os.path.join(dst, "config.yml"), f.read())


def set_env(prof, values, bk):
    """Set (or, with None, remove) keys of the profile's env: in the file that has them, else settings.json."""
    f = settings_files(prof)
    files = {which: load_settings(f[which]) for which in ("settings", "local")}
    for which, (_, err) in files.items():
        if err:
            raise ApiError(f"{os.path.basename(f[which])} has an error ({err}): fix it in the advanced editor")
    changed = set()
    for k, v in values.items():
        holders = [w for w, (d, _) in files.items() if isinstance(d.get("env"), dict) and k in d["env"]]
        targets = holders if v is None else \
            ([w for w in holders if files[w][0]["env"][k] != v] if holders else ["settings"])
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
    for w in sorted(changed):
        save_settings_file(prof, w, files[w][0], bk)


def give_own_folder(prof, bk):
    """Create the profile's folder if it is missing (signed in as the account it uses now) and point
    GH_CONFIG_DIR to it. Returns a line saying what happened, or None when there is nothing to do."""
    if set_up(prof):
        return None
    own, now = own_folder(prof), used_folder(prof)
    if not os.path.isdir(own):
        src = now if os.path.isdir(now) else gh_default_dir()
        if not os.path.isdir(src):
            return None  # the GitHub CLI was never used here: nothing to give it yet
        copy_folder(src, own, bk)
    set_env(prof, {GH_ENV: own}, bk)
    user = gh_user(own)
    return f"{prof['label']}: {pretty(own)}" + (f", GitHub as {user}" if user else ", not signed in to GitHub")


def ensure_gh_folders():
    """At every start of the server: every profile gets its own GitHub CLI folder.
    Returns (lines to print, backup path or None)."""
    todo = [p for p in profiles() if not set_up(p)]
    if not todo:
        return [], None
    bk, lines = Backup("github-folders", "A GitHub CLI folder for each profile"), []
    for p in todo:
        line = give_own_folder(p, bk)
        if line:
            lines.append(line)
            bk.note(line)
    return lines, bk.close()


def new_profile_folder(new, pid, bk):
    """For a profile being created: its own GitHub CLI folder, signed in as the default account.
    Returns a note for the message, or None."""
    if os.path.islink(os.path.join(new, "settings.json")):
        return "its settings.json is shared, so its GitHub account is the source profile's"
    own, src = os.path.join(HOME, ".config", f"gh-{pid}"), gh_default_dir()
    if not os.path.isdir(own):
        if not os.path.isdir(src):
            return None
        copy_folder(src, own, bk)
    settings = os.path.join(new, "settings.json")
    data = read_json(settings, {}) if os.path.exists(settings) else {}
    data = data if isinstance(data, dict) else {}
    data["env"] = dict(data.get("env") if isinstance(data.get("env"), dict) else {}, **{GH_ENV: own})
    write_json(settings, data)  # inside the new profile's folder: restoring removes it with the folder
    bk.note(f"{GH_ENV} = {pretty(own)}")
    user = gh_user(own)
    if not user or gh_users(src)[2]:  # the token stayed in the source's hosts.yml
        return f"sign in to GitHub for it with GH_CONFIG_DIR={pretty(own)} gh auth login"
    return f"GitHub as {user}, from {pretty(own)}: pick another account in Profiles → GitHub"


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


def github_state():
    rows = []
    for p in profiles():
        env, _ = profile_env(p)
        active, users, _ = gh_users(used_folder(p))
        rows.append({"id": p["id"], "label": p["label"], "dir": pretty(own_folder(p)), "user": active,
                     "users": users, "set_up": set_up(p), "shared": shares_settings(p), "default": is_default(p),
                     "name": env.get(GIT_ENV["name"][0], ""), "email": env.get(GIT_ENV["email"][0], "")})
    return {"gh": bool(find_tool("gh")), "git_uses_gh": git_uses_gh(), "accounts": known_users(), "profiles": rows}


def op_github_setup(pid):
    """Give a profile its own folder now (the server does it at every start)."""
    prof = profile(pid)
    if set_up(prof):
        return {"message": f"{prof['label']} already has its own GitHub CLI folder."}
    bk = Backup("github-folders", f"GitHub CLI folder of {prof['label']}")
    line = give_own_folder(prof, bk)
    if not line:
        bk.close()
        raise ApiError("The GitHub CLI was never used on this computer: sign in with gh auth login first")
    bk.note(line)
    return {"message": line + "." + session_hint(prof), "backup": bk.close()}


def op_github_account(pid, user):
    """Make user the active GitHub account of the profile's own folder."""
    prof = profile(pid)
    if shares_settings(prof):
        raise ApiError(f"{prof['label']} shares settings.json with the source profile, and so its GitHub account")
    if not set_up(prof):
        raise ApiError(f"{prof['label']} has no GitHub CLI folder of its own yet: set it up first")
    if user not in known_users():
        raise ApiError(f"{user} is not signed in to the GitHub CLI here: add the account first")
    folder = own_folder(prof)
    if gh_user(folder) == user:
        return {"message": f"{prof['label']} already uses GitHub as {user}."}
    bk = Backup("github", f"GitHub account of {prof['label']}: {user}")
    path = os.path.join(folder, "hosts.yml")
    bk.copy(path, f"hosts-{os.path.basename(folder)}.yml")
    write_text(path, "\n".join(with_active_user(hosts_lines(folder), user)) + "\n")
    os.chmod(path, 0o600)
    bk.note(f"{pretty(folder)}: active user {user}")
    note = " Your terminal uses this account too." if is_default(prof) else ""
    return {"message": f"{prof['label']} uses GitHub as {user}.{note}" + session_hint(prof), "backup": bk.close()}


def op_github_identity(pid, name, email):
    """Who the commits made in a profile are by: GIT_AUTHOR_* and GIT_COMMITTER_* in its env."""
    prof = profile(pid)
    name, email = (name or "").strip(), (email or "").strip()
    if "\n" in name or "\n" in email:
        raise ApiError("Name and email must be one line each")
    if bool(name) != bool(email):
        raise ApiError("Write both the name and the email for commits, or neither")
    if email and not EMAIL.fullmatch(email):
        raise ApiError(f"Not an email address: {email}")
    want = {k: name or None for k in GIT_ENV["name"]}
    want.update({k: email or None for k in GIT_ENV["email"]})
    env, _ = profile_env(prof)
    if all(env.get(k) == v for k, v in want.items()):
        return {"message": f"The commits of {prof['label']} already use these settings."}
    bk = Backup("github", f"Commit identity of {prof['label']}")
    set_env(prof, want, bk)
    bk.note(f"commits by {name} <{email}>" if name else "commits by the git config")
    msg = (f"Commits in {prof['label']} are by {name} <{email}>" if name else
           f"Commits in {prof['label']} use your git config") + shared_note(settings_files(prof)["settings"]) + "."
    return {"message": msg + session_hint(prof), "backup": bk.close()}
