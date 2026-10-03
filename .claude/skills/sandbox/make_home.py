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

# Three profiles: Default (~/.claude), Work and Client. Default has two MCP servers.
for name in ("", "work", "client"):
    home.profile(name)
home.json(".claude.json", {
    "oauthAccount": {"emailAddress": "me@example.com"},
    "mcpServers": {"filesystem": {"type": "stdio", "command": "npx",
                                  "args": ["-y", "@modelcontextprotocol/server-filesystem", "~/code"]}},
    "projects": {str(home.path("code/work/api")): {
        "allowedTools": ["Bash"],
        "mcpServers": {"api-docs": {"type": "http", "url": "https://example.com/mcp",
                                    "headers": {"Authorization": "Bearer not-a-real-token"}}}}}})
home.json(".claude-work/.claude.json", {"projects": {}})
home.json(".claude-client/.claude.json", {"projects": {}})
home.json(".claude/settings.json", {"model": "sonnet", "effortLevel": "high", "theme": "dark"})
home.write(".claude/CLAUDE.md", "# Global instructions\n\nAnswer briefly.\n")
home.write(".claude/skills/review/SKILL.md", "---\nname: review\ndescription: Review a diff\n---\nReview it.\n")

# Projects: one in the wrong profile, one in two profiles, one whose folder moved (Health finds it).
home.conversation("", "code/work/api", "s-api", {"api-notes.md": "the api uses postgres",
                                                 "deploy.md": "deploy with make release"})
home.conversation("work", "code/work/api", "s-api-work")
home.conversation("work", "code/work/billing", "s-billing", {"billing.md": "invoices are monthly"})
home.conversation("", "code/personal/blog", "s-blog", {"style.md": "short posts, no emoji"})
home.conversation("client", "code/client/site", "s-site")
home.conversation("", "code/old-name", "s-old")
home.history("", [("code/work/api", "fix the api", 2), ("code/personal/blog", "new post", 1),
                  ("code/old-name", "old prompt", 3)])
home.history("work", [("code/work/api", "work prompt", 4), ("code/work/billing", "monthly invoices", 5)])
os.rename(home.path("code/old-name"), home.path("code/new-name"))  # the user moved a folder

print(root)
