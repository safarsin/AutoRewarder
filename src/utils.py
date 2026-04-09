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
def check_for_updates():
    try:
        response = requests.get(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            timeout=5
        )
        if response.status_code == 200:
            latest = response.json()['tag_name']
            return latest != CURRENT_VERSION, latest
    except Exception:
        pass
    return False, None