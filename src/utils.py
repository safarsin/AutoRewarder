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


def humanize_queries(queries, logger=None):
    """
    Substitute character by keyboard distance to simulate human typing errors.

    Args:
        queries (list): A list of query strings.
        logger (callable, optional): Logger used to report a skipped pass.
    Returns:
        humanized_queries (list): Queries, some with a simulated typo;
        unchanged if nlpaug is unavailable.
    """
    try:
        import nlpaug.augmenter.char as nac  # type: ignore
    except Exception as e:  # ImportError, or a partially installed nlpaug
        msg = (
            f"[WARNING] Skipping query humanizing — nlpaug unavailable "
            f"({e.__class__.__name__}: {e}). Searching queries as-is."
        )
        (logger or print)(msg)
        return list(queries)

    try:
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
    except Exception as e:  # e.g. its bundled data file is unreadable
        (logger or print)(
            f"[WARNING] Skipping query humanizing — KeyboardAug unavailable "
            f"({e.__class__.__name__}: {e}). Searching queries as-is."
        )
        return list(queries)

    humanized_queries = []

    for query in queries:
        if random.random() < 0.2:
            try:
                modified_query = mod.augment(query)
            except Exception as e:
                (logger or print)(
                    f"[WARNING] Could not humanize a query "
                    f"({e.__class__.__name__}: {e}); using it unchanged."
                )
                humanized_queries.append(query)
                continue
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
