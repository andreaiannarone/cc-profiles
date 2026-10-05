# Backups

Every operation that changes files creates a backup in `~/.cc-profiles/backups/<date>_<operation>/`, before touching anything.

## What a backup contains

| File | Content |
|---|---|
| `manifest.json` | title, time, cc-profiles version, log lines, and the **journal** |
| `operation.txt` | the same title and log, readable without tools |
| `file/` | original copies of modified files, and anything moved out of the way |

The journal lists every step in order:

| Step | Meaning | Restoring does |
|---|---|---|
| `copy` | a file was modified; its original is in `file/` | puts the original back |
| `absent` | a file was created that did not exist | removes it |
| `stash` | a file or folder was moved out of the way, into `file/` | moves it back |
| `move` | something was moved from `from` to `to` | moves it back to `from` |
| `mkdir` | a folder was created | removes it if still empty |
| `created` | a link, launcher or profile was created | removes it |

Only the first copy of a file is kept, because it is the state before the operation. Modified files are stored through symlinks, so restoring a shared file writes the real file and keeps the link.

## Restore

**Restore** walks the journal backwards. It is itself an operation with a backup (titled *Before restoring: …*), so you can undo a restore.

A step that cannot be replayed is skipped and reported, for example when something it needs was moved again since. The other steps still run.

**Restore newest first.** Operations often depend on each other: if B moved a file that A created, A cannot be undone cleanly while B is still in place. When you restore an older backup while newer ones are still active, the app warns you.

A backup can be restored once; afterwards it shows *restored* with the time.

## Delete

**Delete** erases a backup folder for good. It is the only action in cc-profiles that really deletes data. Backups take space, especially after deleting or merging whole profiles; the tab shows the total size.

**Delete old backups…** removes in one go every backup older than 7, 30, 90 or 365 days, and shows how many and how much space before you confirm. Keep the backups of operations you might still want to undo.

## Without the UI

Backups are plain files. If the app cannot start, you can still read `operation.txt` and copy files back from `file/` by hand, using the journal in `manifest.json` as a map.
