# Mac app

On macOS, cc-profiles can live in Applications as an app of its own: a window with its icon in the Dock, found in Spotlight and Launchpad, instead of a tab in your browser.

```sh
cc-profiles install-app
```

Or click **Add Mac app** in the About panel (ⓘ), which also says whether the app is there and up to date. Either way it creates `~/Applications/cc-profiles.app`. Open it like any other app, and keep it in the Dock if you like. It is the same cc-profiles: the window shows the page you know, and the browser keeps working too.

## How it works

- **Opening the app** starts the server in the background unless it is already running, as `/cc-profiles` does, and shows it in the window. If the server was already running (started by `/cc-profiles` or `cc-profiles open`), the app uses it.
- **Closing the window, or ⌘Q,** quits the app. If the app started the server, the server stops too, after any change in progress; one it found running stays on.
- **Links to other sites** (the documentation, GitHub, claude.ai) open in your default browser. **View → Open in Browser** (⇧⌘O) opens the page there too.
- **Exports** (a profile's `.zip`, the usage CSV) go to your Downloads folder, under a new name if a file with that name is already there.
- **⌘R** reloads the page. If the server was stopped meanwhile, **Try again** starts it.

The app runs the `cc-profiles` you installed, with pipx, uv, Homebrew or pip, so it always has the same version. When cc-profiles is updated, or installed again another way, its next start rewrites the app to match, with a backup. An app you delete stays deleted: `cc-profiles install-app` adds it back.

To use another port, `cc-profiles install-app --port 4800`.

## Why macOS opens it without asking

Apps downloaded from the internet need Apple's signature, or macOS stops them the first time. This one is not downloaded: `cc-profiles install-app` puts it together on your Mac from files that came with cc-profiles (the compiled window, written in Swift, and an icon drawn in Python), so macOS opens it right away. It carries only an ad hoc signature, made on your Mac, no Apple identity. Its source is [`src/cc_profiles/app/main.swift`](https://github.com/andreaiannarone/cc-profiles/blob/main/src/cc_profiles/app/main.swift).

## If it does not start

The window says why, with the output of cc-profiles. The usual reason is that Homebrew updated Python and the environment pipx or uv installed cc-profiles in points to a Python that is gone: see [Troubleshooting](troubleshooting.md#bad-interpreter--no-such-file-or-directory-after-a-python-update).

## Remove it

Move it to the Trash, or run `cc-profiles uninstall`, which removes it with the rest of cc-profiles. Your profiles are not touched either way.
