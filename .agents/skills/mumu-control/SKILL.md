---
name: mumu-control
description: Control MuMu Android Emulator (Player 12) on Windows — find installation path, manage emulator instances, launch/shutdown, connect ADB, intelligent UI recognition (OCR + accessibility tree), tap/swipe/text input, and automate games.
version: 1.2
author: MuMu
license: MIT
os: windows
---

# MuMu Emulator Control

Control MuMu Player 12 (Netease) Android emulator on Windows using `mumu-cli.exe` CLI and Python automation scripts (`uiautomator2` + `RapidOCR`).

> ⚠️ **Windows only.**

**Two layers:**

| Layer | Tool | Addressing | Purpose |
|-------|------|------------|---------|
| Instance management | `mumu-cli.exe` | `--vmindex N` | Launch, shutdown, settings, import/export |
| UI automation | Python scripts (`scripts/`) | `-s <serial>` | Screenshot, tap, swipe, OCR, text input |

> **Note:** `mumu-cli.exe` is the new CLI name (replaces the legacy `MuMuManager.exe`). If `mumu-cli.exe` is not found in `nx_main\`, fall back to `MuMuManager.exe` — they are functionally identical.

---

## Before You Start

### 1. Find MuMu Installation Path

**MuMuInstallPath** = root directory (e.g., `D:\Program Files\Netease\MuMu Player 12`).

Detection chain (try in order, stop on first success):

1. **Cached path** — read `mumu_install_path.txt` in skill directory, validate `<path>\nx_main\mumu-cli.exe` (or `MuMuManager.exe`) exists
2. **Registry** — `reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\MuMuPlayer" /v UninstallString` → strip `\uninstall.exe`
3. **Default paths** — probe `C:\Program Files\Netease\MuMu Player 12`, `D:\Program Files\...`, `C:\Program Files (x86)\...`
4. **Ask user** — prompt for path manually
5. **Install** — offer to download from `https://mumu.163.com/`

On success, save to cache:
```cmd
echo <MuMuInstallPath> > "mumu_install_path.txt"
```

### Key Paths

| Tool | Path |
|------|------|
| mumu-cli | `<MuMuInstallPath>\nx_main\mumu-cli.exe` |
| ADB | `<MuMuInstallPath>\nx_main\adb.exe` |
| Instance data | `<MuMuInstallPath>\vms\MuMuPlayer-12.0-<index>\` |

> **Always use the bundled `adb.exe`** from `nx_main\` to avoid version conflicts.

```cmd
cd /d "<MuMuInstallPath>\nx_main"
```

### 2. Install Python Dependencies

```cmd
pip install -r requirements.txt
```

### 3. Initialize uiautomator2

First-time setup — installs `atx-agent` onto the device:

```cmd
python -m uiautomator2 init
```

> Only needed once per device. Re-run after device reset.

---

## mumu-cli Reference

`mumu-cli.exe` (aka `MuMuManager.exe`) is the command-line interface for managing MuMu Player 12 instances. All instance operations — launch, shutdown, app management, settings — go through this binary.

> 📖 **Official documentation:** https://mumu.163.com/redirect/nx/function/mumucli/

**Binary location:** `<MuMuInstallPath>\nx_main\mumu-cli.exe`

**General syntax:**
```
mumu-cli.exe <command> [--vmindex <N>] [subcommand]
```

**`--vmindex` targeting rules:**

| Value | Meaning |
|-------|---------|
| `--vmindex 0` | Single instance (index 0) |
| `--vmindex 0,2,4` | Multiple specific instances |
| `--vmindex all` | All existing instances |

> Short form: `-v` is alias for `--vmindex`, e.g. `-v 0` = `--vmindex 0`

### Complete Command Table

| Command | Subcommand | Description |
|---------|-----------|-------------|
| `info` | — | Query instance status, ADB port, boot state |
| `create` | — | Create a new emulator instance |
| `clone` | — | Clone an existing instance |
| `delete` | — | Delete an instance |
| `rename` | — | Rename an instance |
| `export` | — | Export instance to `.mumudata` backup file |
| `import` | — | Import instance from backup file |
| `setting` | — | Get or set emulator configuration (resolution, etc.) |
| `simulation` | — | Simulate device info (android_id, IMEI, etc.) |
| `control` | `launch` | Launch emulator |
| `control` | `shutdown` | Shutdown emulator |
| `control` | `restart` | Restart emulator |
| `control` | `show_window` | Show emulator window |
| `control` | `hide_window` | Hide emulator window (background mode) |
| `control` | `layout_window` | Set window position and size |
| `control` | `app install` | Install APK (supports .apk / .xapk / .apks) |
| `control` | `app uninstall` | Uninstall app by package name |
| `control` | `app launch` | Launch an app by package name |
| `control` | `app close` | Force-stop a running app |
| `control` | `app info` | Query app state or list installed apps |
| `control` | `tool func` | Trigger toolbar actions (rotate, home, back, screenshot…) |
| `control` | `tool downcpu` | Limit CPU usage (1–100%) |

---

### Top 10 Most Common Commands

#### 1. `info` — Query Emulator Status

Check instance readiness before every operation. Returns JSON with port, state, and boot status.

```cmd
:: Query single instance
mumu-cli.exe info --vmindex 0

