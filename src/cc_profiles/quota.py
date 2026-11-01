# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: the plan's usage limits of the claude.ai account signed in to a profile (read-only)."""

import hashlib
import json
import os
import pwd
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from .core import HOME, find_tool, profile, read_json

# ---------------------------------------------------------------------------
# Where Claude Code keeps the sign-in
# ---------------------------------------------------------------------------
# On macOS in the login keychain, under the user's name, as "Claude Code-credentials"
# for ~/.claude used without CLAUDE_CONFIG_DIR and "Claude Code-credentials-<first 8 hex
# of sha256(CLAUDE_CONFIG_DIR)>" for any other folder; elsewhere (or when the keychain
# is unavailable) in <dir>/.credentials.json. Both hold {"claudeAiOauth": {accessToken,
# expiresAt (ms), scopes, subscriptionType, …}}.
#
# The token is read only to ask for the usage, the way Claude Code's /usage does: it is
# never stored, sent to the page or refreshed. Refreshing would replace the refresh token
# Claude Code holds and could sign the profile out, so an expired token gets a message
# instead: the next Claude Code session in the profile refreshes it.
USAGE_URL = os.environ.get("CC_PROFILES_USAGE_URL", "https://api.anthropic.com/api/oauth/usage")
CACHE_SECONDS = 300
_cache = {}
_lock = threading.Lock()  # one request at a time: two profiles on one account ask once


def keychain_services(dir_abs):
    named = "Claude Code-credentials-" + hashlib.sha256(dir_abs.encode()).hexdigest()[:8]
    if dir_abs.rstrip("/") == os.path.join(HOME, ".claude"):
        return ["Claude Code-credentials", named]
    return [named]


def real_home():
    try:
        return pwd.getpwuid(os.getuid()).pw_dir
    except KeyError:
        return None


def keychain_token(dir_abs):
    # The keychain belongs to the user, not to $HOME: a sandbox home would read the
    # real Default profile's sign-in, so it is asked only on the real home.
    security = find_tool("security")
    if sys.platform != "darwin" or not security or os.path.realpath(HOME) != os.path.realpath(real_home() or ""):
        return None
    user = os.environ.get("USER") or pwd.getpwuid(os.getuid()).pw_name
    for service in keychain_services(dir_abs):
        try:
            r = subprocess.run([security, "find-generic-password", "-a", user, "-w", "-s", service],
                               capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode == 0 and r.stdout.strip():
            try:
                return json.loads(r.stdout.strip()).get("claudeAiOauth")
            except (ValueError, AttributeError):
                return None
    return None


def sign_in(prof):
    tok = keychain_token(prof["dir_abs"])
    if tok is None:
        tok = (read_json(os.path.join(prof["dir_abs"], ".credentials.json"), {}) or {}).get("claudeAiOauth")
    return tok if isinstance(tok, dict) and tok.get("accessToken") else None


# ---------------------------------------------------------------------------
# The usage
# ---------------------------------------------------------------------------
def limit_label(item):
    kind = item.get("kind")
    if kind == "session":
        return "5 h"
    if kind == "weekly_all":
        return "Week"
    scope = item.get("scope") or {}
    name = ((scope.get("model") or {}).get("display_name") or (scope.get("surface") or {}).get("display_name"))
    return f"Week · {name}" if name else None


def parse_limits(data):
    """The limits to show, from the answer of /api/oauth/usage: its `limits` list, or
    the older five_hour / seven_day fields when it has none."""
    out = []
    for item in data.get("limits") or []:
        label = limit_label(item) if isinstance(item, dict) else None
        if label and isinstance(item.get("percent"), (int, float)):
            out.append({"label": label, "percent": round(item["percent"]), "resets_at": item.get("resets_at")})
    if out:
        return out
    for key, label in (("five_hour", "5 h"), ("seven_day", "Week"), ("seven_day_opus", "Week · Opus"),
                       ("seven_day_sonnet", "Week · Sonnet")):
        item = data.get(key)
        if isinstance(item, dict) and isinstance(item.get("utilization"), (int, float)):
            out.append({"label": label, "percent": round(item["utilization"]), "resets_at": item.get("resets_at")})
    return out


def fetch_usage(token):
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": "Bearer " + token, "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def quota(pid, fresh=False):
    prof = profile(pid)
    cfg = read_json(prof["config_abs"], {}) or {}
    email = (cfg.get("oauthAccount") or {}).get("emailAddress", "")
    tok = sign_in(prof)
    if not tok:
        if email:
            return {"state": "unknown", "message": "Sign-in not found: log in again in this profile to see the quota"}
        return {"state": "none", "message": "Not signed in"}
    if "user:profile" not in (tok.get("scopes") or []):
        return {"state": "none", "message": "No plan limits for this sign-in"}
    expires = tok.get("expiresAt")
    if isinstance(expires, (int, float)) and expires / 1000 < time.time() + 30:
        return {"state": "expired", "message": "Open Claude Code in this profile to see the quota"}
    key = email or "profile:" + pid  # one account in two profiles: asked once
    with _lock:
        hit = _cache.get(key)
        if not fresh and hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        try:
            data = fetch_usage(tok["accessToken"])
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return {"state": "expired", "message": "Open Claude Code in this profile to see the quota"}
            if e.code == 429:
                return {"state": "error", "message": "Claude.ai asked to wait: try again in a few minutes"}
            return {"state": "error", "message": f"Claude.ai answered {e.code}: try again later"}
        except (OSError, ValueError) as e:
            return {"state": "error", "message": f"Could not reach claude.ai ({e.__class__.__name__}): check the connection"}
        limits = parse_limits(data if isinstance(data, dict) else {})
        res = ({"state": "ok", "limits": limits, "plan": tok.get("subscriptionType") or "", "checked": time.time()}
               if limits else {"state": "none", "message": "No plan limits for this account"})
        _cache[key] = (time.time(), res)
        return res
