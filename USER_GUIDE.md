# AutoRewarder — User Guide

Welcome! This guide will help you get started with AutoRewarder and explain all its features. No programming knowledge required.

> **For screenshots and demo, see the [Screenshots & Demo](README.md#screenshots--demo) section in the README.**

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
2. Find the latest release (v3.2 or newer)
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

On first launch, AutoRewarder starts with no accounts. You will see an empty state with a **Create your first account** button (or use **Add account** from the header).

### What is First Setup?

First Setup creates a dedicated Edge profile for each account. This keeps it separate from your personal browsing data and lets you manage multiple Rewards accounts safely.

### How to Complete First Setup

1. Click **Create your first account** (or **Add account**)
2. Enter a name for the account
3. Microsoft Edge opens. Sign in to the Rewards account for this profile.

<img src="assets/screenshots/new_sign_in/sign_in_2.png" width="400">

4. Close the browser window when done
5. The account will show as **Ready**

### Multiple Accounts

Adding another account is slightly different, so please follow these steps:

1. Click **Add account**
2. Enter a name for the new account
3. Microsoft Edge opens again, but this time it will suggest you automatically sign in. Do NOT accept the sign-in prompt. Instead, click **No, thanks** or **x**.

<img src="assets/screenshots/new_sign_in/sign_in_3.png" width="400">

4. Then click the profile icon in the top right corner of Edge and choose **Add new account**.

<img src="assets/screenshots/new_sign_in/sign_in_4.png" width="400">
<img src="assets/screenshots/new_sign_in/sign_in_5.png" width="400">

5. After signing in to the new account, the profile tab should look like this:

<img src="assets/screenshots/new_sign_in/sign_in_6.png" width="400">

6. Make sure you see the new account here. If you see the old account, click **Sign out** and sign in with the new account. If you see the new one, just refresh the page and it should show as signed in.

<img src="assets/screenshots/new_sign_in/sign_in_2.png" width="400">
<img src="assets/screenshots/new_sign_in/sign_in_1.png" width="400">

> **Important:** Go to the Rewards dashboard and accept terms and cookies for the new account to make sure it's fully set up.

7. Close the browser window when done

> **Note:** Repeat this to add more accounts.

---

## How to Use

### Starting a Session

1. Open AutoRewarder.exe
2. Select an account from the dropdown
3. Set PC and Mobile query counts (PC 0-130, Mobile 0-99). Set one to 0 to skip it
4. *(Optional)* Toggle **"Daily tasks only"** to skip searches and only collect dashboard click-through tasks
5. Click the **"Start run"** button
6. Watch the status indicator show that AutoRewarder is working
7. The terminal-like window below shows what's happening in real-time
8. To interrupt the run at any time, click the **"Stop"** button — the browser will close cleanly and no orphan processes are left behind

### What's Happening?

- AutoRewarder opens Microsoft Edge (you can see it if hide-browser is off)
- It performs random searches from a built-in list of 8,154 real search queries from a google-trends dataset
- Each search has human-like delays and behavior
- It runs the PC phase first, then the Mobile phase (iPhone emulation)
- It may occasionally switch to Images/Videos/News tabs
- It may take short "coffee breaks" during longer sessions
- After the PC phase, it collects Daily Set + "More Activities" click-through tasks (once per day, per account). Locked cards, sweepstakes and promo banners are automatically skipped — only point-earning tasks are clicked
- The process continues until all searches are complete, or until you click **Stop**
- You'll see updates in the log window

If a new version is available, AutoRewarder can show an update notification and a download link.

#### Daily tasks only

If you've already done your searches manually (or just want to clean up the dashboard quickly), enable the **"Daily tasks only"** toggle before starting. The run skips both Bing search phases and goes straight to the Rewards dashboard to harvest the Daily Set + More Activities cards.

### After Completion

- The **"Start"** button will become enabled again
- You can start another session or close the app
- Your search history is saved automatically
- If you stopped the run via **Stop**, partial progress is kept (whatever searches and daily-task clicks already happened are credited as usual)

---

## Understanding the Settings

### Hide Browser

This toggle controls whether you can see Microsoft Edge while searches are happening.

- **OFF (default)**: You'll see Edge browser window performing searches
- **ON (hide-browser mode)**: Edge runs in the background, you only see the log window

**Why would you use hide-browser?**
- Less distracting if you're working on something else
- Slightly faster performance since it doesn't have to render the browser window what will save system resources (RAM/CPU)

### Autostart

When enabled, AutoRewarder will launch headless runs when you sign in. On Linux (source installs), it creates a desktop autostart entry.

If you want to disable this setting, simply turn it off and save settings. Or remove AutoRewarder from Windows Startup here:

<img src="assets/screenshots/start-up.png" width="400">

### How to check if it's running or stop it (Task Manager)

If the AutoRewarder window is open, the in-app **Stop** button is the cleanest way to halt a run — it closes the browser, kills the WebDriver, and leaves no orphan Edge processes behind.

For background runs (Autostart or CLI mode) where there's no visible window, use Task Manager:

**To check status or force stop:**
1. Open **Task Manager** (`Ctrl + Shift + Esc`).
2. Look for `AutoRewarder.exe` in the **Processes** tab.
3. If it's there, the bot is active.
4. To stop the bot, right-click `AutoRewarder.exe` and select **End task**.

<img src="assets/screenshots/tasks.jpg" width="400">

> If you see the process using some CPU and Network, it means it's currently performing searches!

### Scheduled runs

Each account has its own schedule card in the Settings window. Enable it to run that account automatically when **Start with Windows** is on (or when you run the headless CLI).

- **Simple schedule**: runs the PC and Mobile counts once at launch
- **Advanced scheduling**: spreads the total across the run duration using the queries-per-hour target

It runs in the background and takes jittered breaks (+/- 25%) to mimic human behavior.

> [!WARNING]
> **Important:** Make sure that your PC is connected to the internet and does not go to sleep while the bot is running.

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

History is saved per account in your user data folder:

```
C:\Users\[YourUsername]\AppData\Local\AutoRewarder\accounts\<account_id>\history.json
```

You don't need to access this directly — use the History button in the app instead.

## View background process logs

If you want to see detailed logs of the background process (for debugging or monitoring), you can find them in the `background_log.txt` file located in the same user data folder:

```
C:\Users\[YourUsername]\AppData\Local\AutoRewarder\background_log.txt
```


---

## Tips & Best Practices

### ✅ Do's

- Start with a small number (5-10 searches) on your first try to test
- Let the app run uninterrupted for best results
- Check your internet connection before starting

### ❌ Don'ts

- Don't manually interact with the AutoRewarder Edge profile while it is running (you can still use your main profile)
- Don't use Bing while AutoRewarder is performing searches (it may be detected as unusual activity)
- Don't force-close the app while a session is running
- Don't modify files in `AppData\Local\AutoRewarder` manually
- Don't run multiple AutoRewarder instances simultaneously

### Recommended Usage

For best results:
1. Run 30 PC searches and 30 Mobile searches per session
2. Vary the number of searches each time
3. Run sessions at different times of the day
4. Use hide-browser mode if you want to do other work while it runs

---


### Need Help?

For any issues, check the [Troubleshooting](#troubleshooting) section below.

If your issue isn't listed, please open an issue on GitHub or [contact me](mailto:sinosafarov1919@gmail.com).

---

## Troubleshooting

**Edge WebDriver not found or outdated:**
- Ensure Microsoft Edge is installed
- Try restarting the application (Selenium Manager will auto-download driver)
- Check that Edge version is up to date
- In **Manage accounts**, choose **Re-run setup** for the affected account

**`session not created: DevToolsActivePort file doesn't exist` / Edge failed to start:**
- Close AutoRewarder and any Edge windows
- Open Windows Task Manager and kill all `msedge.exe` processes (and `msedgedriver.exe` if present)
- Open Edge normally and complete any pending updates at `edge://settings/help`
- Re-run AutoRewarder
- If it still fails, use **Manage accounts** -> **Re-run setup** for the account

**Application crashes on startup:**
- In **Manage accounts**, delete or re-run setup for the affected account
- Verify dependencies: `pip install -r requirements.txt` if running from source
- Check Windows Event Viewer for error details

**Searches not completing:**
- Verify internet connection
- Check that Edge is not blocked by antivirus/firewall

**"No account selected" or "Setup pending":**
- Add an account and complete First Setup before starting

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
A: You can run as many sessions as you want. The UI allows PC (0-130) and Mobile (0-99) per run, but Microsoft Rewards limits depend on region and account status.

**Q: Why does it ask me to do First Setup?**
A: First Setup creates a separate browser profile for each account. You only need to run it once per account.

**Q: What if the app freezes?**
A: You can force-close it (Ctrl+Alt+Delete → Task Manager → AutoRewarder → End Task). Your history/settings will be preserved.

**Q: Can I run this on Mac or Linux?** <br>
A: Currently, the pre-built installer and standalone executable are only available for Windows. The application can run on Linux, but it requires manual setup from the source code. A portable/executable version for Linux is not available at this time. Mac OS is not supported.

---

**Last Updated**: May 2026
**Version**: 3.2

Enjoy using AutoRewarder! 🎉