:: Query all instances
mumu-cli.exe info --vmindex all
```

**Key output fields:**

| Field | Meaning | Available |
|-------|---------|-----------|
| `index` | vmindex used in other commands | Always |
| `name` | Instance display name | Always |
| `is_process_started` | `true` = emulator process is running | Always |
| `is_android_started` | `true` = Android OS fully booted | Always |
| `player_state` | `start_finished` = fully running | **Running only** |
| `adb_host_ip` | ADB host (usually `127.0.0.1`) | **Running only** |
| `adb_port` | ADB port (index 0 → `16384`, index N → `16384 + N×2`) | **Running only** |
| `pid` | Emulator process ID | **Running only** |

> ✅ **Ready condition:** `player_state == "start_finished"` **AND** `is_android_started == true`
>
> ⚠️ Fields marked **Running only** are absent when the instance is stopped. Always check `is_android_started` before reading `adb_port`.

---

#### 2. `control launch` — Launch Emulator

```cmd
:: Launch single instance
mumu-cli.exe control --vmindex 0 launch

:: Launch multiple instances
mumu-cli.exe control --vmindex 0,1,2 launch

:: Launch all instances
mumu-cli.exe control --vmindex all launch
```

> After launch, poll `info` until `is_android_started: true` before sending any ADB/UI commands.

---

#### 3. `control shutdown` — Shutdown Emulator

```cmd
:: Shutdown single instance
mumu-cli.exe control --vmindex 0 shutdown

:: Shutdown multiple instances
mumu-cli.exe control --vmindex 0,1,2 shutdown

:: Shutdown all instances
mumu-cli.exe control --vmindex all shutdown
```

---

#### 4. `control restart` — Restart Emulator

Use when instance is frozen, crashed, or behaving unexpectedly.

```cmd
:: Restart single instance
mumu-cli.exe control --vmindex 0 restart

:: Restart multiple instances
mumu-cli.exe control --vmindex 0,1,2 restart

:: Restart all instances
mumu-cli.exe control --vmindex all restart
```

---

#### 5. `control hide_window` / `show_window` — Background Mode

Run automation silently without a visible window to save screen space and resources.

```cmd
:: Hide window (switch to background)
mumu-cli.exe control --vmindex 0 hide_window

:: Show window again
mumu-cli.exe control --vmindex 0 show_window

:: Batch hide all instances
mumu-cli.exe control --vmindex all hide_window
```

---

#### 6. `control app launch` — Launch App

```cmd
:: Launch app in single instance
mumu-cli.exe control --vmindex 0 app launch --package com.example.game

:: Launch in multiple instances
mumu-cli.exe control --vmindex 0,1,2 app launch --package com.example.game

