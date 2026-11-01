"""The plan's usage limits of each profile's account (Profiles tab), against a fake claude.ai."""
import hashlib
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import SRC

NEW = {"five_hour": {"utilization": 99.0}, "limits": [
    {"kind": "session", "percent": 58, "resets_at": "2026-11-01T19:30:00+00:00"},
    {"kind": "weekly_all", "percent": 18.4, "resets_at": "2026-11-05T16:00:00+00:00"},
    {"kind": "weekly_scoped", "percent": 0, "resets_at": None, "scope": {"model": {"display_name": "Opus"}}},
    {"kind": "something_new", "percent": 5}]}
OLD = {"five_hour": {"utilization": 91.0, "resets_at": "2026-11-01T19:30:00+00:00"},
       "seven_day": {"utilization": 40.0, "resets_at": None}, "seven_day_opus": None}
ANSWERS = {"tok-new": (200, NEW), "tok-old": (200, OLD), "tok-401": (401, {}), "tok-429": (429, {}),
           "tok-empty": (200, {"limits": []})}


@pytest.fixture
def claude_ai():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append({k.lower(): v for k, v in self.headers.items()})
            code, body = ANSWERS.get(self.headers.get("Authorization", "").replace("Bearer ", ""), (500, {}))
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/api/oauth/usage", seen
    srv.shutdown()


def signed_in(home, name, email, token=None, expires_in=3600, scopes=("user:inference", "user:profile")):
    d = home.profile(name)
    home.json(f"{d.name}/.claude.json" if name else ".claude.json", {"oauthAccount": {"emailAddress": email}} if email else {})
    if token:
        home.json(f"{d.name}/.credentials.json", {"claudeAiOauth": {
            "accessToken": token, "refreshToken": "never-sent", "expiresAt": int((time.time() + expires_in) * 1000),
            "scopes": list(scopes), "subscriptionType": "max"}})


def test_quota_of_each_profile(home, app_factory, claude_ai):
    url, seen = claude_ai
    signed_in(home, "", "me@example.com", "tok-new")
    signed_in(home, "twin", "me@example.com", "tok-new")    # the same account in a second profile
    signed_in(home, "old", "old@example.com", "tok-old")
    signed_in(home, "gone", "gone@example.com", "tok-401")
    signed_in(home, "busy", "busy@example.com", "tok-429")
    signed_in(home, "late", "late@example.com", "tok-new", expires_in=-60)
    signed_in(home, "key", "key@example.com", "tok-new", scopes=("user:inference",))
    signed_in(home, "lost", "lost@example.com")
    signed_in(home, "out", "")
    signed_in(home, "free", "free@example.com", "tok-empty")
    before = home.snapshot()
    app = app_factory(CC_PROFILES_USAGE_URL=url)
    ids = {p["dir"].split("/")[-1]: p["id"] for p in app.get("/api/profiles")}
    q = lambda name, extra="": app.get(f"/api/quota?profile={ids[name]}{extra}")

    ok = q(".claude")
    assert ok["state"] == "ok" and ok["plan"] == "max"
    assert ok["limits"] == [{"label": "5 h", "percent": 58, "resets_at": "2026-11-01T19:30:00+00:00"},
                            {"label": "Week", "percent": 18, "resets_at": "2026-11-05T16:00:00+00:00"},
                            {"label": "Week · Opus", "percent": 0, "resets_at": None}]
    assert seen[0]["authorization"] == "Bearer tok-new" and seen[0]["anthropic-beta"] == "oauth-2025-04-20"
    assert q(".claude-twin") == ok and len(seen) == 1     # one account, asked once
    assert q(".claude", "&fresh=1")["state"] == "ok" and len(seen) == 2

    assert [(x["label"], x["percent"]) for x in q(".claude-old")["limits"]] == [("5 h", 91), ("Week", 40)]
    assert q(".claude-gone") == {"state": "expired", "message": "Open Claude Code in this profile to see the quota"}
    assert q(".claude-late")["state"] == "expired" and len(seen) == 4  # expired: not even asked
    assert "try again in a few minutes" in q(".claude-busy")["message"]
    assert q(".claude-key") == {"state": "none", "message": "No plan limits for this sign-in"}
    assert q(".claude-lost")["state"] == "unknown" and "log in again" in q(".claude-lost")["message"]
    assert q(".claude-out") == {"state": "none", "message": "Not signed in"}
    assert q(".claude-free")["state"] == "none"
    assert len(seen) == 6

    # the tokens never reach the page, and nothing on disk changes
    every = json.dumps([q(n) for n in ids])
    assert "tok-" not in every and "never-sent" not in every and "refresh" not in every
    assert home.snapshot() == before


