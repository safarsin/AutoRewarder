# AutoRewarder — User Guide

Welcome! This guide will help you get started with AutoRewarder and explain all its features. No programming knowledge required.

<img src="assets/screenshots/warm_up.gif">

<img src="assets/screenshots/preform.gif">

---

## Table of Contents

1. [Installation](#installation)
2. [First Run & Setup](#first-run--setup)
3. [How to Use](#how-to-use)
4. [Understanding the Settings](#understanding-the-settings)
5. [Viewing Search History](#viewing-search-history)
6. [Tips & Best Practices](#tips--best-practices)
7. [Troubleshooting](#troubleshooting)
8. [FAQ](#faq)

---

## Installation

### Step 1: Download
1. Go to the [Releases page](https://github.com/safarsin/AutoRewarder/releases) on GitHub
2. Find the latest release (v3.0 or newer)
3. Download `AutoRewarder-Setup.exe`

### Step 2: Install
1. Double-click the downloaded `AutoRewarder-Setup.exe`
2. The installer will:
   - Verify you have Microsoft Edge installed
   - Verify you have .NET Framework 4.8 or higher
   - Install AutoRewarder to Program Files
3. Click **Next** through the setup wizard
4. Optionally create a desktop shortcut (recommended)
5. Click **Finish**

### Step 3: Run
1. Just run the app from the Start Menu or desktop shortcut

**That's it!** Installer handles everything for you.

---

## First Run & Setup

When you run AutoRewarder for the first time, you'll see a first setup button.

### What is First Setup?

First Setup creates a special profile for Microsoft Edge that AutoRewarder will use. This keeps it separate from your personal browsing data and settings. It only needs to be done once. After that, you can start using AutoRewarder without worrying about it affecting your regular Edge profile.

### How to Complete First Setup

1. Click the **First Setup** button on the main window
2. Wait for it to complete (you should see Microsoft Edge open)
3. Sign in to your Microsoft Rewards account on the Bing page that opens (don't sync browser)
<img src="assets/screenshots/sing_in.png" alt="Sign in screenshot" width="400">
4. Close the browser when done
5. You're ready to use AutoRewarder!

**You only need to do this once** If you run the app again, First Setup won't appear (it will use the saved profile).

---

## How to Use

### Starting a Session

1. Open AutoRewarder.exe
2. Look for the input box labeled with a number
3. Enter a number between **1 and 99** (this is how many searches you want to perform)
4. Click the **"Start"** button
5. Watch the green indicator show that AutoRewarder is working
6. The terminal-like window below shows what's happening in real-time

### What's Happening?

- AutoRewarder opens Microsoft Edge (you can see it if hide-browser is off)
- It performs random searches from a built-in list of 3,428 real search queries from google-trends dataset
- Each search has human-like delays and behavior
- It may occasionally switch to Images/Videos/News tabs
- It may take short "coffee breaks" during longer sessions
- After searches, it may run Daily Set tasks (once per day)
- The process continues until all searches are complete
- You'll see updates in the log window

If a new version is available, AutoRewarder can show an update notification and a download link.

### After Completion

- The **"Start"** button will become enabled again
- You can start another session or close the app
- Your search history is saved automatically

---

## Understanding the Settings

### Hide Browser

This toggle controls whether you can see Microsoft Edge while searches are happening.

- **OFF (default)**: You'll see Edge browser window performing searches
- **ON (hide-browser mode)**: Edge runs in the background, you only see the log window

**Why would you use hide-browser?**
- Less distracting if you're working on something else
- Slightly faster performance since it doesn't have to render the browser window what will save system resources (RAM/CPU)

---

## Viewing Search History

AutoRewarder keeps track of all searches it has performed.

### How to View History

1. In the main AutoRewarder window, click **"History"** button
2. A new window opens showing:
   - **Date** — when the search was performed
   - **Time** — exact time
   - **Query** — what was searched
   - **Status** — success/failure

### Where is History Saved?

History is saved in your user data folder:
```
C:\Users\[YourUsername]\AppData\Local\AutoRewarder\history.json
```

You don't need to access this directly — use the History button in the app instead.

---

## Tips & Best Practices

### ✅ Do's

- Start with a small number (5-10 searches) on your first try to test
- Let the app run uninterrupted for best results
- Check your internet connection before starting

### ❌ Don'ts

- Don't manually interact with Clone Edge (you still can use your main profile) while AutoRewarder is running
- Don't use Bing while AutoRewarder is performing searches (it may be detected as unusual activity)
- Don't force-close the app while a session is running
- Don't modify files in `AppData\Local\AutoRewarder` manually
- Don't run multiple AutoRewarder instances simultaneously

### Recommended Usage

For best results:
1. Run 30 searches per session
3. Vary the number of searches each time

---


### Need Help?

For detailed technical troubleshooting, see the [Troubleshooting](README.md#troubleshooting) section in the main README.

If your issue isn't listed, please open an issue on GitHub or [contact me](mailto:sinosafarov1919@gmail.com).
---

## Troubleshooting

### `DevToolsActivePort file doesn't exist` / `session not created`

This usually means Microsoft Edge didn't start cleanly (often after a background update) and Selenium can't attach.

1. Close AutoRewarder and any Edge windows
2. Open Windows Task Manager and end all `msedge.exe` processes (and `msedgedriver.exe` if present)
3. Open Edge normally and finish updates at `edge://settings/help`
4. Start AutoRewarder again

If it still fails:
- Delete `%USERPROFILE%\AppData\Local\AutoRewarder\EdgeProfile`
- Run **First Setup** again

## FAQ

**Q: Is AutoRewarder safe?**  
A: AutoRewarder is safe to use on your computer. It uses a separate browser profile so your personal data is not affected.

**Q: Why does it need Microsoft account authorization?**  
A: AutoRewarder uses Edge to perform searches. Selenium WebDriver (the automation tool) requires a real browser to work with Microsoft Rewards.

**Q: Will this ban my Microsoft Rewards account?**  
A: Microsoft Rewards' Terms of Service prohibit automation. Use at your own risk.
But AutoRewarder is designed to mimic human behavior with randomized delays and real search queries to reduce the risk of detection. However, there is always a possibility of account suspension if detected such as searching with Bing while AutoRewarder is running or running multiple sessions at the same time.
Personaly I have been using it for almost 7 months without any issues.

**Q: How many searches can I do per day?**  
A: You can run as many sessions as you want (1-99 searches each). However, Microsoft may have daily limits on rewards earned which depend on your account's activity and region.

**Q: Why does it ask me to do First Setup?**  
A: First Setup creates a separate browser profile that doesn't interfere with your personal Edge settings. It only needs to run once.

**Q: What if the app freezes?**  
A: You can force-close it (Ctrl+Alt+Delete → Task Manager → AutoRewarder → End Task). Your history/settings will be preserved.

**Q: Can I run this on Mac or Linux?**  
A: Currently only Windows is supported. You need Windows 10 or later.

---

**Last Updated**: April 2026  
**Version**: 3.0

Enjoy using AutoRewarder! 🎉