:: Launch in all instances
mumu-cli.exe control --vmindex all app launch --package com.example.game
```

---

#### 7. `control app install` — Install APK

Supports `.apk`, `.xapk`, `.apks` formats. Batch install to multiple instances in one command.

```cmd
:: Install to single instance
mumu-cli.exe control --vmindex 0 app install --apk "C:\path\to\app.apk"

:: Install to multiple instances
mumu-cli.exe control --vmindex 0,1,2 app install --apk "C:\path\to\app.apk"

:: Install to all instances
mumu-cli.exe control --vmindex all app install --apk "C:\path\to\app.apk"

```

---

#### 8. `control app close` — Close App

Force-stop a running app (equivalent to `am force-stop`).

```cmd
:: Close app in single instance
mumu-cli.exe control --vmindex 0 app close --package com.example.game

:: Close in multiple instances
mumu-cli.exe control --vmindex 0,1,2 app close --package com.example.game

:: Close in all instances
mumu-cli.exe control --vmindex all app close --package com.example.game
```

**Related app subcommands:**

```cmd
:: Query app state: returns running / stopped / not_installed
mumu-cli.exe control --vmindex 0 app info --package com.example.game

:: List active app (returns {"active": "<package>"})
mumu-cli.exe control --vmindex 0 app info --installed

:: Uninstall app
mumu-cli.exe control --vmindex 0 app uninstall --package com.example.game
```

---

#### 9. `create` / `clone` — Create or Clone Instance

```cmd
:: Create new instance (auto index)
mumu-cli.exe create

:: Create at specific index
mumu-cli.exe create --vmindex 2

:: Clone an existing instance
mumu-cli.exe clone --vmindex 0

:: Rename an instance
mumu-cli.exe rename --vmindex 0 --name "Bot-1"

:: Delete an instance
mumu-cli.exe delete --vmindex 1
```

---

#### 10. `setting` — Configure Emulator

Get or set emulator properties (resolution, rendering mode, etc.).

> ⚠️ **Settings can only be written when the instance is STOPPED.** Writing while running returns `key not writable`. Always `shutdown` first, then modify settings, then `launch` again.

```cmd
:: List all settings for an instance
mumu-cli.exe setting --vmindex 0 --all

:: Get individual settings (resolution is three separate keys)
mumu-cli.exe setting --vmindex 0 --key resolution_width    :: returns e.g. "1600.000000"
mumu-cli.exe setting --vmindex 0 --key resolution_height
mumu-cli.exe setting --vmindex 0 --key resolution_dpi

:: Set resolution — shutdown instance first, then set each key
mumu-cli.exe control --vmindex 0 shutdown
mumu-cli.exe setting --vmindex 0 --key resolution_width --value 1080
mumu-cli.exe setting --vmindex 0 --key resolution_height --value 1920
mumu-cli.exe setting --vmindex 0 --key resolution_dpi --value 480
mumu-cli.exe control --vmindex 0 launch

:: Apply same setting to multiple instances
mumu-cli.exe setting --vmindex 0,1,2 --key resolution_width --value 1080
mumu-cli.exe setting --vmindex 0,1,2 --key resolution_height --value 1920
mumu-cli.exe setting --vmindex 0,1,2 --key resolution_dpi --value 480
```

**Common resolution presets (from `--all` output):**

| Mode | Width | Height | DPI |
|------|-------|--------|-----|
| Tablet 1080p | 1920 | 1080 | 280 |
| Tablet 900p *(default)* | 1600 | 900 | 240 |
| Tablet 720p | 1280 | 720 | 240 |
| Phone 1080p | 1080 | 1920 | 480 |
| Phone 720p | 720 | 1280 | 320 |

---

### Other Useful CLI Commands

```cmd
:: Device simulation — change device fingerprint
mumu-cli.exe simulation --vmindex 0 --simu_key android_id --simu_value <new_id>
mumu-cli.exe simulation --vmindex 0 --simu_key android_id --simu_value __null__  # reset

