# AGENTS.md

These are instructions for anyone changing PowerShock: coding agents (Codex, Claude Code, others) and people. Read all of it before your first change. [README.md](README.md) covers what the app does.

## What this is

PowerShock drives a LEGO EV3 (leJOS 0.9.1-beta, **Java 7**) with a PS4 DualShock 4, through a local web console on a Windows laptop.

| Part | Where | Language / limits |
|---|---|---|
| Console server | `pc/ev3_console.py` and the other `pc/*.py` | Python 3.9+, **standard library only** |
| Console page | `pc/console/index.html` (one file: HTML, CSS, JS), `ds4model.js`, `gears3d.js` | Plain JS, no build step; three.js is vendored in `pc/console/vendor/three/` |
| Brick programs | `ev3/src/powershock/*.java` | **Java 7 language and API only**: no lambdas, streams, `java.time`, try-with-resources on non-`AutoCloseable` types, or `String.join` |
| Build | `build.ps1` | PowerShell; compiles against `lib/rt7.jar` so any Java 8+ API is a compile error |

## Commands

```powershell
cd pc; python -m unittest          # all tests; no hardware needed; must pass before any commit
python pc\tools\privacy_check.py   # must say "clean" before any commit
.\build.ps1                        # builds out\*.jar (needs lib\*.jar, see README)
python pc\ev3_console.py           # console on http://127.0.0.1:8765; use Practice mode without a brick
```

## Rules that are never broken

### 1. No private or sensitive data in the repository

The repository is public. Before every commit:

1. **Run the checks.** `python pc\tools\privacy_check.py` must say `clean`, and `python -m unittest` must pass (it runs the same check).
2. **Look at every new or changed image yourself.** Screenshots can show:
   - Bluetooth addresses
   - network names, IP addresses
   - user names, e-mail addresses
   - other people's devices

   Take screenshots in **Practice** mode, and blank out anything personal before adding them.
