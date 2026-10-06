---
description: Open the cc-profiles web UI to manage your Claude Code profiles
argument-hint: "[restart|stop]"
allowed-tools: Bash(cc-profiles open:*)
---
!`cc-profiles open $ARGUMENTS`

Tell the user, in one short line, what the output above says: the URL where cc-profiles is open; that it was restarted, and that they should reload the page; that it was stopped or was not running; or why it did not start or stop.

If the output says the action is unknown, say that this command accepts nothing, `restart` or `stop`.

If the `cc-profiles` command was not found, say that this command only opens the app and does not install it, and give this install command:

```sh
curl -fsSL https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/install.sh | sh
```
