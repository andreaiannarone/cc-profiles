# Concepts

## Profiles

A **profile** is a folder Claude Code uses for its configuration: `~/.claude` by default, or whatever `CLAUDE_CONFIG_DIR` points to. Each profile has its own:

- memory (general and per project)
- conversations, resumable with `/resume`
- prompt history (arrow up)
- settings, permissions, hooks, `CLAUDE.md`
- skills, plugins, subagents, slash commands, unless they are [shared](#sharing)
- login

Profiles are a good way to keep separate contexts on one machine: work and personal, or one profile per client. Claude.ai connectors and usage limits belong to the *account*, not the profile, so two profiles logged into the same account share them.

## The source profile

The first profile in `config.json` is the **source profile**. Other profiles share items *from* it (see below). It cannot be deleted, and its command is always `claude`.

## Projects

Claude Code stores what belongs to a project in a folder under `projects/`, named after the project's absolute path with every non-alphanumeric character replaced by `-`. For example, `/Users/you/code/api` becomes `-Users-you-code-api`.

Because of this:

- **Moving or renaming a project folder detaches its history.** Claude Code looks for the new name and finds nothing. cc-profiles detects this ([orphan projects](guides/projects.md#orphan-projects)) and can relink it.
- **The name cannot always be turned back into a path.** `-` may stand for `/`, a space, a dot or `+`. cc-profiles recovers the real path from config files, the prompt history and the conversations themselves, and as a last resort by walking the disk.

A project "lives" in a profile when that profile has its conversations or memories. The same project can appear in several profiles.

## Rules

**Rules** say which profile a project belongs to. Each rule matches text in the project's path:

```json
{ "match": "code/work", "profile": "work" }
```

- The first matching rule wins; rules created from the UI are added at the top.
- `{ "exact": "~", "profile": "shared" }` matches one exact path.
- `"profile": "shared"` means "it is normal to find this in every profile", like your home folder or temporary folders.
- A project with no matching rule shows up as *not assigned to a profile*.

When a project belongs to one profile but has content in another, the Projects tab offers **Move to …**.

## Sharing

A profile can **share** an item with the source profile: `skills`, `plugins`, `agents`, `commands`, `CLAUDE.md` or `settings.json`. Sharing replaces the item with a relative symlink (for example `~/.claude-work/skills → ../.claude/skills`), so you install or edit once and every sharing profile sees it.

Notes:

- Writing a shared file (from the Settings tab, for example) writes the source file and keeps the link intact.
- Plugin *files* are shared, but which plugins are *enabled* lives in `settings.json`. Share `settings.json` as well if you want the same plugins enabled everywhere.
- Unsharing gives the profile its own independent copy.

## Backups

Every operation that changes files creates a **backup**: a folder in `~/.cc-profiles/backups/` with the original files and a **journal** of every step (copied, moved, created…). **Restore** replays the journal backwards and puts everything back. A restore is itself an operation with its own backup, so it can be undone too.

Nothing is ever deleted outright. "Delete" moves things into the backup, and only deleting a *backup* really erases data. See [Backups](guides/backups.md).
