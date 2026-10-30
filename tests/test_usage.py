"""Usage: tokens and estimated cost per day, project, model and profile.

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import csv
import io
import json
import time
import urllib.request

import pytest

from conftest import san
from helpers import basic_home


# --- usage ----------------------------------------------------------------------


def reply_line(mid, days_ago, model="claude-sonnet-5-5", inp=0, out=0, cw=0, cr=0, req="req-1", **extra):
    """An assistant line with the usage Claude Code records on every reply."""
    t = time.time() - days_ago * 86400
    usage = {"input_tokens": inp, "output_tokens": out, "cache_creation_input_tokens": cw,
             "cache_read_input_tokens": cr, **extra}
    return json.dumps({"type": "assistant", "requestId": req,
                       "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.123Z", time.gmtime(t)),
                       "message": {"id": mid, "model": model, "role": "assistant",
                                   "content": [{"type": "text", "text": "ok"}], "usage": usage}},
                      separators=(",", ":"))


def add_lines(home, profile, project, session, lines):
    d = home.conversation(profile, project, session) if not (home.profile(profile) / "projects" / san(home.path(project)) / f"{session}.jsonl").exists() \
        else home.profile(profile) / "projects" / san(home.path(project))
    with open(d / f"{session}.jsonl", "a") as f:
        f.write("\n".join(lines) + "\n")
    return d


M = 1_000_000


def test_usage_is_counted_once_per_reply_and_priced(home, app_factory):
    basic_home(home)
    big = reply_line("msg-a", 0.01, inp=M, out=M, cw=M, cr=M)  # sonnet 5.5: 2 + 10 + 2.50 + 0.20 = $14.70
    add_lines(home, "", "code/work/api", "s-use", [
        big, big,  # Claude Code writes one line per content block of the same reply
        reply_line("msg-a", 0.01, inp=M, out=10, cw=M, cr=M),  # a mid-stream line: the one with more output wins
        "{not json", '{"type":"assistant","message":"odd"}',  # broken lines are skipped
        reply_line("msg-b", 0.01, model="<synthetic>", inp=100, out=50),  # no list price: tokens, no cost
        reply_line("msg-c", 3, model="claude-haiku-4-5", out=M),  # $5
        reply_line("msg-d", 40, model="claude-opus-5-5", out=M),  # $20, outside 30 days
        reply_line("msg-e", 0.01, model="claude-sonnet-5-5", cw=M,  # written for 1 hour: 2 × input
                   cache_creation={"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": M}),
        reply_line("msg-f", 0.02, req="req-2", model="claude-opus-4-1", inp=M),  # $15; same id as below, other request
    ])
    add_lines(home, "", "code/personal/blog", "s-use2", [reply_line("msg-f", 0.02, req="req-3", model="claude-opus-4-1", inp=M)])
    # a resumed conversation copies earlier replies into its own file; a moved one can sit in two profiles
    add_lines(home, "work", "code/work/api", "s-use-work", [big, reply_line("msg-w", 1, model="claude-opus-4-8", out=M)])
    app = app_factory()
    before = home.snapshot()

    r = app.get("/api/usage?profile=all&days=30")
    t = r["totals"]
    assert t["replies"] == 7  # a, b, c, e, f twice (two requests), w
    assert (t["input"], t["output"], t["cache_write"], t["cache_read"]) == (3 * M + 100, 3 * M + 50, 2 * M, M)
    assert t["cost"] == pytest.approx(14.70 + 5 + 4 + 15 + 15 + 25)
    assert t["unpriced_tokens"] == 150 and t["cache_read_share"] == pytest.approx(M / (6 * M + 100), abs=1e-4)
    assert len(r["daily"]) == 30 and r["daily"][-1]["date"] == time.strftime("%Y-%m-%d")
    assert r["start"] == r["daily"][0]["date"] and r["end"] == r["daily"][-1]["date"]
    assert sum(d["replies"] for d in r["daily"]) == 7 and sum(1 for d in r["daily"] if d["tokens"]) <= 4
    assert all(d["tokens"] == 0 and d["cost"] == 0 for d in r["daily"][:-5])  # every day is there, zeros included
    models = {m["model"]: m for m in r["models"]}
    assert models["<synthetic>"]["family"] is None and models["<synthetic>"]["unpriced_tokens"] == 150
    assert models["claude-haiku-4-5"]["cost"] == 5 and models["claude-opus-4-8"]["family"] == "Opus 4.5–5"
    assert {p["id"]: p["replies"] for p in r["profiles"]} == {"default": 6, "work": 1}
    projects = {(p["profile"], p["pretty"]): p["replies"] for p in r["projects"]}
    assert projects == {("default", "~/code/work/api"): 5, ("default", "~/code/personal/blog"): 1, ("work", "~/code/work/api"): 1}
    assert r["projects_count"] == 3 and r["prices_checked"] and r["currency"] == "USD"

    work = app.get("/api/usage?profile=work&days=7")  # alone, work counts its copy of msg-a
    assert work["totals"]["replies"] == 2 and "profiles" not in work and len(work["daily"]) == 7
    assert work["totals"]["cost"] == pytest.approx(14.70 + 25)
    assert app.get("/api/usage?profile=default&days=90")["totals"]["replies"] == 7  # msg-d is 40 days old
    assert app.get("/api/usage")["days"] == 30  # all profiles, 30 days by default
    assert home.snapshot() == before  # read-only
    assert not home.path(".cc-profiles/backups").exists() or not any(home.path(".cc-profiles/backups").iterdir())

    # a new reply is read on the next request: the cache follows the file
    add_lines(home, "work", "code/work/api", "s-use-work", [reply_line("msg-new", 0, model="claude-haiku-4-5", inp=10)])
    assert app.get("/api/usage?profile=work&days=7")["totals"]["replies"] == 3


def test_usage_counts_subagent_conversations(home, app_factory):
    basic_home(home)
    d = add_lines(home, "", "code/work/api", "s-main", [reply_line("m-main", 0.01, out=10)])
    sub = d / "s-main" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.jsonl").write_text(reply_line("m-sub", 0.01, out=20) + "\n")
    app = app_factory()
    assert app.get("/api/usage?profile=default&days=7")["totals"]["output"] == 30


def test_usage_rejects_bad_parameters(home, app_factory):
    basic_home(home)
    app = app_factory()
    for q in ("days=10", "days=abc", "days=030", "days=-7", "days=7.0"):
        status, data = app.request("/api/usage?profile=all&" + q)
        assert status == 400 and "Pick 7, 14, 30 or 90 days" in data["error"], q
    status, data = app.request("/api/usage?profile=nope&days=7")
    assert status == 400 and "Unknown profile" in data["error"]
    r = app.get("/api/usage?profile=default&days=90")
    assert r["totals"]["replies"] == 0 and len(r["daily"]) == 90 and r["models"] == [] and r["projects"] == []


def test_usage_csv_has_one_row_per_day_and_model(home, app_factory):
    basic_home(home)
    add_lines(home, "", "code/work/api", "s-csv", [
        reply_line("c-1", 0.01, inp=M, out=M),                      # sonnet 5.5: $12
        reply_line("c-2", 0.01, req="r2", inp=10, out=20, cw=30, cr=40),
        reply_line("c-3", 0.01, model="claude-haiku-4-5", out=M),   # $5
        reply_line("c-4", 2, out=M),                                # $10, two days ago
        reply_line("c-5", 0.01, model="=cmd|' /C calc'!A0", inp=7),  # no list price, not a formula
        reply_line("c-6", 40, out=M),                               # outside 30 days
    ])
    app = app_factory()
    before = home.snapshot()
    req = urllib.request.Request(app.base + "/api/usage.csv?profile=default&days=30", headers={"X-Token": app.token})
    with urllib.request.urlopen(req, timeout=30) as r:
        assert r.headers["Content-Type"] == "text/csv; charset=utf-8"
        assert r.headers["Content-Disposition"] == 'attachment; filename="cc-profiles-usage-default-30d.csv"'
        rows = list(csv.reader(io.StringIO(r.read().decode("utf-8"))))
    assert rows[0] == ["date", "model", "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens",
                       "replies", "estimated_cost_usd"]
    # the days of the replies themselves (0.01 and 2 days ago): right after midnight "0.01 days ago" is yesterday
    today, two_ago = (time.strftime("%Y-%m-%d", time.localtime(time.time() - d * 86400)) for d in (0.01, 2))
    body = {(x[0], x[1]): x[2:] for x in rows[1:]}
    assert len(rows) == 5 and [x[0] for x in rows[1:]] == sorted(x[0] for x in rows[1:])  # oldest first
    assert body[(two_ago, "claude-sonnet-5-5")] == ["0", str(M), "0", "0", "1", "10.0000"]
    sonnet = body[(today, "claude-sonnet-5-5")]
    assert sonnet[:5] == [str(M + 10), str(M + 20), "30", "40", "2"] and float(sonnet[5]) == pytest.approx(12, abs=0.001)
    assert body[(today, "claude-haiku-4-5")] == ["0", str(M), "0", "0", "1", "5.0000"]
    assert body[(today, "'=cmd|' /C calc'!A0")] == ["7", "0", "0", "0", "1", ""]  # no price: no cost
    # the same validation as /api/usage, and the token guard
    assert app.request("/api/usage.csv?profile=default&days=10")[0] == 400
    assert app.request("/api/usage.csv?profile=nope&days=7")[0] == 400
    assert app.request("/api/usage.csv?profile=all&days=7", token=False)[0] == 403
    req = urllib.request.Request(app.base + "/api/usage.csv?days=7", headers={"X-Token": app.token})
    with urllib.request.urlopen(req, timeout=30) as r:
        assert 'filename="cc-profiles-usage-all-7d.csv"' in r.headers["Content-Disposition"]
    assert home.snapshot() == before


def test_usage_lists_the_most_expensive_sessions(home, app_factory):
    basic_home(home)
    p = home.profile("") / "projects" / san(home.path("code/work/api"))
    add_lines(home, "", "code/work/api", "s-cheap", [reply_line("e-1", 0.01, model="claude-haiku-4-5", out=1000)])
    (p / "s-cheap.jsonl").write_text(json.dumps({"type": "user", "message": {"content": "a cheap question"},
                                                 "timestamp": "2026-01-01T00:00:00Z"}) + "\n"
                                     + (p / "s-cheap.jsonl").read_text())
    add_lines(home, "", "code/work/api", "s-dear", [reply_line("e-2", 1, model="claude-opus-4-1", out=M)])  # $75
    sub = p / "s-dear" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.jsonl").write_text(reply_line("e-3", 1, model="claude-opus-4-1", inp=M) + "\n")  # +$15, same session
    add_lines(home, "work", "code/work/api", "s-mid", [reply_line("e-4", 0.5, out=M)])  # sonnet 5.5: $10
    add_lines(home, "", "code/personal/blog", "s-free", [reply_line("e-5", 0.01, model="<synthetic>", out=M)])
    add_lines(home, "", "code/personal/blog", "s-old", [reply_line("e-6", 50, model="claude-opus-4-1", out=M)])
    for i in range(12):  # more than 10 sessions: only the top 10 are listed
        add_lines(home, "", "code/personal/blog", f"s-many-{i}",
                  [reply_line(f"m-{i}", 0.01, model="claude-haiku-4-5", out=10 + i)])
    app = app_factory()
    r = app.get("/api/usage?profile=all&days=30")
    s = r["sessions"]
    assert len(s) == 10
    assert [x["session"] for x in s[:3]] == ["s-dear", "s-mid", "s-cheap"]
    dear = s[0]
    assert dear["cost"] == pytest.approx(90) and dear["replies"] == 2 and dear["tokens"] == 2 * M
    assert dear["profile"] == "default" and dear["project"] == san(home.path("code/work/api"))
    assert dear["pretty"] == "~/code/work/api" and dear["exists"] is True
    assert dear["date"] == time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    assert s[2]["title"] == "a cheap question"  # the first prompt, like the Conversations tab
    assert s[1]["profile"] == "work"
    assert "s-old" not in [x["session"] for x in s]  # outside the period
    # a cheap session costs more than none: s-free (no list price, many tokens) comes after the priced ones
    assert [x["session"] for x in s[3:]] == [f"s-many-{i}" for i in range(11, 4, -1)]
    assert [x["session"] for x in app.get("/api/usage?profile=work&days=7")["sessions"]] == ["s-mid"]
