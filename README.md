# AutoRewarder

![Stars](https://img.shields.io/github/stars/safarsin/AutoRewarder?style=for-the-badge)
![Downloads](https://img.shields.io/github/downloads/safarsin/AutoRewarder/total?style=for-the-badge&color=007ac)

An advanced, set-and-forget automation tool for Microsoft Rewards. AutoRewarder performs Bing searches for PC and mobile point collection, collects Daily Sets, and uses mathematically driven, human-like input simulation (W3C Actions, Bezier curves, and smart scrolling).

Built with a robust Python/Selenium backend, it offers two modes of operation: a sleek HTML/CSS/JS frontend wrapped in a native window via pywebview, and a headless runner (CLI) for scheduled background runs and automation scripts. Packaged as an executable Windows app (via Inno Setup) for a seamless, plug-and-play experience.

> **Ready to start? Check out the complete [USER GUIDE](USER_GUIDE.md)**

---

## Table of Contents

- [Installation](#installation)
- [Screenshots & Demo](#screenshots--demo)
- [Tech Stack](#tech-stack)
- [System Requirements](#system-requirements)
- [Features](#features)
- [Quick Start (For Users)](#quick-start-for-users)
- [Development Setup (For Developers)](#development-setup-for-developers)
- [CLI Usage](#cli-usage)
- [Build & Distribution](#build--distribution)
- [Project Structure](#project-structure)
- [Runtime Data](#runtime-data)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)

---

## Installation

**Easy Way (Recommended):**
Download `AutoRewarder-Setup.exe` from the [latest release](https://github.com/safarsin/AutoRewarder/releases/latest) and run it. The installer will verify all dependencies and install the app for you.

**Portable Way:**
Download `AutoRewarder.zip` from the [latest release](https://github.com/safarsin/AutoRewarder/releases/latest) and extract it to any folder (e.g., a USB drive). Run the executable. All your settings and profiles will be saved locally inside the `config` folder.
> **Note:** Because the portable version is a single-file build, it may take a few seconds longer to start up compared to the installed version while it unpacks core components. Once open, it works at full speed.

**Manual Way (Source):**
Clone this repo, create virtual environment, and run `python AutoRewarder.py`.

---

## Screenshots & Demo

| Perform Searches | App Demo |
| :---: | :---: |
|<img src="assets/screenshots/perform_demo.gif">|<img src="assets/screenshots/main_demo.gif">|

|Daily Sets| Tab Switching |
| :---: | :---: |
|<img src="assets/screenshots/daily_set.gif">|<img src="assets/screenshots/tab_perform.gif">|

> <sub>*Demo is sped up for viewing purposes. Actual execution includes randomized delays and pauses to mimic human behavior.*</sub>

| Main Window | Settings & History |
| :---: | :---: |
| <img src="assets/screenshots/main_2.png"> | <img src="assets/screenshots/history_window.png"> |
| <img src="assets/screenshots/main_1.png"> | <img src="assets/screenshots/settings.jpg"> |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12, [selenium](https://www.selenium.dev/), [pywebview](https://pywebview.flowrl.com/) |
| Frontend | HTML, CSS, JavaScript |
| Bridge | pywebview JS API (pywebview.api) |
| Build | [PyInstaller](https://pyinstaller.org/), [Inno Setup](https://jrsoftware.org/isinfo.php) |

---

## System Requirements

- **OS**: Windows 10 or later (installer), or Linux via source setup (no prebuilt executable)
- **Browser**: Microsoft Edge (driver managed by Selenium Manager)
- **.NET Framework**: 4.8 or higher (automatically checked by installer)
- **RAM**: Minimum 512 MB (1 GB recommended)
- **Disk Space**: ~50 MB

---

## Features

**User Experience & Interface:**
- Multi-account management (add, rename, delete, per-account profiles)
- First Setup per account with a dedicated Edge profile
- PC and Mobile query controls (0-130 / 0-99)
- Optional hide-browser mode (headless UI toggle)
- Per-account scheduled runs (simple or advanced)
- Start with Windows/Linux toggle (autostart)
- Live terminal-like logs with update notifications (GitHub Releases)
- Local history view per account (date, time, query, status)
- Safe recovery for corrupted settings/history files

**Automation & Core Logic:**
- Automatic start-up (launches headless runs on sign-in)
- Configurable run pacing (advanced scheduling with run duration and queries per hour)
- Background WebDriver warmup at startup for faster execution
- Human-like search behavior (typing delays, random pauses, smooth scrolling)
- Mobile emulation for Rewards credit (iPhone UA and touch)
- Uses real-world queries from assets/queries.json (8154 unique entries from google-trends dataset)
- Randomized delays to reduce repetitive patterns
- Optional tab switching between result categories (Images/Videos/News)
- Natural mouse movement/clicking (W3C Actions)
- Daily Set task collection (runs once per day, per account)
- Separate browser profile per account

**Developer & Code Quality:**
- Advanced documentation (comprehensive docstrings and detailed guides)
- Strict code formatting and static type checking (Black, Flake8, MyPy)

---

## Quick Start (For Users)

You do not need Python to use release builds.

1. Download `AutoRewarder-Setup.exe` from the latest release
2. Install and run the app
3. Add your first account and complete setup
4. Set PC/Mobile counts and start a run

For detailed guide, see [USER_GUIDE.md](USER_GUIDE.md)

---

## Development Setup (For Developers)

1. Clone the repository.
2. Create and activate a virtual environment.
3. Install dependencies.
4. Run the app.

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python AutoRewarder.py
```
---

## CLI Usage

For users who prefer the terminal or want to integrate the bot into custom scripts, a headless runner is available. It is the same engine used by the Start with Windows setting. You can call `AutoRewarder.py --headless` or run `AutoRewarder_CLI.py` directly (arguments are the same).

### Available CLI Arguments

These arguments can be combined. Without `--account`, it runs every enabled schedule sequentially.

| Argument | Type | Description | Default / Fallback |
| :--- | :--- | :--- | :--- |
| `--account` | String | Run only this account (by id or label). | Runs all enabled schedules. |
| `--pc` | Integer | Override PC queries for this run (requires `--account`). | Uses the account schedule. |
| `--mobile` | Integer | Override Mobile queries for this run (requires `--account`). | Uses the account schedule. |
| `--force` | Flag | Run even if already triggered today. | Skips accounts already triggered today. |

> **Note:** Headless mode is forced in the CLI and does not change the GUI Hide Browser preference.

---

### Example CLI commands:

```bash
# Run every enabled schedule (same as autostart)
python AutoRewarder.py --headless

# Run a single account once with overrides
python AutoRewarder.py --headless --account "Main" --pc 30 --mobile 20

# Force a re-run the same day
python AutoRewarder.py --headless --account "Main" --pc 30 --force
```

---

## Build & Distribution

**Build EXE (for installer creation):**
```bash
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean AutoRewarder.spec
```

**Create Windows Installer:**
```bash
"C:\Program Files (x86)\Inno Setup 6\iscc.exe" AutoRewarder.iss
```
Or use the Inno Setup IDE to open `AutoRewarder.iss` and compile it.
Output: `dist/AutoRewarder-Setup.exe`

---

## Project Structure

```text
AutoRewarder/
├── GUI/
│   ├── index.html        # Main window UI
│   ├── history.html      # History view UI
│   ├── history.css       # History view styling
│   ├── script.js         # Frontend logic and bridge calls
│   ├── settings.js       # Settings page logic and bridge calls
│   ├── styles.css        # App styling
│   └── normalize.css     # CSS reset
├── assets/
│   ├── icon.ico          # App icon
│   ├── queries.json      # Queries list (8154 unique queries)
│   └── screenshots/      # Screenshots and GIFs for documentation
├── src/
│   ├── __init__.py       # Python package initialization
│   ├── account_manager.py # Multi-account CRUD + migration
│   ├── api.py            # Centralizes all main operations (bridge API exposed to JS)
│   ├── config.py         # Configuration constants/platform and file paths
│   ├── daily_set.py      # Rewards Daily Set collection logic
│   ├── driver_manager.py # WebDriver setup and management
│   ├── edge_policy.py    # Edge sign-in policy helpers (Windows)
│   ├── history.py        # Manages search history storage and retrieval
│   ├── human_behavior.py # Human-like mouse movement/clicks/scrolling
│   ├── search_engine.py  # Handles search logic and interactions
│   ├── settings_manager.py # Manages user settings storage and retrieval
│   └── utils.py          # Utility functions(human-typing, update checks)
├── AutoRewarder.py       # Python backend and webview window
├── AutoRewarder_CLI.py   # Headless runner (multi-account aware)
├── AutoRewarder.spec     # PyInstaller build spec
├── AutoRewarder.iss      # Inno Setup installer script
├── LICENSE
├── README.md
├── USER_GUIDE.md
└── requirements.txt
```

---

## Runtime Data

The application stores its runtime files (profiles, history, logs, and settings) in a dedicated folder separate from your main browser.

**On Windows:**
```text
%USERPROFILE%\AppData\Local\AutoRewarder
```

**On Linux:**
```text
~/.local/share/AutoRewarder
```

Created files and folders:
```text
settings.json      # Global settings (hide_browser, current_account_id, autoStartUp)
accounts.json      # Account index
accounts/
	<account_id>/
		EdgeProfile/   # Separate Edge profile for WebDriver
		history.json   # Search history (date, time, query, status)
		status.json    # Daily Set completion status (per-day)
		meta.json      # Per-account metadata (first_setup_done, schedule)
background_log.txt # Logs from the background runner (for debugging)
```

---

## Troubleshooting

For common issues and solutions, see the [Troubleshooting](USER_GUIDE.md#troubleshooting) section in the USER GUIDE.

---

## Roadmap

- [x] Windows installer with dependency checking (Inno Setup)
- [x] Action Chains Selenium/W3C Actions for more natural mouse movement and clicks
- [x] Daily Set collector
- [x] Refactor: split monolith to src modules
- [x] Update checks (GitHub Releases API)
- [x] Better randomized scrolling (unique speed/length per session)
- [x] Advanced "coffee" breaks during long sessions
- [x] Navigation flow: sometimes switch result tabs (Images/Videos/News)
- [x] Script-only version (CLI tool without GUI)
- [x] Automatic start-up
- [x] Query pacing over a specified duration (rate-based scheduling)
- [x] Multi-account support (manage multiple Rewards accounts)
- [x] Mobile support
- [x] Per-Account Scheduling
- [x] Brand New UI
- [ ] Statistics dashboard (points tracking, session summaries)
- [ ] Browser choice (Chrome, Firefox support in addition to Edge)
- [ ] Daily "Claim" actions
- [ ] Keyboard shortcuts

---

## Disclaimer

Using automation against third-party services may violate their Terms of Service.
You are responsible for your own usage.

---

## Contact

Open an issue for bugs, ideas, or questions.

---

## Support

If you found this project helpful and would like to support my work, you can buy me a coffee here:

[![Buy Me a Coffee](https://img.shields.io/badge/Buy_Me_A_Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/safarsin)
