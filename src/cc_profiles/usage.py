# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: token usage and estimated cost, read from the conversations (read-only)."""

import calendar
import csv
import datetime
import io
import json
import os
import re
import time

from .core import ApiError, cached_read, pretty, profile, profiles
from .paths import path_index, project_folders
from .conversations import conversation_summary

# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
# Anthropic's list prices in USD per million tokens, checked on 2026-10-06 against
# https://platform.claude.com/docs/en/about-claude/pricing. They are
# estimates: subscription plans (Pro, Max, Team) are not billed per token, and cloud
# providers have their own prices. Cache write is the 5-minute price (1.25 × input);
# writes Claude Code reports as 1-hour ones count at 2 × input. The first pattern that
# matches the model id wins; a model that matches none counts tokens but no cost.
PRICES_CHECKED = "2026-10-06"
PRICES = [
    # (pattern, family, input, output, cache write, cache read)
    (r"opus-5-5", "Opus 5.5", 4.00, 20.00, 5.00, 0.20),
    (r"opus-(5|4-[5-9])", "Opus 4.5–5", 5.00, 25.00, 6.25, 0.50),
    (r"opus", "Opus 4.1 and older", 15.00, 75.00, 18.75, 1.50),
    (r"sonnet-5", "Sonnet 5", 2.00, 10.00, 2.50, 0.20),
    (r"sonnet", "Sonnet 4.6 and older", 3.00, 15.00, 3.75, 0.30),
    (r"haiku-4", "Haiku 4.5", 1.00, 5.00, 1.25, 0.10),
    (r"3-5-haiku|haiku-3-5", "Haiku 3.5", 0.80, 4.00, 1.00, 0.08),
    (r"haiku", "Haiku 3", 0.25, 1.25, 0.30, 0.03),
    (r"(fable|mythos)-5-[1-9]", "Fable / Mythos 5.1", 10.00, 50.00, 12.50, 0.25),
    (r"fable|mythos", "Fable / Mythos 5", 10.00, 50.00, 12.50, 1.00),
]
_PRICE_RE = [(re.compile(p), fam, prices) for p, fam, *prices in PRICES]
_price_memo = {}

DAY_CHOICES = (7, 30, 90, 365)
TOP_PROJECTS = 10
TOP_SESSIONS = 10


def price_of(model):
    """(family, (input, output, cache write, cache read)) for a model id, or (None, None)."""
    if model not in _price_memo:
        hit = (None, None)
        m = (model or "").lower()
        if m.startswith("claude"):
            for rx, fam, prices in _PRICE_RE:
                if rx.search(m):
                    hit = (fam, tuple(prices))
                    break
        _price_memo[model] = hit
    return _price_memo[model]


def reply_cost(model, inp, out, cw5, cw1h, cr):
    _, p = price_of(model)
    if p is None:
        return None
    return (inp * p[0] + out * p[1] + cw5 * p[2] + cw1h * p[0] * 2 + cr * p[3]) / 1e6


# ---------------------------------------------------------------------------
# Reading the conversations
# ---------------------------------------------------------------------------
_TS = re.compile(r"(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:\.\d+)?(Z|[+-]\d\d:?\d\d)?$")


def parse_ts(ts):
    """Seconds since the epoch of an ISO timestamp (UTC when it has no offset), or None."""
    m = _TS.match(ts or "") if isinstance(ts, str) else None
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups()[:6])
    try:
        t = calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0))
    except (ValueError, OverflowError):
        return None
    off = m.group(7)
    if off and off != "Z":
        sign = 1 if off[0] == "+" else -1
        off = off[1:].replace(":", "")
        t -= sign * (int(off[:2]) * 3600 + int(off[2:]) * 60)
    return t


def _num(v):
    return v if isinstance(v, int) and v > 0 else 0


def _read_usage(path):
    """One record per reply in a conversation file: (key, time, model, input, output,
    cache write 5 min, cache write 1 h, cache read). Claude Code writes a line per content
    block of a reply, all with the same message id: they count once (the line with the
    most output tokens, in case the first ones were written mid-stream)."""
    found = {}
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line or '"assistant"' not in line:
                    continue
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(j, dict) or j.get("type") != "assistant":
                    continue
                msg = j.get("message")
                u = msg.get("usage") if isinstance(msg, dict) else None
                t = parse_ts(j.get("timestamp"))
                if not isinstance(u, dict) or t is None:
                    continue
                mid = msg.get("id")
                key = f"{mid}:{j.get('requestId') or ''}" if mid else f"{path}:{j.get('uuid') or len(found)}"
                cw = _num(u.get("cache_creation_input_tokens"))
                split = u.get("cache_creation")
                cw1h = min(cw, _num(split.get("ephemeral_1h_input_tokens"))) if isinstance(split, dict) else 0
                model = msg.get("model") if isinstance(msg.get("model"), str) else ""
                rec = (key, t, model, _num(u.get("input_tokens")), _num(u.get("output_tokens")),
                       cw - cw1h, cw1h, _num(u.get("cache_read_input_tokens")))
                old = found.get(key)
                if old is None or rec[4] > old[4]:
                    found[key] = rec
    except OSError:
        return ()
    return tuple(found.values())


