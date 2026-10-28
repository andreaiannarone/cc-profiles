# Mac app

On macOS, cc-profiles lives in Applications as an app of its own: a window with its icon in the Dock, found in Spotlight and Launchpad, instead of a tab in your browser.

It is added by itself: by the install script, or the first time cc-profiles starts on a Mac, however you installed it (pipx, uv, Homebrew) or updated it. That creates `~/Applications/cc-profiles.app`, with a backup. If you delete it, it stays deleted; to add it back, click **Add Mac app** in the About panel (ⓘ), which also says whether the app is there and up to date, or run:

```sh
cc-profiles install-app
```

To keep it from being added at all, install with `install.sh --no-app`, or run `cc-profiles install-app --off` before the first start (`"mac_app": false` in `config.json`). Open it like any other app, and keep it in the Dock if you like. It is the same cc-profiles: the window shows the page you know, and the browser keeps working too.

Once the app is there, `/cc-profiles` and `cc-profiles open` show cc-profiles in it instead of a browser tab.

## How it works

- **Opening the app** starts the server in the background unless it is already running, as `/cc-profiles` does, and shows it in the window. If the server was already running (started by `/cc-profiles` or `cc-profiles open`), the app uses it.
- **Closing the window, or ⌘Q,** quits the app (closing the window does not, with the menu bar icon on). If the app started the server, the server stops too, after any change in progress; one it found running stays on.
- **Links to other sites** (the documentation, GitHub, claude.ai) open in your default browser. **View → Open in Browser** (⇧⌘O) opens the page there too.
- **Exports** (a profile's `.zip`, the usage CSV) go to your Downloads folder, under a new name if a file with that name is already there.
- **The window comes back where it was**, with its size, and on the tab it was on.
- **⌘R** reloads the page. If the server stops while the app is open, the app starts it again by itself; if it stops three times in five minutes, the window says why instead.
- **A new version** puts a badge on the Dock icon and sends one notification per version. Clicking it opens the About panel, where **Update** installs it.

## Shortcuts

| Keys | Does |
|---|---|
| ⌘, | Settings |
| ⌘F | Search everything |
| ⌘1 … ⌘9 | The tabs, in order |
| ⌘+ ⌘− ⌘0 | Zoom in, out, back to actual size (remembered between launches) |
| ⌘R | Reload |
| ⇧⌘O | Open in your browser |

## Drop files on it

- **A profile's `.zip`** (made by Export) opens Import with the file already picked.
- **A folder** opens Relink: pick which of the projects whose folder is gone now lives there.

Drop them on the window or on the app's icon in the Dock. In a browser the page takes a `.zip` too, but not a folder: browsers do not tell a page where a folder is.

## Open a project in a terminal

Every project with a folder has an **Open in Terminal** button (on its row, and in **Manage**): it opens the folder in a new terminal window with Claude Code already running in the profile you pick. When Claude Code exits, the shell stays open. With iTerm or Ghostty installed, pick which terminal in the About panel. This works in the browser too, on a Mac.

From the Finder, any folder opens the same way: right-click it, then **Quick Actions** (or **Services**) → **Open in Claude Code**. The profile is the one your [rules](guides/projects.md#assign-projects-with-rules) give the folder, as with [profile by folder](guides/profile-by-folder.md); with no rule, the profile its project is already in, else your first profile. **Open in Claude Code with Profile…** asks which. The app starts if it is not open. If the two items do not show, turn them on in System Settings → Keyboard → Keyboard Shortcuts → Services → Files and Folders.

Right-click the app's icon in the Dock for your ten most recent projects: each opens in a terminal with Claude Code, and one in several profiles asks which.

## Menu bar and login

- **cc-profiles → Show in Menu Bar** adds the mascot to the menu bar: it says whether the server is running and lists your ten most recent projects, each opening in a terminal with Claude Code (a project in several profiles asks which). Closing the window then keeps the app running there, out of the Dock.
- **cc-profiles → Open at Login** (macOS 13 or later) starts the app when you log in. With the menu bar icon on, it waits there without opening a window.

The app runs the `cc-profiles` you installed, with pipx, uv, Homebrew or pip, so it always has the same version. When cc-profiles is updated, or installed again another way, its next start rewrites the app to match, with a backup. An app you delete stays deleted: `cc-profiles install-app` adds it back.

To use another port, `cc-profiles install-app --port 4800`.

## Why macOS opens it without asking

Apps downloaded from the internet need Apple's signature, or macOS stops them the first time. This one is not downloaded: `cc-profiles install-app` puts it together on your Mac from files that came with cc-profiles (the compiled window, written in Swift, and an icon drawn in Python), so macOS opens it right away. It carries only an ad hoc signature, made on your Mac, no Apple identity. Its source is [`src/cc_profiles/app/main.swift`](https://github.com/andreaiannarone/cc-profiles/blob/main/src/cc_profiles/app/main.swift).

## If it does not start

The window says why, with the output of cc-profiles. The usual reason is that Homebrew updated Python and the environment pipx or uv installed cc-profiles in points to a Python that is gone: see [Troubleshooting](troubleshooting.md#bad-interpreter--no-such-file-or-directory-after-a-python-update).

## Remove it

Move it to the Trash, or run `cc-profiles uninstall`, which removes it with the rest of cc-profiles. Your profiles are not touched either way.
