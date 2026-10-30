"""Conversations: list, view, move, delete.

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import json

from conftest import san
from helpers import basic_home


# --- conversations ------------------------------------------------------------


def write_session(home, profile, project, session, n_prompts=2):
    """A conversation shaped like Claude Code's: prompts, replies, a tool call and its result,
    a slash command, a meta line, the AI title and a file snapshot folder."""
    proj = home.conversation(profile, project, session)  # creates the folder and file-history/<session>
    lines = [
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "<local-command-caveat>x</local-command-caveat>"}},
        {"type": "user", "message": {"role": "user", "content": "<command-name>/clear</command-name>"},
         "timestamp": "2026-10-01T09:00:00Z"},
    ]
    for i in range(n_prompts):
        lines += [
            {"type": "user", "message": {"role": "user", "content": f"Fix the login bug number {i}"},
             "timestamp": f"2026-10-01T10:0{i}:00Z"},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "hm"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "x" * 5000}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": f"Fixed bug {i}."}]},
             "timestamp": f"2026-10-01T10:0{i}:30Z"},
        ]
    lines.append({"type": "ai-title", "aiTitle": "Login bug fixes", "sessionId": session})
    (proj / f"{session}.jsonl").write_text("\n".join(json.dumps(l, separators=(",", ":")) for l in lines) + "\n")
    return proj


def test_conversations_are_listed_and_viewed(home, app_factory):
    basic_home(home)
    write_session(home, "", "code/work/api", "s-api", n_prompts=2)
    app = app_factory()
    api = san(home.path("code/work/api"))
    projects = {p["name"]: p["count"] for p in app.get("/api/conversations/projects?profile=default")}
    assert projects[api] == 1
    (c,) = app.get(f"/api/conversations?profile=default&project={api}")["conversations"]
    assert c["session"] == "s-api" and c["title"] == "Login bug fixes"  # the AI title wins
    assert (c["prompts"], c["replies"]) == (2, 2) and c["snapshots"] is True
    assert c["first"] == "2026-10-01T09:00:00Z" and c["last"] == "2026-10-01T10:01:30Z"
    view = app.get(f"/api/conversations/view?profile=default&project={api}&session=s-api")
    assert [m["role"] for m in view["messages"]] == ["user", "tool", "assistant", "user", "tool", "assistant"]
    assert view["truncated"] is False and view["messages"][1]["text"] == "Tool: Bash"
    assert "x" * 100 not in json.dumps(view)  # tool results are left out

    blog = san(home.path("code/personal/blog"))
    write_session(home, "", "code/personal/blog", "s-long", n_prompts=0)
    with open(home.path(f".claude/projects/{blog}/s-long.jsonl"), "a") as f:
        for i in range(320):
            f.write(json.dumps({"type": "user", "message": {"content": f"prompt {i} " + "y" * 5000}},
                               separators=(",", ":")) + "\n")
    view = app.get(f"/api/conversations/view?profile=default&project={blog}&session=s-long")
    assert view["truncated"] is True and view["total"] == 320 and len(view["messages"]) == 300
    assert view["messages"][-1]["text"].startswith("prompt 319") and view["messages"][-1]["text"].endswith("…")

    # JSON with spaces (not how Claude Code writes it today) is read just the same
    with open(home.path(f".claude/projects/{blog}/s-spaced.jsonl"), "w") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "spaced prompt"}}) + "\n")
        f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}}) + "\n")
    spaced = next(c for c in app.get(f"/api/conversations?profile=default&project={blog}")["conversations"]
                  if c["session"] == "s-spaced")
    assert (spaced["title"], spaced["prompts"], spaced["replies"]) == ("spaced prompt", 1, 1)

    for bad in ("../x", "", "a/b", ".."):
        assert app.request(f"/api/conversations/view?profile=default&project={api}&session={bad}")[0] in (400, 404)
    assert app.request("/api/conversations?profile=default&project=..")[0] == 400


def test_one_conversation_moves_and_everything_is_undoable(home, app_factory):
    basic_home(home)
    write_session(home, "", "code/work/api", "s-two")  # a second conversation in the same project
    before = home.snapshot()
    app = app_factory()
    api = san(home.path("code/work/api"))
    hist = home.path(".claude/history.jsonl").read_text()

    r = app.post("/api/conversations/move", {"profile": "default", "project": api, "session": "s-two", "to": "work"})
    assert "with its file snapshots" in r["message"]
    assert home.path(f".claude-work/projects/{api}/s-two.jsonl").exists()
    assert home.path(".claude-work/file-history/s-two").is_dir() and not home.path(".claude/file-history/s-two").exists()
    assert home.path(f".claude/projects/{api}/s-api.jsonl").exists()  # the other conversation stays
    assert home.path(".claude/history.jsonl").read_text() == hist  # prompt history is not touched
    assert "Pick another" in app.post_error("/api/conversations/move",
                                            {"profile": "work", "project": api, "session": "s-two", "to": "work"})

    app.post("/api/conversations/delete", {"profile": "default", "project": api, "session": "s-api"})
    assert not home.path(f".claude/projects/{api}/s-api.jsonl").exists()
    assert not home.path(".claude/file-history/s-api").exists()

    app.restore_all()
    assert home.snapshot() == before


def test_moving_a_conversation_the_target_has_is_refused(home, app_factory):
    basic_home(home)
    app = app_factory()
    api = san(home.path("code/work/api"))
    write_session(home, "work", "code/work/api", "s-api")  # Work already has a conversation with this id
    assert "already has" in app.post_error("/api/conversations/move",
                                           {"profile": "default", "project": api, "session": "s-api", "to": "work"})