def _subdirs(d):
    try:
        return tuple(sorted(e.name for e in os.scandir(d) if e.is_dir() and not e.name.startswith(".")))
    except OSError:
        return ()


def _jsonl_names(d):
    try:
        return tuple(sorted(f for f in os.listdir(d) if f.endswith(".jsonl") and not f.startswith(".")))
    except OSError:
        return ()


def conversation_files(d, convs):
    """The conversations of a project folder, plus the subagent conversations Claude Code
    keeps in <session>/subagents/. Listings are cached on each folder's stat."""
    files = [os.path.join(d, f) for f in sorted(convs)]
    for s in cached_read("usage-subdirs", d, _subdirs):
        sub = os.path.join(d, s, "subagents")
        if os.path.isdir(sub):
            files += [os.path.join(sub, f) for f in cached_read("usage-subagents", sub, _jsonl_names)]
    return files


def warm_usage():
    """Read every conversation once, so the Usage tab opens fast."""
    for p in profiles():
        for _, d, convs in project_folders(p):
            for f in conversation_files(d, convs):
                cached_read("usage", f, _read_usage)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def _zero():
    return {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "tokens": 0, "replies": 0,
            "cost": 0.0, "unpriced_tokens": 0}


def _add(acc, inp, out, cw, cr, cost):
    acc["input"] += inp
    acc["output"] += out
    acc["cache_write"] += cw
    acc["cache_read"] += cr
    n = inp + out + cw + cr
    acc["tokens"] += n
    acc["replies"] += 1
    if cost is None:
        acc["unpriced_tokens"] += n
    else:
        acc["cost"] += cost


def _done(acc):
    acc["cost"] = round(acc["cost"], 4)
    return acc


def session_of(f):
    """The conversation a file belongs to: a subagent's file counts for its parent."""
    parent = os.path.dirname(f)
    if os.path.basename(parent) == "subagents":
        return os.path.basename(os.path.dirname(parent))
    return os.path.basename(f)[:-len(".jsonl")]


def _title(f):
    try:
        return cached_read("usage-title", f, conversation_summary)["title"]
    except OSError:
        return ""


def _collect(pid, days):
    """Every reply in the period, added up per day, model, project, profile, conversation
    and day + model. Read-only."""
    pid = pid or "all"
    try:
        n_days = int(days)
    except (TypeError, ValueError):
        n_days = 0
    if n_days not in DAY_CHOICES or str(days).strip() != str(n_days):
        raise ApiError(f"Invalid period: {days}. Pick 7, 30, 90 or 365 days.")
    profs = profiles() if pid == "all" else [profile(pid)]

    today = datetime.date.today()
    first = today - datetime.timedelta(days=n_days - 1)
    start = time.mktime(first.timetuple())
    dates = [(first + datetime.timedelta(days=i)).isoformat() for i in range(n_days)]
    daily = {d: _zero() for d in dates}
    totals, by_model, by_project, by_profile = _zero(), {}, {}, {}
    by_session, by_day_model = {}, {}
    seen = set()  # a reply copied into a resumed or moved conversation counts once
    idx = None
    for p in profs:
        pacc = by_profile.setdefault(p["id"], dict(_zero(), id=p["id"], label=p["label"]))
        for name, d, convs in project_folders(p):
            for f in conversation_files(d, convs):
                for key, t, model, inp, out, cw5, cw1h, cr in cached_read("usage", f, _read_usage):
                    if t < start or key in seen:
                        continue
                    seen.add(key)
                    day = time.strftime("%Y-%m-%d", time.localtime(t))
                    if day not in daily:  # in the future: a clock that was wrong
                        continue
                    cost = reply_cost(model, inp, out, cw5, cw1h, cr)
                    cw = cw5 + cw1h
                    for acc in (totals, daily[day], pacc):
                        _add(acc, inp, out, cw, cr, cost)
                    m = by_model.get(model)
                    if m is None:
                        m = by_model[model] = dict(_zero(), model=model or "unknown", family=price_of(model)[0])
                    _add(m, inp, out, cw, cr, cost)
                    pr = by_project.get((p["id"], name))
                    if pr is None:
                        if idx is None:
                            idx = path_index()
                        pr = by_project[(p["id"], name)] = dict(_zero(), profile=p["id"], name=name,
                                                                pretty=pretty(idx.get(name)) or name)
                    _add(pr, inp, out, cw, cr, cost)
                    sid = session_of(f)
                    se = by_session.get((p["id"], name, sid))
                    if se is None:
                        se = by_session[(p["id"], name, sid)] = dict(_zero(), profile=p["id"], project=name,
                                                                    pretty=pr["pretty"], session=sid, last=t)
                    se["last"] = max(se["last"], t)
                    _add(se, inp, out, cw, cr, cost)
                    dm = by_day_model.get((day, model))
                    if dm is None:
                        dm = by_day_model[(day, model)] = dict(_zero(), date=day, model=model or "unknown")
                    _add(dm, inp, out, cw, cr, cost)
    return {"profile": pid, "profiles": profs, "days": n_days, "dates": dates, "daily": daily, "totals": totals,
            "models": by_model, "projects": by_project, "by_profile": by_profile, "sessions": by_session,
            "day_model": by_day_model}


