"""
Main entry point for the AutoRewarder application.

This script initializes the core AutoRewarderAPI and launches the desktop 
graphical user interface (GUI) using pywebview. 

Usage:
    Run this file directly to start the application:
    python AutoRewarder.py
"""

import os
import webview

from src.api import AutoRewarderAPI
from src.config import GUI_DIR, ASSETS_DIR

# Entry point of the application
if __name__ == "__main__":
    api = AutoRewarderAPI()
    window = webview.create_window(
        title= "AutoRewarder",
        url=os.path.join(GUI_DIR, "index.html"),
        js_api=api,
        width=570,
        height=490,
        resizable=False,
        #frameless=True
    )
    api.set_window(window)  # pass window reference to AutoRewarderAPI for logging
    webview.start(icon=os.path.join(ASSETS_DIR, "icon.ico"))