# AutoRewarder — User Guide

Welcome! This guide will help you get started with AutoRewarder and explain all its features. No programming knowledge required.

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
1. Go to the [Releases page](../../releases) on GitHub
2. Find the latest release
3. Download the file named `AutoRewarder.zip`

### Step 2: Extract
1. Right-click the downloaded ZIP file
2. Select **Extract All**
3. Choose a folder where you want to extract (e.g., Desktop or Documents)
4. Click **Extract**

### Step 3: Run
1. Open the extracted folder
2. Double-click `AutoRewarder.exe`
3. The app will open in a window

**That's it!** No installation needed.

---

## First Run & Setup

When you run AutoRewarder for the first time, you'll see a first setup button.

### What is First Setup?

First Setup creates a special profile for Microsoft Edge that AutoRewarder uses. This keeps it separate from your personal browsing data and settings. It only needs to be done once. After that, you can start using AutoRewarder without worrying about it affecting your regular Edge profile.

### How to Complete First Setup

1. Click the **First Setup** button on the main window
2. Wait for it to complete (you should see Microsoft Edge open)
3. Then you should authorize your acount by signing in to Microsoft Rewards in the Bing page that opens
4. You're ready to use AutoRewarder!

**You only need to do this once.** If you run the app again, First Setup won't appear.

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
- The process continues until all searches are complete
- You'll see updates in the log window

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
**Version**: 2.0

Enjoy using AutoRewarder! 🎉