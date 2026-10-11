"""Locale detection and language resolution for search-query generation.

Decides which language the auto-generated (LLM) search queries should be
written in.

In the desktop GUI the browser reports the OS locale via
``navigator.language``; that value is persisted to settings and preferred
here. In headless/CLI runs there is no browser, so we fall back to the Python
``locale`` module, the ``LANG`` family of environment variables, and (on
Windows) the Win32 user-default locale.
"""

import locale as _locale
import os

# Primary language subtag -> human-readable English name, used only to phrase
# the generation prompt ("...in French."). We look at the language part only,
# so "fr-FR" and "fr-CA" both resolve to "French".
_LANGUAGE_NAMES = {
    "ar": "Arabic",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "fi": "Finnish",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "zh": "Chinese",
}

DEFAULT_LOCALE = "en-US"


def _normalize(tag):
    """Normalize a raw locale string to a BCP-47 ``ll-CC`` (or ``ll``) form.

    Accepts values like ``fr_FR.UTF-8``, ``fr-FR``, ``fr``, ``C`` or ``""``
    and returns e.g. ``fr-FR`` / ``fr``, or ``""`` when nothing usable is left.
    """
    if not tag:
        return ""

    tag = str(tag).strip()
    # Drop encoding suffix (fr_FR.UTF-8 -> fr_FR) and unify separators.
    tag = tag.split(".")[0].split("@")[0].replace("_", "-")

    if not tag or tag.lower() in ("c", "posix", "auto"):
        return ""

    parts = tag.split("-")
    lang = parts[0].lower()
    if not lang.isalpha():
        return ""

    if len(parts) > 1 and parts[1]:
        return f"{lang}-{parts[1].upper()}"
    return lang


def detect_system_locale():
    """Best-effort OS locale for headless runs, e.g. ``fr-FR``.

    Returns ``DEFAULT_LOCALE`` when nothing usable can be found.
    """
    candidates = []

    # Windows: ask Win32 for the user's default locale name (most accurate).
    if os.name == "nt":
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, len(buf)):
                candidates.append(buf.value)
        except Exception:
            pass

    # Standard-library locale readers (cross-platform).
    try:
        candidates.append(_locale.getlocale()[0])
    except Exception:
        pass
    try:
        # getdefaultlocale() is deprecated in 3.12 but remains the most
        # reliable reader of the LANG environment; silence the warning.
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            candidates.append(_locale.getdefaultlocale()[0])
    except Exception:
        pass

    # POSIX environment variables (LANGUAGE may be a colon-separated list).
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        val = os.environ.get(var)
        if val:
            candidates.append(val.split(":")[0])

    for cand in candidates:
        norm = _normalize(cand)
        if norm:
            return norm

    return DEFAULT_LOCALE


def language_name(loc):
    """Return the English language name for a locale (``fr-FR`` -> ``French``).

    Falls back to the raw (normalized) locale string when the language is not
    in the table; that still works fine as a hint for the model.
    """
    norm = _normalize(loc) or DEFAULT_LOCALE
    lang = norm.split("-")[0].lower()
    return _LANGUAGE_NAMES.get(lang, norm)


def resolve_search_locale(settings, logger=None):
    """Resolve the locale to use for query generation.

    Priority:
        1. Explicit ``search_locale`` setting, when set to something other
           than ``"auto"``/empty (user override in the UI).
        2. ``detected_locale`` reported by the GUI (``navigator.language``).
        3. Python-side OS detection (headless/CLI).
        4. ``DEFAULT_LOCALE``.

    Args:
        settings (dict): the global settings dict.
        logger (callable, optional): logging function.

    Returns:
        str: a locale such as ``"fr-FR"``.
    """
    settings = settings or {}

    raw = str(settings.get("search_locale") or "").strip()
    if raw and raw.lower() != "auto":
        norm = _normalize(raw)
        if norm:
            return norm

    detected = _normalize(settings.get("detected_locale"))
    if detected:
        return detected

    resolved = detect_system_locale()
    if logger:
        logger(f"Search locale auto-detected: {resolved}")
    return resolved
