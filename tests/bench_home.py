"""Benchmark: how fast the UI's tabs open on a large home.

Builds a synthetic home (4 profiles, 2,000 projects, 20,000 conversations, a few of
50 MB, 5,000 memories, 300 skills, a 100,000-line prompt history, 2,000 backups),
starts a real server on it and times every GET request the UI makes when a tab opens.
Not part of the test suite: run it by hand.

    .venv/bin/python tests/bench_home.py [folder] [seconds]

folder defaults to /tmp/cc-profiles-bench; seconds (default 0) is how long to wait after
the server starts, to time the tabs once its background warm-up is done.

The home is built once and reused while the folder exists (delete it to rebuild).
"""
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import App, FakeHome, san  # noqa: E402

PROFILES = ["", "work", "client", "lab"]
N_PROJECTS, N_CONV, N_MEM, N_SKILLS, N_HISTORY, N_BACKUPS = 2000, 20000, 5000, 300, 100000, 2000
BIG = 3  # conversations of about 50 MB


def pdir(name):
    return ".claude" if not name else f".claude-{name}"


def build(root):
    rnd = random.Random(7)
    home = FakeHome(root)
    for p in PROFILES:
        home.profile(p)
    projects = [f"code/{['work', 'personal', 'client', 'lab'][i % 4]}/p{i:04d}" for i in range(N_PROJECTS)]
    owner = {pr: PROFILES[i % 4] for i, pr in enumerate(projects)}
    for i, pr in enumerate(projects):
        if i % 20 != 0:  # one project in 20 has lost its folder
            home.path(pr).mkdir(parents=True, exist_ok=True)
    # conversations: spread over projects, most small, a few huge
    line = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 400}]}},
                      separators=(",", ":"))
    for c in range(N_CONV):
        pr = projects[c % N_PROJECTS]
        prof = owner[pr] if c % 7 else PROFILES[(PROFILES.index(owner[pr]) + 1) % 4]  # some in a 2nd profile
        d = home.path(f"{pdir(prof)}/projects/{san(str(home.path(pr)))}")
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"s{c:05d}.jsonl"
        head = [json.dumps({"type": "user", "cwd": str(home.path(pr)), "timestamp": "2026-10-01T09:00:00Z",
                            "message": {"role": "user", "content": f"prompt {c}"}}, separators=(",", ":"))]
        with open(f, "w") as fh:
            fh.write("\n".join(head + [line] * rnd.randint(5, 40)) + "\n")
            if c < BIG:
                chunk = (line + "\n") * 1000
                for _ in range(50 * 1024 * 1024 // len(chunk)):
                    fh.write(chunk)
        fhist = home.path(f"{pdir(prof)}/file-history/s{c:05d}")
        fhist.mkdir(parents=True, exist_ok=True)
        (fhist / "snapshot").write_text("x")
    # memories
    for m in range(N_MEM):
        pr = projects[(m * 3) % N_PROJECTS]
        md = home.path(f"{pdir(owner[pr])}/projects/{san(str(home.path(pr)))}/memory")
        md.mkdir(parents=True, exist_ok=True)
        (md / f"m{m:04d}.md").write_text(f"---\nname: m{m:04d}\ndescription: memory number {m}\n---\nbody {m}\n")
        with open(md / "MEMORY.md", "a") as idx:
            idx.write(f"- [m{m:04d}](m{m:04d}.md) — memory number {m}\n")
    # skills
    for s in range(N_SKILLS):
        sd = home.path(f"{pdir(PROFILES[s % 3])}/skills/skill-{s:03d}")
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "SKILL.md").write_text(f"---\nname: skill-{s:03d}\ndescription: does task {s}\n---\nSteps for {s}.\n")
    # prompt history and per-project settings
    with open(home.path(".claude/history.jsonl"), "w") as fh:
        for h in range(N_HISTORY):
            fh.write(json.dumps({"display": f"prompt {h}", "timestamp": h,
                                 "project": str(home.path(projects[h % N_PROJECTS]))}) + "\n")
    for p in PROFILES:
        cfg = {"projects": {str(home.path(pr)): {"allowedTools": []} for pr in projects if owner[pr] == p}}
        if not p:
            cfg["oauthAccount"] = {"emailAddress": "me@example.com"}
        home.json(f"{pdir(p)}/.claude.json" if p else ".claude.json", cfg)
    # backups
    bdir = home.path(".cc-profiles/backups")
    for b in range(N_BACKUPS):
        d = bdir / f"2026-09-{1 + b % 28:02d}_10-{b // 60 % 60:02d}-{b % 60:02d}_op-{b}"
        (d / "file").mkdir(parents=True)
        (d / "file" / "001-x").write_text("x" * 2000)
        (d / "manifest.json").write_text(json.dumps({"title": f"Operation {b}", "created": 1790000000 + b,
                                                     "log": [], "journal": [{"op": "absent", "path": "/nope"}]}))
    home.json(".cc-profiles/config.json", {
        "profiles": [{"id": "default", "label": "Default", "dir": "~/.claude", "config": "~/.claude.json",
                      "command": "claude"}]
        + [{"id": p, "label": p.title(), "dir": f"~/.claude-{p}", "config": f"~/.claude-{p}/.claude.json",
            "command": f"claude-{p}"} for p in PROFILES[1:]],
        "rules": [{"match": f"code/{k}", "profile": v} for k, v in
                  [("work", "work"), ("client", "client"), ("lab", "lab"), ("personal", "default")]],
        "search_roots": ["~"]})
    (root / ".built").write_text("ok")


GETS = [
    ("Profiles cards", "/api/profiles"),
    ("Projects", "/api/projects"),
    ("Memories", "/api/memory/projects?profile=default"),
    ("Conversations", "/api/conversations/projects?profile=default"),
    ("Profiles tab (sharing)", "/api/sharing"),
    ("Skills", "/api/skills?profile=default"),
    ("MCP", "/api/mcp?profile=default"),
    ("Plugins", "/api/plugins?profile=default"),
    ("Settings", "/api/settings?profile=default"),
    ("Backups", "/api/backups"),
    ("Health", "/api/health"),
    ("About", "/api/about"),
    ("Search", "/api/search?q=task%2012"),
    ("Compare", "/api/compare?a=default&b=work"),
]


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cc-profiles-bench")
    if not (root / ".built").exists():
        root.mkdir(parents=True, exist_ok=True)
        t = time.time()
        build(root)
        print(f"built {root} in {time.time() - t:.0f} s")
    app = App(FakeHome(root))
    time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 0)
    try:
        print(f"{'request':26} {'first':>8} {'again':>8}  size")
        for label, path in GETS:
            times = []
            for _ in range(2):
                t = time.time()
                req = urllib.request.Request(app.base + path, headers={"X-Token": app.token})
                with urllib.request.urlopen(req, timeout=900) as r:  # slow requests are what we measure
                    status, body = r.status, json.loads(r.read())
                times.append(time.time() - t)
            assert status == 200, (path, body)
            print(f"{label:26} {times[0]:7.2f}s {times[1]:7.2f}s  {len(json.dumps(body)) // 1024} KB")
    finally:
        app.stop()


if __name__ == "__main__":
    main()