3. **Never commit these.** Each is covered by `.gitignore`; never force-add them:
   - **Device data:** MAC/Bluetooth addresses of real devices; IP addresses other than `127.0.0.1` and leJOS's `10.0.1.1`.
   - **Personal data:** WiFi network names, WiFi passwords or WPA keys, e-mail addresses, names, Windows user folders (`C:\Users\<name>`).
   - **Secrets:** tokens, API keys, private keys, `.env` files.
   - **Files:**
     - `sd_lejos/`, `sd_backup*`, `lib/*.jar` and anything from the leJOS SD card. Oracle's Java runtime may not be redistributed.
     - `out/` (build output).
     - `pc/mapping.json` (a user's own controls).
     - `docs/DEVICE_LOG.md` (a user's own brick history).
     - `.private-terms`.
4. **Examples and tests** use placeholders: `HomeNetwork`, `00:00:00:00:00:00`, `AA:BB:CC:DD:EE:FF`, `192.168.1.40`, `<brick address>`.
5. **Logs and errors** must never contain passwords or keys. The WiFi password is turned into a WPA key on the laptop and never stored, logged or sent.
6. **Found private data already committed?** Stop and tell the owner. Removing it from history needs their decision.

`.private-terms` (git-ignored) lists each developer's own private words, which the check also refuses. Add yours to it.

### 2. Safety: a robot must never move unexpectedly

- **Motors stop** within 500 ms when commands stop (brick watchdog), at once when the connection drops, and when the controller disconnects or the page loses focus.
- **After a dropped link,** **Motors on** stays off until the user turns it on again.
- **Stop always wins:** a late input message must not undo it.
- **Brick-side limits:**
  - Speeds are clamped to ±100, angles to ±720°, and test turns to ±3600° with a time limit.
  - Input lines are capped at 256 characters, and at most 32 tests can be queued.
- Any change to these paths needs a test (see `pc/test_link.py`) and a mention under **Fixed** or **Security** in the changelog.

### 3. Security of the console

- **Network exposure:**
  - The console listens on `127.0.0.1` only.
  - It checks `Host` and `Origin` exactly.
  - Every `/api/` call needs `X-PowerShock: 1` or `Sec-Fetch-Site: same-origin`.

  Don't loosen any of this, add CORS headers, or listen on other interfaces.
- **Request bodies** are capped at 64 KB. Validate every field the page sends, and treat it as untrusted.
- **Output and commands:**
  - Escape all text put into HTML (`esc()` in the page).
  - Never build shell commands from user input. Pass arguments as lists, as `ev3_brick.py` does.
- **No new dependencies** without the owner's OK. That means no pip packages, CDNs or remote scripts; the page works offline.

### 4. The brick and the user's machine

- **Ask first:** don't upload to, run on, or change settings on a real EV3, or change Windows settings or drivers, without the owner's explicit OK.
- **Record it:** log every change in `docs/DEVICE_LOG.md` (local, not published) with how to undo it.
- **Passwords:** never type or store one for the user.

## Making a change

1. **Understand first.** Read the code around the change and the tests that cover it.
2. **Keep it small and focused.** Don't reformat unrelated code or rename for taste.
3. **Tests (required):**
   - Every bug fix gets a test that fails without the fix.
   - Every new behaviour in `pc/*.py` gets tests in `pc/test_*.py`.
   - Tests need no hardware: use the practice brick (`FakeEV3`) or a local socket, as `test_link.py` and `test_version.py` do.
   - Turn Practice off in any running console first. Its pretend brick holds port 5000, which the tests' own pretend brick also uses.
   - Keep tests fast (seconds) and deterministic.
   - Java has no test harness. Keep brick logic simple, and check it through the console's practice brick and by reasoning. Describe what you checked on real hardware, if anything.
4. **Brick protocol changes:**
   - Lines from the PC are `P`, `M` and the old `l r a`. Lines from the brick are `V` and `T`.
   - A `T` line ends with optional items: `mB=tacho:speed:stalled:role` for motors, and `s4=ir:37` / `s2=us:123` / `s3=col:5` / `s1=gy:-45` for sensors.
   - Change both sides together, plus the practice brick in `ev3_console.py`.
   - Keep older versions working where you can: unknown lines are ignored.
5. **The page:**
   - **Writing:** plain words, sentence case, buttons say what they do ("Upload latest build", not "Submit"). Errors say what happened and what to do.
   - **Testing:** check the page in a browser with Practice mode on. Look at the browser console for errors.
   - **Responsive:** check narrow widths (≤ 860 px).
   - **Accessibility:** keep keyboard access, focus outlines, `aria-label`s and `prefers-reduced-motion`.
   - **Performance:** the page polls every 250 ms. Don't rewrite large `innerHTML` blocks when nothing changed (use `setHTML`).
6. **Docs:** update `README.md` and `docs/TROUBLESHOOTING.md` when behaviour or setup changes.
7. **Changelog:** add a line under `## [Unreleased]` in `CHANGELOG.md` for anything a user would notice (Added / Changed / Fixed / Security / Removed).

## Versioning and releases

- **Semantic Versioning,** one version for the whole app, in `VERSION`.
  - **Where it's read:** `pc/version.py` reads it, and `build.ps1` stamps it into the jars (`powershock/version.txt`).
  - **Where it shows:** the brick program reports it (`V <version>`), and the console shows it.
- **Don't bump the version** in an ordinary change. Releases are cut on purpose, following "Making a release" in `CHANGELOG.md`.
- `pc/test_version.py` checks that `VERSION` matches the newest changelog entry.
- **Before 1.0.0:** a minor bump may change the brick protocol; patch bumps are fixes only.

## Style

- **Python:**
  - Standard library only.
  - Follow the existing style: short docstrings that say why, and 4-space indents.
  - Lines up to about 120 characters.
  - Locks are held only for short sections. No blocking network calls while holding `Link.lock`.
- **Java:**
  - Java 7 only.
  - Only the main loop drives motors; other threads queue work.
  - Catch `Throwable` around network handling, so one bad client can't stop the receiver.
- **JS:**
  - No frameworks.
  - `const`/`let`, small functions, and `$()` for `getElementById`.
  - Keep state in `S`.
- **Comments** explain why, not what. No commented-out code.

## Commits and pull requests

- **Branch** from `main`; never push to `main` directly unless the owner asks.
- **One logical change per commit.** Write messages in the imperative ("Add stick calibration"), with a short body when the why isn't obvious.
- **Before committing:** tests pass, the privacy check is clean, `.\build.ps1` succeeds if Java changed, the changelog is updated, and images have been checked by eye.
- **Pull requests** say what changed, why, and how it was tested (tests, Practice mode, or real hardware).
- **Ask the owner before:**
  - pushing or opening a pull request
  - publishing anything, creating releases or tags
  - changing repository settings
