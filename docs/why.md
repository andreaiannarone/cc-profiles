# Why cc-profiles

Claude Code already supports several profiles: set `CLAUDE_CONFIG_DIR` to another folder and it keeps everything there. Many people start with an alias:

```sh
alias claude-work='CLAUDE_CONFIG_DIR=~/.claude-work claude'
```

That is enough to *use* two profiles. cc-profiles is for everything that comes after: keeping them in order.

## What the alias does not do

**Moving a project between profiles.** A project's history is spread over four places: its folder under `projects/` (named after the path, with every non-alphanumeric character turned into `-`), the file snapshots in `file-history/`, the prompts in `history.jsonl`, and the per-project settings inside `.claude.json`, which for the default profile lives outside the folder. Copy only the first one and `/resume` works while arrow-up history and the project's trust and MCP servers stay behind. See [Move a project](how-to/move-a-project.md).

**Noticing what ended up where.** Start `claude` in a work project from the wrong terminal and its history lands in the wrong profile. The **Projects** tab lists every project with what each profile holds, and rules say where each one belongs.

**Renamed folders.** Rename a project folder and Claude Code finds no history for it: the folder name under `projects/` still has the old path. Relinking means renaming it and rewriting the path in `history.jsonl` and `.claude.json`. See [Relink a moved folder](how-to/relink-a-moved-folder.md).

**Sharing.** Skills, plugins and settings live in each profile. Sharing them by hand means symlinks, made relative so they survive a moved home folder, and remembering never to link a profile through another one. cc-profiles makes and removes them with a switch.

**Undo.** Each of these is a handful of `mv` and edits on files Claude Code may be reading at that moment. cc-profiles writes each file atomically and journals every step in a backup, so any change can be restored.

**Seeing it all.** Memories, conversations, skills, MCP servers, plugins, settings, usage and cost of every profile, in one place, with search across all of them and a side-by-side comparison of two profiles.

## By hand or with cc-profiles

| Task | By hand | cc-profiles |
|---|---|---|
| start Claude Code in a profile | alias or `CLAUDE_CONFIG_DIR=…` | a launcher per profile, or `claude` picks it from the folder |
| create a profile with your settings and skills | copy the folder, then remove the login, caches and sessions | **+ New profile**, from a copy or a template; login never copied |
| move a project | four places, two of them inside JSON and JSONL files | one click, with a preview |
| relink a renamed folder | rename a folder and rewrite two files | **Relink…**, with suggestions |
| share skills | relative symlinks | a switch |
| undo | your own copies, if you made them | **Restore**, for every change |

## When you do not need it

With one profile, or two that never mix, an alias is all you need. cc-profiles is free and local, and [uninstalling it](uninstall.md) leaves your profiles as they are, so trying it costs little.
