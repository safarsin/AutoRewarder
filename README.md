# AutoRewarder

A desktop automation app for Microsoft Rewards that performs Bing searches with human-like behavior.
Built with Python ([pywebview](https://pywebview.flowrl.com/) and [selenium](https://www.selenium.dev/)).
The UI is rendered with HTML/CSS/JS in a native window, while the automation logic is handled in Python.

Fully portable: no installation required for end users [release build](https://github.com/safarsin/AutoRewarder/releases/tag/v2.0).

> **For a complete user guide, see [USER_GUIDE.md](USER_GUIDE.md)**

## Screenshots

| Main Window | History Window |
| :---: | :---: |
| Coming soon | Coming soon |

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12, selenium, pywebview |
| Frontend | HTML, CSS, JavaScript |
| Bridge | pywebview JS API (pywebview.api) |
| Build | PyInstaller |

## System Requirements

- **OS**: Windows 10 or later
- **Browser**: Microsoft Edge (driver managed by Selenium Manager)
- **RAM**: Minimum 512 MB (1 GB recommended)
- **Disk Space**: ~50 MB

## Features

**User Features:**
- First Setup flow with dedicated Edge profile for isolation
- Optional hide-browser mode (headless automation toggle)
- Live terminal-like logs with real-time updates
- Local history view with date, time, query, and execution status
- One-click start automation (1-99 searches per session)
- Safe recovery for corrupted settings/history files

**Automation Features:**
- Background WebDriver warmup at startup for faster execution
- Human-like search behavior (typing delays, random pauses, smooth scrolling)
- Uses real-world queries from assets/queries.json (3428 unique entries from google-trends dataset)
- Randomized delays to avoid detection
- Separate browser thread isolation

## Quick Start (For Users)

You do not need Python to use release builds.

1. Download `AutoRewarder.exe` from releases
2. Extract and run
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

## Build Portable Release

Recommended (reproducible) build using spec:

```bash
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean AutoRewarder.spec
```

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
│   └── queries.json      # Queries list (3428 unique queries)
├── AutoRewarder.py       # Python backend and webview window
├── AutoRewarder.spec     # PyInstaller build spec
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
```


## Troubleshooting

**Edge WebDriver not found or outdated:**
- Ensure Microsoft Edge is installed
- Try restarting the application (Selenium Manager will auto-download driver)
- Check that Edge version is up to date
- Delete `%USERPROFILE%\AppData\Local\AutoRewarder\EdgeProfile` and retry

**Application crashes on startup:**
- Delete `EdgeProfile/` folder in `%USERPROFILE%\AppData\Local\AutoRewarder`
- Run First Setup again
- Verify dependencies: `pip install -r requirements.txt` if running from source
- Check Windows Event Viewer for error details

**Searches not completing:**
- Verify internet connection
- Check that Edge is not blocked by antivirus/firewall

## Roadmap

- [ ] Browser choice (Chrome, Firefox support in addition to Edge)
- [ ] Advanced scheduling (automated daily runs at specific times)
- [ ] Statistics dashboard (points tracking, session summaries)
- [ ] Multi-account support (manage multiple Rewards accounts)
- [ ] Script-only version (CLI tool without GUI)
- [ ] An intaller version (Inno Setup or similar)
- [ ] Keyboard shortcuts

## Disclaimer

Using automation against third-party services may violate their Terms of Service.
You are responsible for your own usage.

## Contact

Open an issue for bugs, ideas, or questions.
