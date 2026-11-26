# CLAUDE.md

All project rules live in AGENTS.md, so every coding agent follows the same ones:

@AGENTS.md

## Claude Code specifics

- **Console preview:** `.claude/launch.json` starts the console as `powershock-console` (port 8765). Use the browser preview in **Practice** mode to check page changes, and read the browser console for errors.
- **Before you commit:** run `cd pc; python -m unittest` and `python pc\tools\privacy_check.py`. Both must pass. Then look at any new screenshots yourself.
- **Shell:** on Windows, prefer the Edit/Write tools over shell heredocs for code that contains backslashes. Shell quoting can silently change `\n` or `\\`.
- **Hardware:** never upload to the brick, change its WiFi, or touch Windows Bluetooth settings without the owner's go-ahead. Log every such change in `docs/DEVICE_LOG.md` with undo steps.
