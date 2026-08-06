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
import random
import re
from datetime import date

import requests

from .locale import language_name

# Provider -> default model used when the user leaves the model field blank.
# The model stays editable in the UI so users can track newer models without a
# code change.
DEFAULT_MODELS = {
    "openai": "gpt-5.4-nano",
    "openrouter": "openai/gpt-5.4-nano",
    "anthropic": "claude-haiku-4-5",
    "gemini": "gemini-3.1-flash-lite",
}

SUPPORTED_PROVIDERS = tuple(DEFAULT_MODELS.keys())
PROVIDER_ALIASES = {
    "9router": "openrouter",
}

_TIMEOUT = 30  # seconds, per request
_ANTHROPIC_VERSION = "2023-06-01"


def normalize_provider(provider):
    """Return the canonical provider id, preserving unknown values for validation."""
    provider = (provider or "openai").strip().lower()
    return PROVIDER_ALIASES.get(provider, provider)


def _max_tokens(count):
    """Rough output-token budget for `count` short JSON-array queries."""
    return min(8192, 512 + count * 30)


def normalize_query(query):
    """Lowercase, strip punctuation, collapse whitespace — repeat-detection key."""
    text = re.sub(r"[^\w\s]", "", str(query or "").lower())
    return re.sub(r"\s+", " ", text).strip()


# Pattern pools per query category. `{loc}` placeholders are formatted at
# prompt-build time; a random subset is shown each call so the model isn't
# anchored to the same strings every day.
_EXAMPLE_POOLS = {
    "Questions people ask themselves": (
        "why is my cat throwing up",
        "how much tithing should i give",
        "when does daylight savings end",
    ),
    "Urgent how-tos": (
        "how to unclog toilet without plunger",
        "reset airpods pro",
        "delete duplicate rows excel",
    ),
    "Navigational shortcuts": (
        "facebook login",
        "weather tomorrow",
        "gmail inbox",
    ),
    "Conversational fragments": (
        "best affordable vacuum 2025",
        "is it gonna snow today",
        "headache that won't go away",
    ),
    "Local/intent-driven": (
        "pizza open now near me",
        "dmv appointment {loc}",
        "cheap oil change {loc}",
    ),
    "Trend/reaction": (
        "who won the debate",
        "stock market down today why",
        "power outage {loc}",
    ),
    "Comparison": (
        "iphone 16 vs samsung s25",
        "uber vs lyft cheaper",
    ),
}


def _build_prompt(count, loc, excluded=None):
    """Phrase the generation instruction in the user's language."""
    lang = language_name(loc)
    lines = [
        f"Generate {count} distinct web search queries that feel ripped from real people's browsers. Language: {lang}, locale: {loc}.",
        "Think like a human with a genuine itch to scratch — not a topic checklist. Every query should be something someone actually typed because they needed to know right then.",
        "",
        "Mix these natural query patterns — examples are style samples only, never emit them verbatim:",
    ]
    for label, examples in _EXAMPLE_POOLS.items():
        shown = random.sample(
            [example.format(loc=loc) for example in examples],
            min(2, len(examples)),
        )
        lines.append("- " + label + ": " + ", ".join(f'"{q}"' for q in shown))
    lines += [
        "",
        f"Today's date: {date.today().isoformat()}. Favor fresh, seasonal, or timely queries.",
        "",
        "Crucial rules:",
        "- Vary length: some 2-3 words, some 5-8 words. Real queries are uneven.",
        "- Skip perfect grammar. Real people drop articles, use fragments, type lowercase.",
        "- No keyword-stuffing. Nobody types \"best healthy easy quick dinner recipes high protein.\"",
        "- Each query distinct persona/need. Don't remix same template across topics.",
        "- No quotes, no numbering, no markdown, no explanations.",
        "- Queries must survive the \"would anyone actually type this?\" test.",
        "",
        "Anti-patterns to avoid:",
        "- \"sports news today\", \"weather forecast\", \"healthy recipes\" — these are topic labels, not searches.",
        "- Obvious template fills: \"[topic] [year] [modifier]\" across every line.",
    ]
    prompt = "\n".join(lines)

    if excluded:
        prompt += (
            "\n\nRecently used queries you must NOT repeat (exact or near-identical counts as a repeat):\n"
            + "\n".join(f"- {q}" for q in excluded)
        )
    return prompt + f"\n\nReturn ONLY a JSON array of {count} strings."


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
    return _message_text(data) or ""


