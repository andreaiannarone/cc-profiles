"""Global search and profile comparison (read-only).

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import json

from helpers import basic_home


# --- search and compare (read-only) --------------------------------------------


def search_home(home):
    basic_home(home)
    home.write(".claude/skills/release-notes/SKILL.md",
               "---\nname: release-notes\ndescription: Write the changelog from merged pull requests\n---\nBody.\n")
    home.write(".claude/CLAUDE.md", "# Rules\n\nAlways answer in English.\nPrefer postgres for databases.\n")
    cfg = json.loads(home.path(".claude.json").read_text())
    cfg["mcpServers"] = {"files": {"type": "stdio", "command": "npx", "args": ["-y", "server-filesystem"],
                                   "env": {"API_KEY": "secret-zebra-123"}}}
    home.json(".claude.json", cfg)


def test_search_finds_everything_and_changes_nothing(home, app_factory):
    search_home(home)
    before = home.snapshot()
    app = app_factory()
    r = app.get("/api/search?q=POSTGRES")  # case-insensitive
    assert {m["open"]["file"] for m in r["results"]["memories"]} == {"api-notes.md"}  # a memory body
    hit = r["results"]["claude_md"][0]
    assert hit["profile"] == "default" and hit["open"]["line"] == 4
    assert hit["snippet"]["text"][hit["snippet"]["at"]:][:8].lower() == "postgres"
    assert [s["title"] for s in app.get("/api/search?q=changelog")["results"]["skills"]] == ["release-notes"]
    mcp = app.get("/api/search?q=filesystem")["results"]["mcp"]
    assert [(m["title"], m["open"]["scope"]) for m in mcp] == [("files", "user")]
    proj = app.get("/api/search?q=work/api")["results"]["projects"]
    assert len(proj) == 1 and sorted(proj[0]["profiles"]) == ["default", "work"]
    assert "secret-zebra" not in json.dumps(app.get("/api/search?q=files"))
    assert app.get("/api/search?q=secret-zebra")["counts"]["mcp"] == 0  # env values are not searched
    assert app.request("/api/search?q=a")[0] == 400
    assert home.snapshot() == before


def test_compare_two_profiles(home, app_factory):
    search_home(home)
    home.json(".claude/settings.json", {"language": "English", "permissions": {"allow": ["Bash(ls)", "Read"]}})
    home.json(".claude-work/settings.local.json", {"language": "Italiano"})
    home.json(".claude-work/settings.json", {"permissions": {"allow": ["Read"], "deny": ["Bash(rm:*)"]}})
    home.write(".claude-work/skills/release-notes/SKILL.md", "---\nname: release-notes\n---\nOther.\n")
    home.write(".claude-work/skills/oncall/SKILL.md", "---\nname: oncall\n---\n")
    cfg = json.loads(home.path(".claude-work/.claude.json").read_text())
    cfg["mcpServers"] = {"sentry": {"type": "http", "url": "https://mcp.sentry.dev/mcp",
                                    "headers": {"Authorization": "Bearer secret-zebra-456"}}}
    home.json(".claude-work/.claude.json", cfg)
    before = home.snapshot()
    app = app_factory()
    c = app.get("/api/compare?a=default&b=work")
    lang = next(s for s in c["settings"] if s["key"] == "language")
    assert (lang["a"], lang["a_source"], lang["b"], lang["b_source"], lang["same"]) == \
        ("English", "settings", "Italiano", "local", False)
    assert not any(s["key"] == "model" for s in c["settings"])  # the model is picked with /model, not here
    assert c["permissions"]["diff"]["allow"] == {"only_a": ["Bash(ls)"], "only_b": [], "both": ["Read"]}
    assert c["permissions"]["diff"]["deny"]["only_b"] == ["Bash(rm:*)"]
    assert c["permissions"]["b"]["deny"] == ["Bash(rm:*)"]  # full lists, to post a merged one back
    assert c["skills"]["only_b"] == ["oncall"] and c["skills"]["both"] == [{"name": "release-notes", "same": False}]
    assert [m["name"] for m in c["mcp"]["only_a"]] == ["files"] and c["mcp"]["only_b"][0]["type"] == "http"
    assert c["claude_md"]["a"]["exists"] and not c["claude_md"]["b"]["exists"] and not c["claude_md"]["same"]
    assert "secret-zebra" not in json.dumps(c)
    assert "two different profiles" in app.request("/api/compare?a=work&b=work")[1]["error"]
    assert home.snapshot() == before