def top_sessions(by_session, profs):
    """The conversations that cost the most in the period (then the most tokens), with
    their title like the Conversations tab."""
    dirs = {p["id"]: p["dir_abs"] for p in profs}
    top = sorted(by_session.values(), key=lambda x: (-x["cost"], -x["tokens"], -x["last"], x["session"]))[:TOP_SESSIONS]
    for s in top:
        f = os.path.join(dirs[s["profile"]], "projects", s["project"], s["session"] + ".jsonl")
        s["title"] = _title(f) if os.path.isfile(f) else ""
        s["exists"] = os.path.isfile(f)
        s["date"] = time.strftime("%Y-%m-%d", time.localtime(s["last"]))
        _done(s)
    return top


def usage(pid="all", days="30"):
    """Tokens and estimated cost per day, project, model, profile and conversation, for
    the last `days` days (today included, local time). Read-only: it never writes anything."""
    col = _collect(pid, days)
    pid, n_days, dates, daily, totals = col["profile"], col["days"], col["dates"], col["daily"], col["totals"]
    profs, by_model, by_project, by_profile = col["profiles"], col["models"], col["projects"], col["by_profile"]
    in_side = totals["input"] + totals["cache_write"] + totals["cache_read"]
    projects = sorted(by_project.values(), key=lambda x: (-x["tokens"], x["pretty"]))
    out = {
        "profile": pid, "days": n_days, "start": dates[0], "end": dates[-1],
        "currency": "USD", "prices_checked": PRICES_CHECKED,
        "prices": [{"family": fam, "input": a, "output": b, "cache_write": c, "cache_read": r}
                   for _, fam, a, b, c, r in PRICES],
        "totals": dict(_done(totals), cache_read_share=round(totals["cache_read"] / in_side, 4) if in_side else 0.0),
        "daily": [dict(_done(daily[d]), date=d) for d in dates],
        "projects": [_done(x) for x in projects[:TOP_PROJECTS]],
        "projects_count": len(projects),
        "models": [_done(x) for x in sorted(by_model.values(), key=lambda x: (-x["tokens"], x["model"]))],
        "sessions": top_sessions(col["sessions"], profs),
    }
    if pid == "all":
        out["profiles"] = [_done(by_profile[p["id"]]) for p in profs]
    return out


CSV_COLUMNS = ["date", "model", "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens",
               "replies", "estimated_cost_usd"]


def _cell(v):
    """A text cell a spreadsheet will not run as a formula."""
    v = str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def usage_csv(pid="all", days="30"):
    """(bytes, file name): one row per day per model with replies in the period, oldest
    first. The cost is empty for a model without a list price. Read-only."""
    c = _collect(pid, days)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for (day, _), r in sorted(c["day_model"].items(), key=lambda kv: (kv[0][0], kv[1]["model"])):
        priced = r["unpriced_tokens"] < r["tokens"] or not r["tokens"]
        w.writerow([day, _cell(r["model"]), r["input"], r["output"], r["cache_write"], r["cache_read"],
                    r["replies"], f"{r['cost']:.4f}" if priced else ""])
    return buf.getvalue().encode("utf-8"), f"cc-profiles-usage-{c['profile']}-{c['days']}d.csv"
