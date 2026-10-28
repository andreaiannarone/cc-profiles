# Projects

The **Projects** tab lists every project that has a folder under `projects/` in at least one profile. For each one it shows:

- **Belongs to**: the profile the [rules](../concepts.md#rules) assign it to, *All profiles* for shared paths, or *unassigned*.
- One column per profile: how many conversations and memories the project has there.
- **Status**: what needs fixing, if anything.

The tab opens on **Needs attention**. Use the chips to see all projects, the projects of one profile, or the shared ones, and the search field to filter by path.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../assets/screenshots/projects-dark.jpg">
  <img src="../assets/screenshots/projects-light.jpg" alt="The Projects tab: five projects with their profile, conversations and memories per profile, one folder not found on disk and one project to move to Work" width="1440" height="684" loading="lazy">
</picture>

## Move a project to another profile

When a project has content in a profile it does not belong to, its row shows **Move to …**. You can also choose *Move from A to B* under **Manage**.

Moving takes everything that belongs to the project in the source profile:

| What | Where it lives |
|---|---|
| conversations | `projects/<name>/*.jsonl` |
| memories and their `MEMORY.md` index | `projects/<name>/memory/` |
| file snapshots of those conversations | `file-history/<session>/` |
| prompts typed in that project | `history.jsonl` |
| per-project settings (trust, allowed tools, MCP servers) | `projects` key of `.claude.json` |

Before confirming, *Show the files and folders it touches* lists every item and what happens to it: moved, merged into the target's `MEMORY.md`, or kept in the backup because the target already has it. The preview changes nothing.

If a Claude Code session is open in either profile, the confirmation says so: Claude Code keeps `.claude.json` in memory and could write the old project settings back. Close it first, or restart it after moving.

If the target profile already has something with the same name, the target's version is kept and the incoming one goes to the backup. Index lines of `MEMORY.md` are merged. Prompts already present in the target history (same text and timestamp) are not duplicated.

## Orphan projects

A project is an **orphan** when its folder no longer exists on disk, usually because you moved or renamed it. Claude Code then stops showing its history, because it looks for the folder under its new name.

**Relink…** asks where the project is now. It suggests folders with the same name, found by searching the folders in `search_roots` (your home by default) up to 5 levels deep, skipping `node_modules`, `Library`, hidden folders and build folders. You can also type the path, or click **Choose…** to pick the folder: it opens your system's folder dialog (Finder's on macOS, `zenity` or `kdialog` on Linux), and where there is none, such as WSL, a folder browser opens under the field. A browser never tells a web page the full path of a folder you pick, so the app's server, which runs on your computer, opens the dialog and fills in the path. Relinking:

1. moves the conversations and memories to the folder name that matches the new path;
2. rewrites the prompts in `history.jsonl` to the new path, so arrow-up history works there again;
3. renames the per-project settings in `.claude.json`.

**Merge into…**, next to Relink, does the same with a project you already have instead of a folder: when the history of an old folder belongs with a project that exists, pick that project from the list (projects of the same profile whose folder is on disk, the ones with the same folder name first; type to filter). A confirmation says how many conversations, memories and prompts go in, and lists the files the target already has: the target keeps its own, and the originals go to the backup. Memories are merged with their `MEMORY.md` lines, and nothing is deleted.

If the folder is gone for good, **Delete** moves the project to the backup.

In the [Mac app](../mac-app.md) you can also drop the project's new folder on the window or on the Dock icon: it asks which orphan project lives there now, then relinks it.

> A project on an external disk shows as an orphan while the disk is not connected. Leave it alone: it comes back when you plug the disk in.

## Open a project in a terminal

On macOS, **Open in Terminal** (on the row, and in **Manage**) opens the project's folder in a new terminal window with Claude Code running in the profile you pick, as if you had typed its command there. When Claude Code exits, the shell stays open. Terminal, iTerm and Ghostty work; with more than one installed, pick it in the About panel (ⓘ). The button names the terminal, and shows only for projects whose folder exists. The [Mac app](../mac-app.md) also opens any folder this way from the Finder's Quick Actions, and your recent projects from its Dock icon.

## Assign projects with rules

**Assign…** (or *Assign to a profile* under **Manage**) creates a rule from a piece of the path, for example `code/work` → *Work*. Every current and future project whose path contains that text belongs to that profile. Prefer the shortest piece that is still unambiguous: a rule on a parent folder covers everything inside it.

## Delete a project from a profile

**Manage → Delete from …** moves the project's folder and its file snapshots to the backup. The project stays in the other profiles. Prompts in the history are left untouched: they disappear once the folder is gone, and they come back if you restore.
