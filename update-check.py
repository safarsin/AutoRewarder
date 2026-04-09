# import requests

# def update_check():
#     response = requests.get(
#         "https://api.github.com/repos/safarsin/AutoRewarder/releases/latest"
#     )
#     latest = response.json()
#     latest_version = latest["tag_name"]
#     latest_url = latest["html_url"]

#     return latest_version, latest_url

# print(update_check())

import requests

CURRENT_VERSION = "1.0"
REPO = "safarsin/AutoRewarder"

def check_for_updates():
    try:
        response = requests.get(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            timeout=5
        )
        if response.status_code == 200:
            latest = response.json()['tag_name']
            return latest != CURRENT_VERSION, latest
    except:
        pass
    return False, None

print(check_for_updates())