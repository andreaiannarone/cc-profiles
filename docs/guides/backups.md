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

## Incomplete backups

If an operation fails halfway (a disk error, a file Claude Code locked, a bug), the steps it had already done stay journaled: the backup is closed anyway and labelled **incomplete**, and the error message says so. **Restore** undoes those steps like any other backup. A failure before any change leaves no backup.

## Restore

**Restore** walks the journal backwards. It is itself an operation with a backup (titled *Before restoring: …*), so you can undo a restore.

A step that cannot be replayed is skipped and reported, for example when something it needs was moved again since. The other steps still run.

**Restore newest first.** Operations often depend on each other: if B moved a file that A created, A cannot be undone cleanly while B is still in place. When you restore an older backup while newer ones are still active, the app warns you.

A backup can be restored once; afterwards it shows *restored* with the time.

## Delete

**Delete** erases a backup folder for good. It is the only action in cc-profiles that really deletes data. Backups take space, especially after deleting or merging whole profiles; the tab shows the total size.

**Delete old backups…** removes in one go every backup older than 7, 30, 90 or 365 days, and shows how many and how much space before you confirm. Keep the backups of operations you might still want to undo.

## Automatic cleanup

**Delete backups older than … automatically**, in the toolbar of the Backups tab, is off by default (*never*). Pick 30, 90, 180 or 365 days to turn it on. From then on cc-profiles deletes the backups older than that when it starts and once a day while it runs. The confirmation shows what goes right away.

The automatic cleanup never deletes:

- a backup of an operation done in the last 24 hours;
- an [incomplete backup](#incomplete-backups) that has not been restored yet, because it may hold the only way to undo a failed operation.

The setting is stored as `backup_keep_days` in [`config.json`](../configuration.md). Changing it is an operation with its own backup, like any other. The backups it deletes cannot be restored.

## Without the UI

Backups are plain files. If the app cannot start, you can still read `operation.txt` and copy files back from `file/` by hand, using the journal in `manifest.json` as a map.