:: Export / Import instance backup
mumu-cli.exe export --vmindex 0 --dir "C:\backups"
mumu-cli.exe import --vmindex 1 --path "C:\backups\backup.mumudata"

:: Toolbar functions (trigger via CLI)
mumu-cli.exe control --vmindex 0 tool func --name screenshot   # take screenshot
mumu-cli.exe control --vmindex 0 tool func --name rotate       # rotate screen
mumu-cli.exe control --vmindex 0 tool func --name go_home      # press Home
mumu-cli.exe control --vmindex 0 tool func --name go_back      # press Back
mumu-cli.exe control --vmindex 0 tool func --name top_most     # pin window on top
mumu-cli.exe control --vmindex 0 tool func --name fullscreen   # fullscreen toggle
mumu-cli.exe control --vmindex 0 tool func --name shake        # shake gesture
mumu-cli.exe control --vmindex 0 tool func --name volume_up    # volume up
mumu-cli.exe control --vmindex 0 tool func --name volume_down  # volume down
mumu-cli.exe control --vmindex 0 tool func --name volume_mute  # mute toggle

:: Set window position and size
mumu-cli.exe control --vmindex 0 layout_window --pos_x 100 --pos_y 100 --size_w 1280 --size_h 720

:: Limit CPU usage (1–100%)
mumu-cli.exe control --vmindex 0 tool downcpu --cap 50
```

---

## ADB Connection

From `info` JSON: serial = `<adb_host_ip>:<adb_port>` (e.g., `127.0.0.1:16384`).

```cmd
.\adb.exe connect 127.0.0.1:16384
.\adb.exe devices
:: Expected: 127.0.0.1:16384    device

:: Troubleshoot: reset ADB
.\adb.exe kill-server && .\adb.exe start-server && .\adb.exe connect 127.0.0.1:16384
```

---

## UI Automation — Python Scripts

> All scripts are in `scripts/`. Default serial: `127.0.0.1:16384` (override with `-s <serial>`).
> Default output: `./tmp/mumu-control/`.
> Examples below omit `-s` for brevity — add it when using non-default serial.

### Recommended Automation Loop

```
1. uiscan.py  → Screenshot + UI recognition → Annotated image
2. AI reads UI recognition → Annotated image → Find target via visual understanding and element annotations
3. tap.py     → Tap target (by coords or text match)
4. uiscan.py  → Verify result
5. Wait → Repeat
```

**Simplest path (recommended):** `python scripts/tap.py --text "Collect"` — auto screenshot → OCR → tap

> ⚠️ NEVER tap without a prior screenshot/scan.

---

### uiscan.py — Screenshot + UI Element Recognition

Dual-source recognition: accessibility tree (`dump_hierarchy`) + RapidOCR. Results merged (hierarchy priority).

**Output:** `{name}.png` (annotated) + `{name}_elements.json` (structured data)

```cmd
:: Full scan (hierarchy + OCR)
python scripts/uiscan.py

:: Custom output
python scripts/uiscan.py -o ./output -n game_state

:: Partial modes
python scripts/uiscan.py --screenshot-only
python scripts/uiscan.py --no-ocr          # hierarchy only (fast)
python scripts/uiscan.py --no-hierarchy     # OCR only (game engines)
```

**Output JSON example:**
```json
[
  {
    "index": 0, "name": "Collect Reward", "control_type": "Button",
    "coords": {"x": 540, "y": 960}, "size": {"width": 200, "height": 60},
    "resource_id": "com.game:id/collect_btn", "clickable": true
  },
  {
    "index": 1, "name": "Daily Check-in", "control_type": "OCRText",
    "coords": {"x": 300, "y": 400}, "size": {"width": 120, "height": 30}
  }
]
```

---

### tap.py — Tap

```cmd
:: By coordinates
python scripts/tap.py 540 960

:: By text (auto screenshot → OCR → find → tap) — RECOMMENDED for games
python scripts/tap.py --text "Collect"

