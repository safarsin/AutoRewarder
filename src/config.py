import os
import platform

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
        os.environ["USERPROFILE"],
        "AppData",
        "Local",
        "AutoRewarder"
    )

# Quit on invalid platform
else:
    raise OSError(f"Unsupported platform: {PLATFORM_NAME}")

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI_DIR = os.path.join(BASE_DIR, "GUI")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

if not os.path.exists(APP_DIR):
    os.makedirs(APP_DIR)

EDGE_PROFILE_PATH = os.path.join(APP_DIR, "EdgeProfile")
HISTORY_FILE_PATH = os.path.join(APP_DIR, "history.json")
SETTINGS_FILE_PATH = os.path.join(APP_DIR, "settings.json")
JSON_FILE_PATH = os.path.join(ASSETS_DIR, "queries.json")