# Memories

Claude Code's auto-memory saves notes in `projects/<name>/memory/`, one Markdown file per memory, plus a `MEMORY.md` index that Claude reads at the start of every session in that project. The memories of your home folder's project act as general memories: they load whenever you start Claude Code from your home.

## Browse

Pick a profile and a project on the left. By default only projects with memories are listed; tick *also show projects without memories* to see every project, for example to pick a destination.

Each memory shows its name, type (`user`, `feedback`, `project`, `reference`) and description, taken from the file's frontmatter. Two problems are flagged:

- **not in MEMORY.md**: the file exists but the index does not list it, so Claude may never read it.
- **MEMORY.md lists files that do not exist**: the index points to a deleted file.

## Edit

Click a memory to open it in the editor. **Save** keeps the previous version in a backup.

## Move

**Move…** sends a memory to another project, in the same profile or a different one. The line is removed from the source `MEMORY.md` and added to the target's (created if needed). Moving fails if the target already has a memory with the same file name.

Typical uses:

- a memory saved in the wrong project
- a preference that is about *you*, not one project: move it to your home project so it applies everywhere
- a work memory that ended up in a personal profile

## Delete

**Delete** removes the line from `MEMORY.md` and moves the file to the backup.

## Good practice

- Memories that contradict the current code are worse than no memory: Claude follows them confidently. Delete memories about things you removed.
- When the same preference shows up in several projects, merge it into one memory in your home project.
- For context that must always apply in a profile ("in this profile you work for …"), use the profile's `CLAUDE.md` instead: it is always loaded, while memories are recalled when relevant. See [Settings](settings.md#claudemd).