def _call_openrouter(prompt, model, api_key, max_tokens, logger):
    """OpenRouter OpenAI-compatible chat API. Returns text answer or ''."""
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": "AutoRewarder",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 1.0,
            "max_tokens": max_tokens,
        },
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        _log_http_error(logger, "openrouter", resp)
        return ""
    data = resp.json()
    return _message_text(data) or ""


def _message_text(data):
    """Extract the text answer from an OpenAI-compatible chat response.

    Some models return ``message.content`` as a list of text blocks rather
    than a plain string; handle both shapes.
    """
    content = data["choices"][0]["message"].get("content") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", "") or "")
            elif block:
                parts.append(str(block))
        return "".join(parts)
    return ""


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
    "openrouter": _call_openrouter,
    "anthropic": _call_anthropic,
    "gemini": _call_gemini,
}


def _extract_queries(text, count):
    """Parse a JSON array of strings out of the model's text answer.

    Tolerates code fences, prose, ``{"queries": [...]}``-style objects and
    trailing commas. If nothing JSON-shaped parses, falls back to pulling
    quoted strings out of the raw answer. Returns a de-duplicated,
    order-preserving list capped at `count`.
    """
    if not text:
        return []

    items = _parse_json_queries(text)
    if items is None:
        # Fallback: scan the raw answer for quoted strings. Handles bullet
        # lists and prose when the model skips valid JSON entirely.
        items = []
        for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', text):
            query = m.group(1).replace('\\"', '"').replace("\\\\", "\\").strip()
            if query:
                items.append(query)

    out = [q for q in items if q]

    # De-duplicate while preserving order, then cap at the requested count.
    return list(dict.fromkeys(out))[:count]


def _parse_json_queries(text):
    """Return the query strings from the answer's JSON, or None if unparseable.

    Locates the outermost ``[...]`` span so fences and prose around the array
    are ignored, then accepts either a bare list or an object that wraps one
    (e.g. ``{"queries": [...]}``).
    """
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None

    chunk = text[start:end + 1]
    # Tolerate trailing commas, which models love to emit.
    chunk = re.sub(r",\s*([\]}])", r"\1", chunk)
    try:
        data = json.loads(chunk)
    except (ValueError, TypeError):
        return None

    if isinstance(data, list):
        values = data
    elif isinstance(data, dict):
        values = next((v for v in data.values() if isinstance(v, list)), None)
    else:
        return None

    if not isinstance(values, list):
        return None
    return [item.strip().strip('"').strip() for item in values if isinstance(item, str)]


def generate_queries(
    count, locale, provider="openai", model="", api_key="", logger=None, exclude=None
):
    """Generate up to `count` search queries in `locale`'s language via an LLM.

    Args:
        count (int): number of queries to request.
        locale (str): BCP-47 locale (e.g. ``"fr-FR"``) driving the language.
        provider (str): one of ``openai`` / ``openrouter`` / ``anthropic`` / ``gemini``.
        model (str): model id; falls back to the provider default when blank.
        api_key (str): the user's own API key.
        logger (callable, optional): logging function.
        exclude (list, optional): recently-used queries the result must not repeat.

    Returns:
        list[str]: query strings, or ``[]`` on any failure. Never raises.
    """
    try:
        count = int(count)
    except (TypeError, ValueError):
        return []
    if count <= 0 or not api_key:
        return []

    excluded = [q for q in (exclude or []) if isinstance(q, str) and q.strip()]
    excluded_norm = {normalize_query(q) for q in excluded}

    provider = normalize_provider(provider)
    caller = _DISPATCH.get(provider)
    if caller is None:
        if logger:
            logger(f"[WARNING] LLM: unsupported provider '{provider}'.")
        return []

    model = (model or "").strip() or DEFAULT_MODELS[provider]
    prompt = _build_prompt(count, locale, excluded[:150])

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
    queries = [q for q in queries if normalize_query(q) not in excluded_norm]
    if not queries and logger:
        logger(f"[WARNING] LLM ({provider}) returned no usable queries.")
    return queries
