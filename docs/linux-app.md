# Linux app

On Linux with a desktop (GNOME, KDE, Xfce and the others), cc-profiles puts itself in your applications menu, with its icon. Clicking it starts cc-profiles if it is not running, and shows the page in a window of its own, with no tabs and no address bar, instead of a tab in your browser.

It is added by itself the first time cc-profiles starts on Linux, with a backup: a desktop entry in `~/.local/share/applications/cc-profiles.desktop` and the icon in `~/.local/share/icons/hicolor/256x256/apps/`. If you delete it, it stays deleted; to add it back, click **Add to applications menu** in the About panel (ⓘ), which also says whether the entry is there and up to date, or run:

```sh
cc-profiles install-app
```

To keep it from being added at all, run `cc-profiles install-app --off` before the first start (`"linux_app": false` in `config.json`).

## The window

The window is your browser in app mode (`--app`): Google Chrome, Chromium, Microsoft Edge, Brave or Vivaldi, the first one found. With none of them installed, the menu entry opens cc-profiles in your default browser, and the About panel says so. `/cc-profiles` and `cc-profiles open` show the same window while the entry is there.

The window uses the browser's own profile, so it has your bookmarks and extensions available, but it shows only cc-profiles.

## What it does not have

The [Mac app](mac-app.md) is a program of its own; on Linux cc-profiles adds no program, only the menu entry. So it does not stop the server when the window closes (stop it with `cc-profiles stop`), and has no menu bar icon, dropped files, recent projects or Open at Login. Everything inside the page is the same.

## Updates and removal

The server rewrites the entry when it starts, if the version, the `cc-profiles` command or the port changed; only an entry with `X-CC-Profiles-Managed=true` is ever rewritten or removed. `cc-profiles uninstall` removes it with its icon. Under WSL there is no Linux desktop, so no entry is added: open `http://127.0.0.1:4777` in your Windows browser.
