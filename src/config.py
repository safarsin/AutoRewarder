"""
Configuration module for AutoRewarder.

This module defines constants and paths used throughout the AutoRewarder application,
such as version information, repository details, platform-specific directories,
and helpers to resolve per-account file paths (Edge profile, history, status, meta).
"""

import os
import platform
import sys

CURRENT_VERSION = "v3.0"
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

# Multi-account storage layout:
#   APP_DIR/
#     settings.json          (global: hide_browser, current_account_id, schema_version)
#     accounts.json          (index: [{id, label, created_at}])
#     accounts/
#       <account_id>/
#         EdgeProfile/
#         history.json
#         status.json
#         meta.json          (per-account: first_setup_done)
ACCOUNTS_DIR = os.path.join(APP_DIR, "accounts")
GLOBAL_SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
ACCOUNTS_INDEX_PATH = os.path.join(APP_DIR, "accounts.json")
JSON_FILE_PATH = os.path.join(ASSETS_DIR, "queries.json")

# Legacy single-account paths (used only for one-shot migration detection).
LEGACY_EDGE_PROFILE_PATH = os.path.join(APP_DIR, "EdgeProfile")
LEGACY_HISTORY_FILE_PATH = os.path.join(APP_DIR, "history.json")
LEGACY_STATUS_FILE_PATH = os.path.join(APP_DIR, "status.json")


def account_dir(account_id):
    """Return the directory holding all files for a given account."""
    return os.path.join(ACCOUNTS_DIR, account_id)


def edge_profile_path(account_id):
    """Return the Selenium --user-data-dir path for a given account."""
    return os.path.join(account_dir(account_id), "EdgeProfile")


def history_path(account_id):
    """Return the history.json path for a given account."""
    return os.path.join(account_dir(account_id), "history.json")


def status_path(account_id):
    """Return the daily-set status.json path for a given account."""
    return os.path.join(account_dir(account_id), "status.json")


def account_meta_path(account_id):
    """Return the per-account meta.json path (stores first_setup_done)."""
    return os.path.join(account_dir(account_id), "meta.json")
