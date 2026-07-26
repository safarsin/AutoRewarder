"""LLM-backed search-query generation (bring-your-own-key).

Given a target count and a locale, ask a cloud LLM to produce fresh, natural
web-search queries written in the user's language. The app ships no AI SDK;
every call goes over plain HTTP with the ``requests`` library already listed
in ``requirements.txt``.

Robustness is the priority: this is a set-and-forget / scheduled tool, so
``generate_queries`` **never raises**. Every failure path — missing or invalid
key, quota / rate-limit, offline, timeout, malformed response — returns an
empty list and logs the cause, letting the caller fall back to the static
query file.
"""

import json

import requests

from .locale import language_name

# Provider -> default model used when the user leaves the model field blank.
# The model stays editable in the UI so users can track newer models without a
# code change.
DEFAULT_MODELS = {
    "openai": "gpt-5.4-nano",
    "anthropic": "claude-haiku-4-5",
    "gemini": "gemini-3.1-flash-lite",
}

SUPPORTED_PROVIDERS = tuple(DEFAULT_MODELS.keys())

_TIMEOUT = 30  # seconds, per request
_ANTHROPIC_VERSION = "2023-06-01"


def _max_tokens(count):
    """Rough output-token budget for `count` short JSON-array queries."""
    return min(8192, 512 + count * 30)


def _build_prompt(count, loc):
    """Phrase the generation instruction in the user's language."""
    lang = language_name(loc)
    return (
        f"Generate {count} realistic, varied web search queries that a typical "
        f"person would type into a search engine. Write them in {lang} "
        f"(locale {loc}). Mix everyday topics: news, weather, recipes, sports, "
        f"shopping, how-to, entertainment, technology, health and local "
        f"interests. Keep each query short and natural (about 2 to 6 words), "
        f"with no numbering, no quotes and no explanations. "
        f"Return ONLY a JSON array of {count} distinct strings."
    )


def _log_http_error(logger, provider, resp):
    """Translate a non-2xx response into a clear, actionable log line."""
    if not logger:
        return
    status = resp.status_code
    if status in (401, 403):
        reason = "invalid or unauthorized API key"
    elif status == 429:
        reason = "rate limit or quota exceeded"
    elif status == 402:
        reason = "billing / quota exhausted"
    else:
        reason = f"HTTP {status}"
    snippet = (resp.text or "").replace("\n", " ")[:200]
    logger(f"[WARNING] LLM ({provider}) request failed: {reason}. {snippet}")


def _call_openai(prompt, model, api_key, max_tokens, logger):
    """OpenAI Chat Completions. Returns the model's text answer or ''."""
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 1.0,
            "max_completion_tokens": max_tokens,
        },
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        _log_http_error(logger, "openai", resp)
        return ""
    data = resp.json()
    return data["choices"][0]["message"]["content"] or ""


def _call_anthropic(prompt, model, api_key, max_tokens, logger):
    """Anthropic Messages API. Returns the model's text answer or ''."""
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 1.0,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        _log_http_error(logger, "anthropic", resp)
        return ""
    data = resp.json()
    blocks = data.get("content", [])
    return "".join(b.get("text", "") for b in blocks if isinstance(b, dict))


def _call_gemini(prompt, model, api_key, max_tokens, logger):
    """Google Gemini generateContent. Returns the model's text answer or ''."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 1.0,
                "maxOutputTokens": max_tokens,
            },
        },
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        _log_http_error(logger, "gemini", resp)
        return ""
    data = resp.json()
    candidates = data.get("candidates") or [{}]
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


_DISPATCH = {
    "openai": _call_openai,
    "anthropic": _call_anthropic,
    "gemini": _call_gemini,
}


def _extract_queries(text, count):
    """Parse a JSON array of strings out of the model's text answer.

    Tolerates code fences and surrounding prose by locating the outermost
    ``[...]`` span. Returns a de-duplicated, order-preserving list capped at
    `count`.
    """
    if not text:
        return []

    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []

    end += 1
    try:
        data = json.loads(text[start:end])
    except (ValueError, TypeError):
        return []

    if not isinstance(data, list):
        return []

    out = []
    for item in data:
        if isinstance(item, str):
            query = item.strip().strip('"').strip()
            if query:
                out.append(query)

    # De-duplicate while preserving order, then cap at the requested count.
    return list(dict.fromkeys(out))[:count]


def generate_queries(
    count, locale, provider="openai", model="", api_key="", logger=None
):
    """Generate up to `count` search queries in `locale`'s language via an LLM.

    Args:
        count (int): number of queries to request.
        locale (str): BCP-47 locale (e.g. ``"fr-FR"``) driving the language.
        provider (str): one of ``openai`` / ``anthropic`` / ``gemini``.
        model (str): model id; falls back to the provider default when blank.
        api_key (str): the user's own API key.
        logger (callable, optional): logging function.

    Returns:
        list[str]: query strings, or ``[]`` on any failure. Never raises.
    """
    try:
        count = int(count)
    except (TypeError, ValueError):
        return []
    if count <= 0 or not api_key:
        return []

    provider = (provider or "openai").strip().lower()
    caller = _DISPATCH.get(provider)
    if caller is None:
        if logger:
            logger(f"[WARNING] LLM: unsupported provider '{provider}'.")
        return []

    model = (model or "").strip() or DEFAULT_MODELS[provider]
    prompt = _build_prompt(count, locale)

    try:
        text = caller(prompt, model, api_key, _max_tokens(count), logger)
    except requests.RequestException as e:
        if logger:
            logger(f"[WARNING] LLM ({provider}) network error: {e}")
        return []
    except (KeyError, IndexError, ValueError, TypeError) as e:
        if logger:
            logger(f"[WARNING] LLM ({provider}) unexpected response: {e}")
        return []

    queries = _extract_queries(text, count)
    if not queries and logger:
        logger(f"[WARNING] LLM ({provider}) returned no usable queries.")
    return queries
