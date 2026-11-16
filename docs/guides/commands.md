# Commands

The **Commands** tab manages the custom slash commands of one profile at a time: the files in its `commands/` folder. A command is a prompt saved under a name. Type `/review` in Claude Code and it sends the prompt in `commands/review.md`. Pick the profile at the top of the tab, as in Skills and Agents.

Every change goes to a backup first, like any other operation, and applies from the next Claude Code session in that profile.

## Names and namespaces

| File | Command |
|---|---|
| `commands/review.md` | `/review` |
| `commands/git/commit.md` | `/git:commit` |

A subfolder adds a namespace, up to two folders deep. Names use letters, digits, dots, dashes and underscores. In **New command…** you can type the name either way: `git/commit` or `/git:commit`.

## The file

A command file is the prompt, with optional frontmatter that Claude Code reads:

```markdown
---
description: Review the current diff for bugs
argument-hint: [file]
allowed-tools: Bash(git diff:*)
model: sonnet
---
Review $ARGUMENTS
```

- `description` shows in the `/` menu. Without it, Claude Code shows the prompt's first line.
- `argument-hint` shows what to type after the command.
- `allowed-tools` lets the command run these tools without asking.
- `model` picks the model for that turn.
- `$ARGUMENTS` is everything typed after the command, and `$1`, `$2` are its words.

The editor edits the whole file. A frontmatter that is opened with `---` but never closed cannot be saved.

## The list

Each card shows the command as you type it, its argument hint, its description (or the prompt's first line), the model, **allowed tools**, and **linked** when the file is a link to somewhere else. Type in *Filter commands…* to narrow the list.

`/cc-profiles` carries the **cc-profiles** badge. It is cc-profiles' own command, kept up to date at every start, so it opens read-only and cannot be deleted here. Turn it off with `cc-profiles install-command --off`.

Commands that installed plugins bring are listed below, under **From plugins**, as `/plugin:name`. They are read-only: the plugin installs and updates them.

## Copy and delete

- **Copy to…** copies the saved file to another profile, unless that profile already has a command with the same name.
- **Copy to all…** first shows which profiles get it and which are skipped: those that already have it, and those that share their `commands` folder with a profile already in the list. One backup covers every profile.
- **Delete** moves the file into the backup. If the `commands` folder is [shared](profiles.md#share-items), the command disappears from every profile that shares it, and the confirmation says so.