:: Long press
python scripts/tap.py 540 960 --long --duration 3.0
python scripts/tap.py --text "Enhance" --long
```

---

### swipe.py — Swipe / Scroll

```cmd
:: By coordinates: x1 y1 x2 y2
python scripts/swipe.py 540 1400 540 400

:: By direction (auto-calculates based on screen size)
python scripts/swipe.py --direction up|down|left|right

:: Custom speed
python scripts/swipe.py --direction up --duration 1.0
```

---

### keyevent.py — Hardware Key Events

```cmd
python scripts/keyevent.py home|back|enter|power|escape|tab|space|delete|recent
python scripts/keyevent.py volume_up|volume_down|volume_mute
python scripts/keyevent.py dpad_up|dpad_down|dpad_left|dpad_right
python scripts/keyevent.py 26    # by numeric keycode
```

---

### input_text.py — Text Input (Supports Chinese/Unicode)

Default: **clears existing text** before input. Use `--append` to append.

```cmd
:: Method 1: Resource ID (most reliable — recommended)
python scripts/input_text.py "Onmyoji" --res-id com.mumu.store:id/search_bar
python scripts/input_text.py "extra" --res-id com.mumu.store:id/search_bar --append

:: Method 2: Coordinates (when no resource ID available)
python scripts/input_text.py "hello" --coord 500 800
python scripts/input_text.py "more" --coord 500 800 --append

:: Method 3: Legacy (requires field already focused)
python scripts/input_text.py "hello world"
```

**Finding Resource ID:** Run `uiscan.py`, look for `resource_id` in output JSON or table.

---

### screenshot.py — Simple Screenshot

```cmd
python scripts/screenshot.py
python scripts/screenshot.py -o ./captures/screen1.png
```

> For screenshots + element recognition, use `uiscan.py` instead.

---

## App Management via ADB

For fine-grained single-instance control, use ADB directly:

```cmd
:: Install APK
.\adb.exe -s 127.0.0.1:16384 install app.apk

:: List installed 3rd-party packages
.\adb.exe -s 127.0.0.1:16384 shell pm list packages -3

:: Force stop app
.\adb.exe -s 127.0.0.1:16384 shell am force-stop com.example.app

