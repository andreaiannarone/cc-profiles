"""Disk space of a profile: what fills it, and moving what is old into a backup.

Like every end-to-end test here, they run against a real server on a fake home and
end by restoring every backup and comparing the fake home with how it started.
"""
import json
import os
import time

from helpers import basic_home

OLD = time.time() - 60 * 86400


def age(path, when=OLD):
    """Set the times of a file or folder and everything in it."""
    for cur, dirs, files in os.walk(path):
        for n in files + dirs:
            os.utime(os.path.join(cur, n), (when, when))
    os.utime(path, (when, when))


def storage_home(home):
    basic_home(home)  # conversations s-api, s-blog, s-old with file-history, dated 2001
    d = home.profile("")
    conv = next((d / "projects").glob("*api*"))
    (conv / "s-api").mkdir()
    (conv / "s-api" / "subagent.jsonl").write_text("{}\n")
    age(conv / "s-api")
    home.write(".claude/file-history/gone-session/snap", "x" * 100)
    home.write(".claude/session-env/gone-session/env", "x")
    home.write(".claude/todos/s-blog-agent-s-blog.json", "[]")
    home.write(".claude/debug/old.txt", "x" * 1000)
    home.write(".claude/debug/new.txt", "x" * 10)
    home.write(".claude/paste-cache/abc.txt", "pasted")
    for rel in ("file-history/gone-session", "session-env/gone-session", "todos/s-blog-agent-s-blog.json",
                "debug/old.txt", "paste-cache/abc.txt", "file-history/s-api", "file-history/s-blog", "file-history/s-old"):
        age(d / rel)
    age(d / "projects")
    return d


def test_disk_space_lists_what_is_old_and_frees_it_into_a_backup(home, app_factory):
    d = storage_home(home)
    before = home.snapshot()
    app = app_factory()

    s = app.get("/api/storage?profile=default")
    assert s["days"] == 30 and s["cleanup_days"] is None and s["keep_days"] == 90
    cats = {c["id"]: c for c in s["categories"]}
    assert cats["conversations"]["count"] == 3 and cats["conversations"]["old_count"] == 3
    # the files of a session that still has its conversation count with it, not on their own
    assert (cats["file-history"]["count"], cats["file-history"]["old_size"]) == (1, 100)
    assert cats["todos"]["count"] == 0 and cats["session-env"]["count"] == 1
    assert (cats["debug"]["count"], cats["debug"]["old_count"], cats["debug"]["old_size"]) == (2, 1, 1000)
    assert cats["image-cache"]["count"] == 0
    assert s["total"] > 0

    # Claude Code's own setting is the default number of days
    app.post("/api/settings/field", {"profile": "default", "key": "cleanupPeriodDays", "value": 7})
    assert app.get("/api/storage?profile=default")["days"] == 7
    assert app.get("/api/storage?profile=default&days=100000")["categories"][0]["old_count"] == 0
    assert "Days" in app.post_error("/api/storage/clean", {"profile": "default", "days": 0, "categories": ["debug"]})
    assert "Pick" in app.post_error("/api/storage/clean", {"profile": "default", "days": 30, "categories": ["memory"]})

    r = app.post("/api/storage/clean", {"profile": "default", "days": 30,
                                        "categories": ["debug", "file-history", "session-env", "paste-cache"]})
    assert r["freed"] == 1000 + 100 + 1 + 6 and "moved to the backup" in r["message"]
    assert not (d / "debug/old.txt").exists() and (d / "debug/new.txt").exists()
    assert not (d / "file-history/gone-session").exists() and (d / "file-history/s-api").exists()

    r = app.post("/api/storage/clean", {"profile": "default", "days": 30, "categories": ["conversations"]})
    assert not list((d / "projects").glob("*/*.jsonl"))
    assert not (d / "file-history/s-api").exists() and not (d / "todos/s-blog-agent-s-blog.json").exists()
    assert list((d / "projects").glob("*/memory/api-notes.md")), "memories stay"
    assert "Nothing older" in app.post_error("/api/storage/clean", {"profile": "default", "days": 30,
                                                                   "categories": ["conversations"]})

    app.restore_all()
    assert home.snapshot() == before
    assert json.loads(home.path(".claude/settings.json").read_text()) == {}
