"""
Main entry point for the AutoRewarder application.

This script initializes the core AutoRewarderAPI and launches the desktop
graphical user interface (GUI) using pywebview.

Usage:
    Run this file directly to start the application:
    python AutoRewarder.py
"""

import os
import sys
import argparse
import webview

from src.api import AutoRewarderAPI
from src.config import GUI_DIR, ASSETS_DIR

# Entry point of the application
if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--headless", action="store_true", help="Run in headless/background mode")
    args, _ = parser.parse_known_args()

    # If started with --headless, delegate to the headless runner and exit.
    if args.headless:
        # Import here to avoid importing headless_runner when running the GUI.
        try:
            from AutoRewarder_CLI import main as headless_main
        except Exception:
            # Try module path when running from package root
            from .AutoRewarder_CLI import main as headless_main

        headless_main()
        sys.exit(0)

    api = AutoRewarderAPI()
    window = webview.create_window(
        title="AutoRewarder",
        url=os.path.join(GUI_DIR, "index.html"),
        js_api=api,
        width=570,
        height=490,
        resizable=False,
        # frameless=True
    )
    api.set_window(window)  # pass window reference to AutoRewarderAPI for logging
    webview.start(icon=os.path.join(ASSETS_DIR, "icon.ico"))
