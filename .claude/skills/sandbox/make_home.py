"""Build a fake home with Claude Code profiles to try cc-profiles on, and print its path.

Usage: .venv/bin/python .claude/skills/sandbox/make_home.py [folder]
Without a folder it creates a new temporary one. Uses FakeHome from the tests.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import FakeHome  # noqa: E402

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="cc-profiles-sandbox-"))
root.mkdir(parents=True, exist_ok=True)
home = FakeHome(root)

# Three profiles: Default (~/.claude), Work and Client. Default has MCP servers and three claude.ai connectors.
for name in ("", "work", "client"):
    home.profile(name)
home.json(".claude.json", {
    "oauthAccount": {"emailAddress": "me@example.com"},
    "claudeAiMcpEverConnected": ["claude.ai Google Drive", "claude.ai Gmail", "claude.ai Linear"],
    "mcpServers": {
        "filesystem": {"type": "stdio", "command": "npx",
                       "args": ["-y", "@modelcontextprotocol/server-filesystem", "~/code"]},
        "github": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                   "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "not-a-real-token"}},
        "sentry": {"type": "http", "url": "https://mcp.sentry.dev/mcp"}},
    "projects": {str(home.path("code/work/api")): {
        "allowedTools": ["Bash"],
        "mcpServers": {"api-docs": {"type": "http", "url": "https://example.com/mcp",
                                    "headers": {"Authorization": "Bearer not-a-real-token"}}}}}})
# two GitHub CLI sign-ins (the user only: tokens live in the keychain), for the GitHub section
for folder, user in ((".config/gh", "me-personal"), (".config/gh-work", "me-at-work")):
    home.write(folder + "/hosts.yml", f"github.com:\n    git_protocol: https\n    users:\n        {user}:\n    user: {user}\n")
home.json(".claude-work/.claude.json", {"projects": {}})
home.json(".claude-client/.claude.json", {"projects": {}})
home.json(".claude/settings.json", {"model": "sonnet", "timeFormat": "24-hour", "theme": "dark",
                                    "outputStyle": "Explanatory"})
home.write(".claude/CLAUDE.md", "# Global instructions\n\nAnswer briefly.\n")
SKILLS = {
    "review": "Review a diff for bugs, missing tests and unclear names before it is merged",
    "release-notes": "Write release notes from the pull requests merged since the last tag",
    "write-tests": "Add tests for the code that just changed, following the project's test style",
    "commit-message": "Write a commit message that says what changed and why, in the repo's style",
    "sql-explain": "Explain a slow SQL query and suggest indexes, reading the EXPLAIN output",
    "changelog": "Keep CHANGELOG.md up to date under Unreleased, grouped by Added, Changed and Fixed",
}
for name, desc in SKILLS.items():
    home.write(f".claude/skills/{name}/SKILL.md", f"---\nname: {name}\ndescription: {desc}\n---\n# {name}\n\n{desc}.\n")
home.write(".claude/skills/release-notes/template.md", "## What's new\n")
home.write(".claude-work/skills/oncall/SKILL.md",
           "---\nname: oncall\ndescription: Triage an alert: find the service, recent deploys and the runbook\n---\n")

# Projects: one in the wrong profile, one in two profiles, one whose folder moved (Health finds it).
home.conversation("", "code/work/api", "s-api", {
    "api-notes.md": "The API uses Postgres 16; migrations live in db/migrations.",
    "deploy.md": "Deploy with make release; never deploy on Fridays.",
    "testing.md": "Run the integration tests with docker compose up -d first.",
    "auth.md": "Sessions are JWTs signed with the key in Vault, rotated monthly."})
home.conversation("work", "code/work/api", "s-api-work")
home.conversation("work", "code/work/billing", "s-billing", {"billing.md": "invoices are monthly"})
home.conversation("", "code/personal/blog", "s-blog", {"style.md": "short posts, no emoji"})
home.conversation("client", "code/client/site", "s-site")
home.conversation("", "code/old-name", "s-old")
home.history("", [("code/work/api", "fix the api", 2), ("code/personal/blog", "new post", 1),
                  ("code/old-name", "old prompt", 3)])
home.history("work", [("code/work/api", "work prompt", 4), ("code/work/billing", "monthly invoices", 5)])
os.rename(home.path("code/old-name"), home.path("code/new-name"))  # the user moved a folder


def describe_memories(root):
    """FakeHome writes placeholder descriptions: use the first line of each memory instead,
    as Claude Code does, and rebuild the MEMORY.md indexes."""
    for md in root.glob(".claude*/projects/*/memory"):
        lines = []
        for f in sorted(md.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            body = f.read_text().split("---\n")[-1].strip()
            f.write_text(f"---\nname: {f.stem}\ndescription: {body}\nmetadata:\n  type: project\n---\n{body}\n")
            lines.append(f"- [{f.stem}]({f.name}) — {body}")
        (md / "MEMORY.md").write_text("\n".join(lines) + "\n")


describe_memories(root)

TALKS = {
    "s-api": [("user", "The /orders endpoint is slow, can you find out why?"),
              ("assistant", "I'll look at the query first.", "Bash"),
              ("assistant", "The orders query has no index on customer_id: it scans 2 million rows. Adding the index brings it from 1.8 s to 12 ms."),
              ("user", "Great, add a migration for it.")],
    "s-api-work": [("user", "Write tests for the invoice totals."),
                   ("assistant", "Added 6 tests covering discounts, VAT and rounding.", "Edit")],
    "s-billing": [("user", "Why do monthly invoices start on the 2nd?"),
                  ("assistant", "The cron job runs at midnight UTC, which is still the 1st in your time zone only after 1 am.")],
    "s-blog": [("user", "Draft a short post about our new release."),
               ("assistant", "Here is a 300-word draft with a title and three sections.")],
    "s-site": [("user", "Fix the broken link in the footer."), ("assistant", "Fixed: it pointed to /about-us instead of /about.", "Edit")],
    "s-old": [("user", "Rename the project folder to new-name."), ("assistant", "Done. Remember to relink it in cc-profiles.")],
}


# Which model answered in each conversation, and how many days ago it started: the Usage
# tab then shows a few weeks of replies. Timestamps are relative to now, so the sample
# data always falls in the last 7 and 30 days.
MODELS = {"s-api": "claude-opus-5-5", "s-api-work": "claude-sonnet-5-5", "s-billing": "claude-sonnet-5-5",
          "s-blog": "claude-haiku-4-5", "s-site": "claude-opus-4-8", "s-old": "claude-sonnet-4-6"}
AGO = {"s-api": 1, "s-api-work": 3, "s-billing": 9, "s-blog": 5, "s-site": 2, "s-old": 20}


def write_talks(root):
    """FakeHome writes one technical line per conversation: add real prompts and replies,
    with the token usage Claude Code records on every reply, plus earlier replies that
    only carry usage (tool calls), so the Usage tab has a few weeks to show."""
    import json
    import random
    import time
    rnd = random.Random(7)
    now = time.time()
    stamp = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))

    def usage():
        return {"input_tokens": rnd.randint(3, 60), "output_tokens": rnd.randint(150, 2400),
                "cache_creation_input_tokens": rnd.randint(500, 9000),
                "cache_read_input_tokens": rnd.randint(15000, 90000)}

    for f in sorted(root.glob(".claude*/projects/*/*.jsonl")):
        lines = f.read_text().splitlines()
        cwd = json.loads(lines[0]).get("cwd") if lines else None
        model, start = MODELS.get(f.stem, "claude-sonnet-5-5"), now - AGO.get(f.stem, 4) * 86400
        n = 0

        def reply(t, content, extra=None):
            nonlocal n
            n += 1
            line = {"type": "assistant", "sessionId": f.stem, "cwd": cwd, "timestamp": stamp(t),
                    "requestId": f"req_{f.stem}_{n}",
                    "message": {"id": f"msg_{f.stem}_{n}", "role": "assistant", "model": model,
                                "content": content, "usage": usage()}}
            line.update(extra or {})
            return json.dumps(line, separators=(",", ":"))  # compact, like Claude Code

        # earlier work in the same project: replies with only a tool call and their usage
        for day in range(AGO.get(f.stem, 4) + 6, AGO.get(f.stem, 4), -1):
            for _ in range(rnd.randint(0, 6)):
                lines.append(reply(now - day * 86400 + rnd.randint(0, 36000), [{"type": "thinking", "thinking": ""}]))
        for i, msg in enumerate(TALKS.get(f.stem, [])):
            role, text, t = msg[0], msg[1], start + i * 90
            if role == "user":
                lines.append(json.dumps({"type": "user", "sessionId": f.stem, "cwd": cwd, "timestamp": stamp(t),
                                         "message": {"role": "user", "content": text}}, separators=(",", ":")))
                continue
            lines.append(reply(t, [{"type": "text", "text": text}]))
            if len(msg) > 2:  # a second line for the same reply, as Claude Code writes while streaming
                same = json.loads(lines[-1])
                same["message"]["content"] = [{"type": "tool_use", "name": msg[2], "input": {}}]
                lines.append(json.dumps(same, separators=(",", ":")))
        f.write_text("\n".join(lines) + "\n")


write_talks(root)

print(root)