:: Uninstall app
.\adb.exe -s 127.0.0.1:16384 uninstall com.example.app
```

> 💡 Prefer `mumu-cli.exe control --vmindex N app ...` for **batch multi-instance** operations. Use ADB for fine-grained control on a single instance.

---

## Quick Reference

| Action | Command |
|--------|---------|
| **Setup** | |
| Install deps | `pip install -r requirements.txt` |
| Init u2 | `python -m uiautomator2 init` |
| **mumu-cli — Instances** | |
| List all instances | `mumu-cli.exe info --vmindex all` |
| Query single | `mumu-cli.exe info --vmindex 0` |
| Create instance | `mumu-cli.exe create --vmindex 2` |
| Clone instance | `mumu-cli.exe clone --vmindex 0` |
| Rename instance | `mumu-cli.exe rename --vmindex 0 --name "Bot-1"` |
| Delete instance | `mumu-cli.exe delete --vmindex 1` |
| Export backup | `mumu-cli.exe export --vmindex 0 --dir "C:\backups"` |
| Import backup | `mumu-cli.exe import --vmindex 1 --path "C:\backups\backup.mumudata"` |
| **mumu-cli — Lifecycle** | |
| Launch | `mumu-cli.exe control --vmindex 0 launch` |
| Shutdown | `mumu-cli.exe control --vmindex 0 shutdown` |
| Restart | `mumu-cli.exe control --vmindex 0 restart` |
| Hide window | `mumu-cli.exe control --vmindex 0 hide_window` |
| Show window | `mumu-cli.exe control --vmindex 0 show_window` |
| **mumu-cli — Apps** | |
| Install APK | `mumu-cli.exe control --vmindex 0 app install --apk "C:\app.apk"` |
| Launch app | `mumu-cli.exe control --vmindex 0 app launch --package <pkg>` |
| Close app | `mumu-cli.exe control --vmindex 0 app close --package <pkg>` |
| App status | `mumu-cli.exe control --vmindex 0 app info --package <pkg>` |
| Active app | `mumu-cli.exe control --vmindex 0 app info --installed` |
| Uninstall app | `mumu-cli.exe control --vmindex 0 app uninstall --package <pkg>` |
| **mumu-cli — Settings** | |
| Get all settings | `mumu-cli.exe setting --vmindex 0 --all` |
| Get resolution | `mumu-cli.exe setting --vmindex 0 --key resolution_width` |
| Set resolution *(shutdown first)* | `mumu-cli.exe setting -v 0 --key resolution_width --value 1080` |
| Limit CPU | `mumu-cli.exe control --vmindex 0 tool downcpu --cap 50` |
| Set window layout | `mumu-cli.exe control --vmindex 0 layout_window -px 0 -py 0 -sw 1280 -sh 720` |
| **ADB** | |
| Connect | `.\adb.exe connect 127.0.0.1:16384` |
| List devices | `.\adb.exe devices` |
| Reset ADB | `.\adb.exe kill-server && .\adb.exe start-server` |
| **UI Automation** | |
| Full UI scan | `python scripts/uiscan.py` |
| Screenshot | `python scripts/screenshot.py` |
| Tap coords | `python scripts/tap.py 540 960` |
| Tap text (OCR) | `python scripts/tap.py --text "Collect"` |
| Long press | `python scripts/tap.py 540 960 --long` |
| Swipe direction | `python scripts/swipe.py --direction up` |
| Swipe coords | `python scripts/swipe.py x1 y1 x2 y2` |
| Key event | `python scripts/keyevent.py back` |
| Text input | `python scripts/input_text.py "hello" --res-id <id>` |

---

## Verify Setup

Run in order with your `<serial>` (default `127.0.0.1:16384`):

| # | Check | Command | Pass |
|---|-------|---------|------|
| 1 | Binaries exist | `dir "<MuMuInstallPath>\nx_main\mumu-cli.exe"` | File found |
| 2 | Instance info | `mumu-cli.exe info --vmindex 0` | Valid JSON |
| 3 | ADB connected | `.\adb.exe connect <serial> && .\adb.exe devices` | Shows `device` |
| 4 | Python deps | `python -c "import uiautomator2; import rapidocr_onnxruntime; print('OK')"` | Prints `OK` |
| 5 | Screenshot | `python scripts/screenshot.py -o ./test.png` | PNG created |
| 6 | UIScan | `python scripts/uiscan.py -o ./ -n test` | Annotated PNG + JSON |
| 7 | Tap by text | `python scripts/tap.py --text "<visible_text>"` | Found and tapped |

---

## Troubleshooting

| Symptom | Resolution |
|---------|-----------|
| `mumu-cli.exe` not found | Re-run detection chain; delete `mumu_install_path.txt` |
| `info` error | `mumu-cli.exe create --vmindex 0` |
| ADB `offline` | Launch instance first; check `player_state` via `info` |
| ADB `unauthorized` | Accept USB debugging dialog in emulator |
| Blank screenshot | Wait for `is_android_started: true` |
| `import` fails | `pip install -r requirements.txt` |
| No elements in uiscan | `python -m uiautomator2 init` |
| `--text` not found | Use `uiscan.py` to verify visible text first |
| Chinese input broken | Use `input_text.py` (not raw `adb shell input text`) |
| ADB drops mid-session | `adb kill-server && adb start-server && adb connect <serial>` |
| Resolution not applied | Restart instance after `setting --key resolution --value ...` |
| App won't launch | Verify package name: `mumu-cli.exe control -v 0 app info --installed` |
| `key not writable` on setting | Shutdown instance first: `mumu-cli.exe control -v 0 shutdown` |
| long press fails (RemoteDisconnected) | Run `python -m uiautomator2 init` to reinstall atx-agent |
