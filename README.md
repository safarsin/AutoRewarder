# AutoRewarder

![Stars](https://img.shields.io/github/stars/safarsin/AutoRewarder?style=for-the-badge)
![Downloads](https://img.shields.io/github/downloads/safarsin/AutoRewarder/total?style=for-the-badge&color=007acc)

An advanced desktop automation tool for Microsoft Rewards. AutoRewarder performs Bing searches and collects Daily Sets using mathematically driven, human-like input simulation (W3C Actions, Bezier curves, and smart scrolling).

Built with a robust Python/Selenium backend and a sleek HTML/CSS/JS frontend wrapped in a native window via pywebview. Packaged as a executable Windows app (via Inno Setup) for a seamless, plug-and-play experience.

> **Ready to start? Check out the complete [USER GUIDE](USER_GUIDE.md)**

## Installation

**Easy Way (Recommended):**
Download `AutoRewarder-Setup.exe` from the [latest release](https://github.com/safarsin/AutoRewarder/releases/latest) and run it. The installer will verify all dependencies and install the app for you.

**Portable Way:**
Download `AutoRewarder.zip` from the [latest release](https://github.com/safarsin/AutoRewarder/releases/latest) and extract it to any folder (e.g., a USB drive). Run the executable. All your settings and profiles will be saved locally inside the `config` folder.
> **Note:** Because the portable version is a single-file build, it may take a few seconds longer to start up compared to the installed version while it unpacks core components. Once open, it works at full speed.

**Manual Way (Source):**
Clone this repo, create virtual environment, and run `python AutoRewarder.py`.


## Screenshots & Demo

| Perform Searches | Driver Preparation |
| :---: | :---: |
|<img src="assets/screenshots/preform.gif">|<img src="assets/screenshots/warm_up.gif">|

|Daily Sets| Tab Switching |
| :---: | :---: |
|<img src="assets/screenshots/daily_set.gif">|<img src="assets/screenshots/tab_perform.gif">|

> <sub>*Demo is sped up for viewing purposes. Actual execution includes randomized delays and pauses to mimic human behavior.*</sub>

| Main Window | History & Updates |
| :---: | :---: |
| <img src="assets/screenshots/main_window.png"> | <img src="assets/screenshots/history_window1.png"> |
| <img src="assets/screenshots/main_window1.png"> | <img src="assets/screenshots/update_check.png"> |


## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12, [selenium](https://www.selenium.dev/), [pywebview](https://pywebview.flowrl.com/) |
| Frontend | HTML, CSS, JavaScript |
| Bridge | pywebview JS API (pywebview.api) |
| Build | [PyInstaller](https://pyinstaller.org/), [Inno Setup](https://jrsoftware.org/isinfo.php) |

## System Requirements

- **OS**: Windows 10 or later (can also work on Linux but it is not downloadable as an executable)
- **Browser**: Microsoft Edge (driver managed by Selenium Manager)
- **.NET Framework**: 4.8 or higher (automatically checked by installer)
- **RAM**: Minimum 512 MB (1 GB recommended)
- **Disk Space**: ~50 MB

## Features

**User Features:**
- First Setup flow with dedicated Edge profile for isolation
- Optional hide-browser mode (headless automation toggle)
- Live terminal-like logs with real-time updates
- Update available notifications (GitHub Releases)
- Local history view with date, time, query, and execution status
- One-click start automation (1-99 searches per session)
- Safe recovery for corrupted settings/history files

**Automation Features:**
- Background WebDriver warmup at startup for faster execution
- Human-like search behavior (typing delays, random pauses, smooth scrolling)
- Uses real-world queries from assets/queries.json (3428 unique entries from google-trends dataset)
- Randomized delays to reduce repetitive patterns
- Optional tab switching between result categories (Images/Videos/News)
- Natural mouse movement/clicking (W3C Actions)
- Daily Set task collection (runs once per day)
- Separate browser thread isolation

## Quick Start (For Users)

You do not need Python to use release builds.

1. Download `AutoRewarder-Setup.exe` from the latest release
2. Install and run the app
3. Complete First Setup
4. Start automation

For detailed guide, see [USER_GUIDE.md](USER_GUIDE.md)

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

## Project Structure

```text
AutoRewarder/
├── GUI/
│   ├── index.html        # Main window UI
│   ├── history.html      # History view UI
│   ├── script.js         # Frontend logic and bridge calls
│   ├── styles.css        # App styling
│   └── normalize.css     # CSS reset
├── assets/
│   ├── icon.ico          # App icon
│   ├── queries.json      # Queries list (3428 unique queries)
│   └── screenshots/      # Screenshots and GIFs for documentation
├── src/
│   ├── __init__.py       # Python package initialization
│   ├── api.py            # Centralizes all main operations (bridge API exposed to JS)        
│   ├── config.py         # Configuration constants/platform and file paths
│   ├── daily_set.py      # Rewards Daily Set collection logic
│   ├── driver_manager.py # WebDriver setup and management
│   ├── history.py        # Manages search history storage and retrieval
│   ├── human_behavior.py # Human-like mouse movement/clicks/scrolling
│   ├── search_engine.py  # Handles search logic and interactions
│   ├── settings_manager.py # Manages user settings storage and retrieval
│   └── utils.py          # Utility functions(human-typing, update checks)
│ 
├── AutoRewarder.py       # Python backend and webview window
├── AutoRewarder.spec     # PyInstaller build spec
├── AutoRewarder.iss      # Inno Setup installer script
├── LICENSE              
├── README.md            
└── requirements.txt      
```

## Runtime Data

The app stores runtime files in:

```text
%USERPROFILE%\AppData\Local\AutoRewarder
```

Created files and folders:
```text
EdgeProfile/   # Separate Edge profile for WebDriver
settings.json  # User settings (first_setup_done, hide_browser)
history.json   # Search history (date, time, query, status)
status.json    # Daily Set completion status (per-day)
```


## Troubleshooting

For common issues and solutions, see the [Troubleshooting](USER_GUIDE.md#troubleshooting) section in the USER GUIDE.

## Roadmap

- [x] Windows installer with dependency checking (Inno Setup)
- [x] Action Chains Selenium/W3C Actions for more natural mouse movement and clicks
- [x] Daily Set collector
- [x] Refactor: split monolith to src modules
- [x] Update checks (GitHub Releases API)
- [x] Better randomized scrolling (unique speed/length per session)
- [x] Advanced "coffee" breaks during long sessions
- [x] Navigation flow: sometimes switch result tabs (Images/Videos/News)
- [ ] Browser choice (Chrome, Firefox support in addition to Edge)
- [ ] Advanced scheduling (automated daily runs at specific times)
- [ ] Statistics dashboard (points tracking, session summaries)
- [ ] Multi-account support (manage multiple Rewards accounts)
- [ ] Script-only version (CLI tool without GUI)
- [ ] Daily Set "Claim" actions
- [ ] Keyboard shortcuts
- [ ] UI themes (dark/light mode)

## Disclaimer

Using automation against third-party services may violate their Terms of Service.
You are responsible for your own usage.

## Contact

Open an issue for bugs, ideas, or questions.

## Support

If you found this project helpful and would like to support my work, you can buy me a coffee here:

[![Buy Me a Coffee](https://img.shields.io/badge/Buy_Me_A_Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/safarsin)
