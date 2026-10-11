"""Shared utility helpers for AutoRewarder."""

import time
import random
import requests

from .config import CURRENT_VERSION, REPO


def human_typing(element, text):
    """
    Simulate human-like typing by sending keys to a web element with random delays.

    Args:
        element: The web element to send keys to.
        text: The text to type into the element.
    """

    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.18))


def humanize_queries(queries):
    """
    Substitute character by keyboard distance to simulate human typing errors.

    Args:
        queries (list): A list of query strings.
    Returns:
        humanized_queries (list): Modified query strings with simulated typing errors.
    """
    import nlpaug.augmenter.char as nac  # type: ignore

    mod = nac.KeyboardAug(
        # 100% probability because the 20% overall chance
        # handled outside by the `random` module
        aug_char_p=1.0,
        aug_word_p=1.0,
        # Only one typo per query
        aug_char_max=1,
        aug_word_max=1,
        # Ignore short words
        min_char=4,
        include_upper_case=False,
        include_special_char=False,
        include_numeric=True,
    )

    humanized_queries = []

    for query in queries:
        if random.random() < 0.2:
            modified_query = mod.augment(query)
            typo_query = (
                modified_query[0]
                if isinstance(modified_query, list)
                else modified_query
            )
            humanized_queries.append(typo_query)
        else:
            humanized_queries.append(query)

    return humanized_queries


def check_for_updates(logger=None):
    """
    Check GitHub API for the latest release and compare it to the current version.

    Args:
        logger (callable, optional): A function to log messages. Defaults to None.

    Returns:
        tuple: (is_update_available (bool), latest_version (str or None))
    """
    try:
        headers = {"User-Agent": "AutoRewarder-App"}

        response = requests.get(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            headers=headers,
            timeout=5,
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

            is_rate_limit = response.headers.get("X-Ratelimit-Remaining") == "0"

            if logger:
                if is_rate_limit:
                    logger(
                        "[WARNING] GitHub API rate limit exceeded (403). Try again later."
                    )
                else:
                    logger(
                        "[WARNING] GitHub access forbidden (403). Check your VPN or connection."
                    )
        else:
            if logger:
                logger(
                    f"[WARNING] GitHub update check failed. Status: {response.status_code}"
                )

    except requests.exceptions.RequestException as e:
        if logger:
            logger(f"[WARNING] Network error while checking for updates: {e}")
    except Exception as e:
        if logger:
            logger(f"[ERROR] Unexpected error while checking for updates: {e}")

    return False, None
