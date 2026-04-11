import time
import random
import requests

from .config import CURRENT_VERSION, REPO

# Human-like typing with random delays between keystrokes
def human_typing(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.18))

# Check if update is required
def check_for_updates(logger=None):
    try:
        headers = {
            "User-Agent": "AutoRewarder-App"
            }

        response = requests.get(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            headers=headers,
            timeout=5
        )
        if response.status_code == 200:
            latest = response.json().get("tag_name")
            if latest:
                return latest != CURRENT_VERSION, latest
        elif response.status_code == 429:
            if logger:
                logger("[WARNING] GitHub API rate limit reached (429).")
                logger("Try again later or check manually for updates.")
        elif response.status_code == 403:

            is_rate_limit = response.headers.get('X-Ratelimit-Remaining') == '0'

            if logger:
                if is_rate_limit:
                    logger("[WARNING] GitHub API rate limit exceeded (403). Try again later.")
                else:
                    logger("[WARNING] GitHub access forbidden (403). Check your VPN or connection.")
        else:
            if logger:
                logger(f"[WARNING] GitHub update check failed. Status: {response.status_code}")

    except requests.exceptions.RequestException as e:
        if logger:
            logger(f"[WARNING] Network error while checking for updates: {e}")
    except Exception as e:
        if logger:
            logger(f"[ERROR] Unexpected error while checking for updates: {e}")

    return False, None