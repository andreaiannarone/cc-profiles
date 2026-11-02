"""Automatic exports: every profile exported into a folder, the last 3 of each kept, and a
profile whose folder is gone restored from its latest export."""
import json
import shutil
import time
import zipfile

from helpers import basic_home


def wait_export(app):
    for _ in range(100):
        s = app.get("/api/autoexport")
        if not s["running"]:
            return s
        time.sleep(0.1)
    raise AssertionError("the export did not finish")


def test_export_keep_three_and_restore_a_profile_that_is_gone(home, app_factory, tmp_path):
    basic_home(home)
    home.json(".claude/settings.json", {"model": "opus"})
    home.write(".claude/skills/review/SKILL.md", "---\nname: review\n---\nReview.\n")
    home.path(".claude-work/skills").symlink_to("../.claude/skills")  # Work shares the skills
    out = tmp_path / "exports"
    out.mkdir()
    for day in ("2026-01-01", "2026-01-02", "2026-01-03"):  # older exports of Work
        (out / f"cc-profile-work-{day}.zip").write_text("old")
    (out / "notes.txt").write_text("mine")  # not ours: never touched
    app = app_factory(CC_PROFILES_EXPORT_DIR=str(out))

    s = app.get("/api/autoexport")
    assert s["every"] is None and s["last"] is None and s["keep"] == 3  # off by default
    assert "every day" in app.post("/api/autoexport", {"every": "day"})["message"]
    assert app.get("/api/autoexport")["every"] == "day"
    assert "Exporting every profile" in app.post("/api/autoexport/run", {})["message"]
    s = wait_export(app)
    today = time.strftime("%Y-%m-%d")
    assert {r["id"]: r["file"] for r in s["results"]} == {
        "default": f"cc-profile-default-{today}.zip", "work": f"cc-profile-work-{today}.zip"}
    assert not any(r.get("error") for r in s["results"]) and s["next"] - s["last"] == 86400
    assert sorted(p.name for p in out.iterdir()) == [  # Work: the newest 3, today's included
        f"cc-profile-default-{today}.zip", "cc-profile-work-2026-01-02.zip", "cc-profile-work-2026-01-03.zip",
        f"cc-profile-work-{today}.zip", "notes.txt"]
    with zipfile.ZipFile(out / f"cc-profile-work-{today}.zip") as z:
        names = z.namelist()
        assert any(n.endswith("s-api-work.jsonl") for n in names)  # conversations included
        assert json.loads(z.read("cc-profiles-export.json"))["shared"] == ["skills"]

    # Work's folder disappears (outside cc-profiles): its latest export brings it back
    work = home.path(".claude-work")
    conv = next(work.rglob("s-api-work.jsonl")).read_text()
    shutil.rmtree(work)
    before = home.snapshot()
    row = next(p for p in app.get("/api/profiles") if p["id"] == "work")
    assert row["missing"] and row["restore_from"]["day"] == today
    s = wait_export(app) if app.post("/api/autoexport/run", {}) else None
    assert [r.get("error", "")[:22] for r in s["results"] if r["id"] == "work"] == ["its folder is missing:"]
    assert (out / f"cc-profile-work-{today}.zip").exists()  # the exports of a missing folder are kept

    r = app.post("/api/profiles/restore-export", {"id": "work"})
    assert f"Work restored from the export of {today}" in r["message"]
    assert next(work.rglob("s-api-work.jsonl")).read_text() == conv
    assert (work / "skills").is_symlink() and str((work / "skills").readlink()) == "../.claude/skills"
    assert "oauthAccount" not in json.loads((work / ".claude.json").read_text())
    assert "nothing to restore" in app.post_error("/api/profiles/restore-export", {"id": "work"})
    app.post("/api/backups/restore", {"name": r["backup"].split("/")[-1]})  # Undo: gone again
    assert home.snapshot() == before

    assert "Automatic export off" in app.post("/api/autoexport", {"every": None})["message"]
    assert "Nothing to change" in app.post_error("/api/autoexport", {"every": "off"})


def test_the_export_starts_by_itself_when_due(home, app_factory, tmp_path):
    basic_home(home)
    out = tmp_path / "exports"
    app = app_factory(CC_PROFILES_EXPORT_DIR=str(out), CC_PROFILES_EXPORT_TICK="0.2")
    assert not out.exists()  # off by default: nothing is exported
    app.post("/api/autoexport", {"every": "week"})  # never exported yet: due at once
    for _ in range(100):
        if out.exists() and len(list(out.glob("*.zip"))) == 2:
            break
        time.sleep(0.1)
    assert sorted(p.name.split("-")[2] for p in out.glob("*.zip")) == ["default", "work"]
    s = wait_export(app)
    assert s["every"] == "week" and s["next"] - s["last"] == 7 * 86400