def test_quota_when_claude_ai_cannot_be_reached(home, app_factory, tmp_path):
    signed_in(home, "", "me@example.com", "tok-new")
    app = app_factory(CC_PROFILES_USAGE_URL=(tmp_path / "missing.json").as_uri())
    r = app.get("/api/quota?profile=default")
    assert r["state"] == "error" and "check the connection" in r["message"]
    assert "Unknown profile" in app.request("/api/quota?profile=nope")[1]["error"]


def test_keychain_names_follow_claude_code():
    sys.path.insert(0, str(SRC))
    from cc_profiles import quota
    d = quota.HOME + "/.claude-work"
    assert quota.keychain_services(d) == ["Claude Code-credentials-" + hashlib.sha256(d.encode()).hexdigest()[:8]]
    default = quota.keychain_services(quota.HOME + "/.claude")
    assert default[0] == "Claude Code-credentials" and len(default) == 2


def test_accounts_with_their_profiles(home, app_factory, claude_ai):
    url, seen = claude_ai
    signed_in(home, "", "me@example.com", "tok-new")
    signed_in(home, "twin", "me@example.com", "tok-new", expires_in=-60)  # Claude Code refreshes it later
    signed_in(home, "team", "me@acme.example")                          # signed out
    signed_in(home, "out", "")
    home.json(".claude.json", {"oauthAccount": {
        "accountUuid": "a1", "emailAddress": "me@example.com", "fullName": "Sam Example", "organizationUuid": "o1",
        "organizationName": "me@example.com's Organization", "organizationRole": "admin",
        "organizationType": "claude_max", "organizationRateLimitTier": "default_claude_max_20x",
        "billingType": "stripe_subscription", "hasExtraUsageEnabled": False,
        "accountCreatedAt": "2025-03-02T10:00:00Z", "subscriptionCreatedAt": "2025-03-02T10:05:00Z"}})
    home.json(".claude-twin/.claude.json", {"oauthAccount": {"accountUuid": "a1", "emailAddress": "me@example.com",
                                                            "organizationUuid": "o1"}})
    home.json(".claude-team/.claude.json", {"oauthAccount": {"accountUuid": "a1", "emailAddress": "me@acme.example",
                                                            "organizationUuid": "o2", "organizationName": "Acme",
                                                            "organizationType": "claude_team"}})
    before = home.snapshot()
    app = app_factory(CC_PROFILES_USAGE_URL=url)
    r = app.get("/api/accounts")
    ids = {p["dir"].split("/")[-1]: p["id"] for p in app.get("/api/profiles")}
    assert r["not_signed_in"] == ["Out"]
    me, team = r["accounts"]
    assert {k: me[k] for k in ("email", "name", "plan", "role", "billing", "extra_usage", "since")} == {
        "email": "me@example.com", "name": "Sam Example", "plan": "Max 20×", "role": "admin",
        "billing": "stripe_subscription", "extra_usage": False, "since": "2025-03-02T10:00:00Z"}
    assert [(p["id"], p["sign_in"]) for p in me["profiles"]] == [(ids[".claude"], "ok"), (ids[".claude-twin"], "refresh")]
    assert me["quota_profile"] == ids[".claude"]
    assert team["plan"] == "Team" and team["organization"] == "Acme"  # same person, another organization
    assert team["profiles"][0]["sign_in"] == "signed_out" and team["quota_profile"] is None
    assert "tok-" not in json.dumps(r) and seen == []  # listing asks claude.ai nothing
    assert home.snapshot() == before
