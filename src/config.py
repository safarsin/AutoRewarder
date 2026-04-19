"""
Configuration module for AutoRewarder.

This module defines constants and paths used throughout the AutoRewarder application,
such as version information, repository details, platform-specific directories,
and file paths for storing user data and settings.
"""

import os
import platform
import sys

CURRENT_VERSION = "v3.1"
REPO = "safarsin/AutoRewarder"

PLATFORM_NAME = platform.system()

# Configs
# Create a separate folder for the bot's profile to avoid conflicts with your main browser
APP_DIR = ""

# Get Linux app directory
if PLATFORM_NAME == "Linux":
    APP_DIR = os.path.expanduser("~/.local/share/AutoRewarder")

# Get Windows app directory
elif PLATFORM_NAME == "Windows":
    APP_DIR = os.path.join(
        os.environ["USERPROFILE"], "AppData", "Local", "AutoRewarder"
    )

# Quit on invalid platform
else:
    raise OSError(f"Unsupported platform: {PLATFORM_NAME}")

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI_DIR = os.path.join(BASE_DIR, "GUI")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# Portable config takes precedence
if getattr(sys, "frozen", False):
    portable_app_dir = os.path.join(os.path.dirname(sys.executable), "config")
    if os.path.isdir(portable_app_dir):
        APP_DIR = portable_app_dir

if not os.path.exists(APP_DIR):
    os.makedirs(APP_DIR)

EDGE_PROFILE_PATH = os.path.join(APP_DIR, "EdgeProfile")
HISTORY_FILE_PATH = os.path.join(APP_DIR, "history.json")
SETTINGS_FILE_PATH = os.path.join(APP_DIR, "settings.json")
STATUS_FILE_PATH = os.path.join(APP_DIR, "status.json")
JSON_FILE_PATH = os.path.join(ASSETS_DIR, "queries.json")
LOG_FILE_PATH = os.path.join(APP_DIR, "background_log.txt")

# Maximum size (in bytes) before the log file is deleted and recreated (6 MB)
LOG_MAX_SIZE = 6 * 1024 * 1024
