# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: the claude.ai accounts the profiles are signed in to, and their plan's usage limits (read-only)."""

import hashlib
import json
import os
import pwd
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from .core import DATA_DIR, HOME, find_tool, profile, profiles, read_json, write_json

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
# The day's highest value of each limit, per account, for the chart in the Usage tab. Like
# update-check.json it is the app's own cache of an answer, not a Claude Code file: no backup.
HISTORY_FILE = os.path.join(DATA_DIR, "quota-history.json")
HISTORY_DAYS = 90


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
        if limits:
            record_history(key, limits)
        return res


def record_history(key, limits, now=None):
    """Keeps the day's highest value of each limit (called under _lock: one writer)."""
    now = time.time() if now is None else now
    data = read_json(HISTORY_FILE, {}) or {}
    days = data.setdefault(key, {})
    today = days.setdefault(time.strftime("%Y-%m-%d", time.localtime(now)), {})
    changed = False
    for item in limits:
        if item["percent"] > today.get(item["label"], -1):
            today[item["label"]] = item["percent"]
            changed = True
    oldest = time.strftime("%Y-%m-%d", time.localtime(now - HISTORY_DAYS * 86400))
    for day in [d for d in days if d < oldest]:
        del days[day]
        changed = True
    if changed:
        try:
            write_json(HISTORY_FILE, data)
        except OSError:
            pass  # only the chart misses a point


def quota_history():
    """The recorded days of each account, named from the profiles that use it."""
    names = {}
    for p in profiles():
        a = (read_json(p["config_abs"], {}) or {}).get("oauthAccount") or {}
        if a.get("emailAddress"):
            names[a["emailAddress"]] = a.get("fullName") or a.get("displayName") or a["emailAddress"]
        names["profile:" + p["id"]] = p["label"]
    out = []
    for key, days in sorted((read_json(HISTORY_FILE, {}) or {}).items()):
        if isinstance(days, dict) and days:
            out.append({"account": key, "name": names.get(key, key.replace("profile:", "")),
                        "days": [{"date": d, "limits": v} for d, v in sorted(days.items())]})
    return {"accounts": out}


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
# What Claude Code keeps of the account in the oauthAccount key of each profile's .claude.json:
# accountUuid, emailAddress, fullName / displayName, organizationUuid, organizationName,
# organizationRole, organizationType (claude_max, claude_pro, claude_team…), the rate limit tier
# (default_claude_max_5x…), billingType, hasExtraUsageEnabled, accountCreatedAt, subscriptionCreatedAt.
PLANS = {"claude_max": "Max", "claude_pro": "Pro", "claude_team": "Team", "claude_enterprise": "Enterprise",
         "max": "Max", "pro": "Pro", "team": "Team", "enterprise": "Enterprise"}


def plan_label(kind, tier):
    if not kind:
        return ""
    label = PLANS.get(kind, kind.replace("claude_", "").replace("_", " ").capitalize())
    m = re.search(r"_(\d+)x$", tier or "")
    return f"{label} {m.group(1)}×" if m else label


def sign_in_state(prof, email):
    tok = sign_in(prof)
    if not tok:
        return "signed_out" if email else "none"
    expires = tok.get("expiresAt")
    if isinstance(expires, (int, float)) and expires / 1000 < time.time() + 30:
        return "refresh"  # Claude Code refreshes it at the next session
    return "ok"


def list_accounts():
    """The claude.ai accounts the profiles are signed in to, each with the profiles using it,
    and the profiles signed in to none. Tokens are only looked at, never returned."""
    accounts, none = {}, []
    for p in profiles():
        a = (read_json(p["config_abs"], {}) or {}).get("oauthAccount") or {}
        email = a.get("emailAddress") or ""
        if not email:
            none.append(p["label"])
            continue
        key = (a.get("accountUuid") or email) + "/" + (a.get("organizationUuid") or "")
        acc = accounts.setdefault(key, {
            "email": email, "name": a.get("fullName") or a.get("displayName") or "",
            "organization": a.get("organizationName") or "", "role": a.get("organizationRole") or "",
            "plan": plan_label(a.get("organizationType"), a.get("organizationRateLimitTier") or a.get("userRateLimitTier")),
            "billing": a.get("billingType") or "", "extra_usage": a.get("hasExtraUsageEnabled"),
            "since": a.get("accountCreatedAt") or "", "subscribed": a.get("subscriptionCreatedAt") or "",
            "profiles": []})
        acc["profiles"].append({"id": p["id"], "label": p["label"], "sign_in": sign_in_state(p, email)})
    out = list(accounts.values())
    for acc in out:  # the quota is asked with a sign-in that works (or that Claude Code will refresh)
        usable = [x["id"] for x in acc["profiles"] if x["sign_in"] == "ok"] + \
                 [x["id"] for x in acc["profiles"] if x["sign_in"] == "refresh"]
        acc["quota_profile"] = usable[0] if usable else None
    return {"accounts": out, "not_signed_in": none}
