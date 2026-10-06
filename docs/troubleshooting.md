# Troubleshooting

## "Port 4777 is busy"

cc-profiles is probably already running in another terminal: open `http://127.0.0.1:4777`, or start another instance with `--port 4778`.

## A tab says the page is newer than the server

You updated cc-profiles while it was running: the page comes from the new version, the server is still the old one. Run `cc-profiles restart` (or `/cc-profiles restart` in Claude Code) and reload the page.

## The page shows "Missing or wrong token"

The page is from an older run of the server. Every start generates a new token: reload the page.

## `claude-<id>: command not found`

The launcher is in `~/.local/bin`, which is not in your `PATH`. Add this to your shell startup file and open a new terminal:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

## A new profile is not logged in

That is expected: credentials are never copied. Run the profile's command and use `/login`.

## A profile that was logged in now says "Not logged in"

If the profile was created by copying another profile's folder by hand, it shared the same login token. When one profile refreshed the token, the copy became invalid. Log in again with `/login`. Profiles created by cc-profiles do not have this problem.

## A project shows "folder not found on disk"

You moved or renamed the project folder. Use **Relink…** in the Projects tab, or in Health. If the folder is on an external disk, connect it: the project comes back by itself.

## A project shows "unknown path"

No file mentions the project's real path, and the folder name could not be matched on disk. That usually means the folder is gone. **Delete** moves it to the backup.

## "A session is open"

A `claude` process is running in that profile, or a conversation in it was written in the last 2 minutes. Close Claude Code in that profile (every terminal and editor that runs it), wait two minutes, and try again. The check exists because a running session would keep writing into folders being moved.

## A restore reports "steps not restored"

Some files the backup needs were changed again by a later operation. Restore the newer backups first, newest first, then try again. The *Before restoring: …* backup lists every step that was skipped.

## A setting I changed has no effect

- Changes apply from the **next** Claude Code session in that profile.
- If the setting is also in `settings.local.json`, that value wins. The Settings tab shows where each value comes from.
- Managed (enterprise) settings, if your organization uses them, override everything.

## Settings dropdowns do not show a value I know exists

Dropdown options come from a specific Claude Code version, shown in the Settings tab. A newer Claude Code may accept more values. Set it from the advanced editor, and [open an issue](https://github.com/andreaiannarone/cc-profiles/issues) so the list can be updated.

## Reporting a bug

Open an issue with the steps to reproduce and the output of `cc-profiles --version` and `claude --version`. If an operation went wrong, the `operation.txt` of its backup folder helps, but check it first for private paths or names. Never paste conversations, memories or credentials.
