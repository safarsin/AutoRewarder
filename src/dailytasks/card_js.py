"""
JavaScript heuristics + CardStatus enum used by RewardsCard.

These run inside the Rewards SPA via Selenium's `driver.execute_script`. Each
heuristic is a self-contained JS program that takes a card root element as
`arguments[0]` and returns a value. The heuristics share two helper functions
(`classOf` and `isVisible`) defined once in `_JS_HELPERS` and prepended to
each body — keeping the originals in sync across 5 separate JS strings was
the source of subtle bugs.

Each public `CARD_*_JS` constant is `_JS_HELPERS + _CARD_*_BODY_JS`. Unused
helpers in a given body are harmless (no perf cost, no warning).
"""

from enum import Enum


class CardStatus(str, Enum):
    """
    Outcome of classifying a Rewards card. Subclasses `str` so existing
    `list.count("locked")`-style usage stays backward-compatible during any
    transition; the enum values are the same lowercase tokens used before.
    """

    LOCKED = "locked"
    EXCLUDED = "excluded"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


# Shared helpers prepended to every CARD_*_JS string. Defining them once
# keeps `isVisible` and `classOf` in sync across heuristics.
_JS_HELPERS = r"""
function classOf(el) {
    var c = el && el.className;
    if (typeof c === 'string') return c;
    if (c && typeof c.baseVal === 'string') return c.baseVal;
    return '';
}

function isVisible(el) {
    if (!el) return false;
    var rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    var style = window.getComputedStyle(el);
    if (!style) return true;
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    if (parseFloat(style.opacity) === 0) return false;
    return true;
}

"""


# Decides whether a Rewards card is already completed.
#
# Tighter rules (the previous broad version matched any descendant class
# containing "complete" — including hidden state markers MS keeps in the DOM
# for both states, which produced false positives):
#   1. Only specific, well-known completion icon classes (full word match).
#   2. The icon must be visible (non-zero rect, not display:none, not
#      visibility:hidden, not opacity:0). MS includes BOTH the AddMedium
#      ("+") icon and the CompletedSolid/SkypeCheck icon in every card; only
#      the relevant one is visible.
#   3. As a softer fallback, accept an explicit completion phrase in the
#      card's aria-label only.
# When in doubt, return false — a false negative means we re-click a card
# that's already done (mildly wasteful), but a false positive means we skip
# a card that needed clicking.
_CARD_COMPLETED_BODY_JS = r"""
var card = arguments[0];
if (!card) return false;

// Broad completion-class fragments. MS varies these by SPA version, so we
// accept multiple substrings, word-bounded, and explicitly skip "incomplete".
var COMPLETED_RE =
    /(?:^|[ -])(?:mee-icon-completedsolid|mee-icon-skypecheck|mee-icon-skypecirclecheck|mee-icon-checkmark|mee-icon-completed|mee-icon-accept|completedsolid|skypecheck|checkmark|completed)(?:$|[ -])/i;
var INCOMPLETE_RE =
    /(?:^|[ -])(?:mee-icon-addmedium|addmedium|mee-icon-add)(?:$|[ -])/i;

var nodes = card.querySelectorAll('[class*="icon"], [class*="Icon"]');
var foundComplete = false;
var foundIncomplete = false;
for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    var cls = classOf(el).toLowerCase();
    if (!cls) continue;
    if (/incomplete/.test(cls)) continue;
    if (!isVisible(el)) continue;
    if (COMPLETED_RE.test(cls)) { foundComplete = true; break; }
    if (INCOMPLETE_RE.test(cls)) foundIncomplete = true;
}

if (foundComplete) return true;
if (foundIncomplete) return false;

// Card-level fallbacks: aria-label / data-* attributes that signal state.
var aria = (card.getAttribute('aria-label') || '').toLowerCase();
if (aria && !/incomplete/.test(aria)) {
    if (/\b(completed|already collected|task complete|task complete\.|done)\b/.test(aria)) {
        return true;
    }
}
var dataState = (
    (card.getAttribute('data-state') || '') + ' ' +
    (card.getAttribute('data-status') || '') + ' ' +
    (card.getAttribute('data-bi-promotedstatus') || '')
).toLowerCase();
if (/\b(complete|completed|done)\b/.test(dataState)) return true;

return false;
"""


# Detects cards whose root element is not actually visible to the user.
# MS keeps tomorrow's Daily Set in the DOM next to today's, wrapped in a
# `<mee-card-group ng-hide>` (display:none) — our card selector matches
# both groups, so we'd otherwise count 6 cards and try to click 3 zero-
# sized phantoms.
_CARD_VISIBLE_BODY_JS = r"""
return isVisible(arguments[0]);
"""


# Detects cards that are locked (only available later — tomorrow's Daily
# Set, future weekly More Activities). Multiple signals because MS doesn't
# always use the `card-banner-locked` class consistently:
#   - Visible "locked" / "card-banner-locked" / "mee-rewards-card-banner-locked"
#     class anywhere in the card subtree.
#   - Visible mee-icon-Lock / generic *icon-lock* class.
#   - aria-disabled="true" / data-locked="true" on the card root.
#   - Visible "Available" / "Disponible" / "Tomorrow" / "Demain" hint text.
_CARD_LOCKED_BODY_JS = r"""
var card = arguments[0];
if (!card) return false;

// Check for explicit "unlocked" signals first.
var unlockedCandidates = card.querySelectorAll('[class*="unlocked"], [id*="unlocked"], img[src*="unlocked"], img[alt*="unlocked"]');
var isUnlocked = false;
for (var j = 0; j < unlockedCandidates.length; j++) {
    var el = unlockedCandidates[j];
    if (isVisible(el) || (el.tagName === 'IMG' && isVisible(el.parentElement))) {
        isUnlocked = true;
        break;
    }
}
if (isUnlocked) return false;

// 1. Card-level attributes — fast wins.
if ((card.getAttribute('data-locked') || '').toLowerCase() === 'true') return true;
if ((card.getAttribute('aria-disabled') || '').toLowerCase() === 'true') return true;

var LOCKED_RE = /(?:^|[ -])(?:locked|card-banner-locked|mee-rewards-card-banner-locked|mee-icon-lock)(?:$|[ -])/i;

// 2. Card root class.
var selfCls = classOf(card).toLowerCase();
if (LOCKED_RE.test(selfCls) && !/unlocked/.test(selfCls)) return true;

// 3. Visible descendant with a locked-style class.
var classCandidates = card.querySelectorAll('[class*="locked"], [class*="lock-"], [class*="-lock"], [class*="icon-Lock"]');
for (var i = 0; i < classCandidates.length; i++) {
    var el = classCandidates[i];
    var cls = classOf(el).toLowerCase();
    if (!cls) continue;
    if (/unlocked/.test(cls)) continue;
    if (!LOCKED_RE.test(cls)) continue;
    if (isVisible(el)) return true;
}

// 4. Visible "available later" hint text. Word-boundary so we don't
//    misfire on prose that contains the word inside a longer sentence.
var bannerText = (card.innerText || card.textContent || '').toLowerCase();
if (/\b(available\s+(?:tomorrow|in\s+\d|later)|disponible\s+demain|unlocks?\s+(?:tomorrow|in)|d[ée]bloqu[eé][a-z]*\s+(?:demain|le))\b/.test(bannerText)) {
    return true;
}

return false;
"""


# Detects whether a card visibly shows a points value to be earned.
# In the Rewards SPA, every "More Activities" card uses the same template,
# but only point-earning ones render the `<span ng-if="$ctrl.pointsString">N</span>`
# element. Promotional banners (refer-a-friend, extension installs, Microsoft
# 365 / Xbox offers, redemption nudges) leave that ng-if false, so the span
# never reaches the DOM. Checking for a visible `.pointsString` with a number
# is the most reliable filter — far more robust than enumerating promo
# keywords ("sweepstake", "tirage", etc.) which miss new banner formats.
#
# Aria-label was tempting as a fallback ("Gagnez 10 points" framing), but
# promo cards like the refer-a-friend banner inline phrases like "Gagnez
# 7 500 points quand vos amis cherchent" inside the description, which
# false-positives any "earn N" regex. Sticking to the rendered span keeps
# the signal trustworthy.
_CARD_HAS_POINTS_BODY_JS = r"""
var card = arguments[0];
if (!card) return false;

var nodes = card.querySelectorAll('.pointsString, [class*="pointsString"]');
for (var i = 0; i < nodes.length; i++) {
    if (!isVisible(nodes[i])) continue;
    var t = (nodes[i].innerText || nodes[i].textContent || '').trim();
    if (/\d/.test(t)) return true;
}

return false;
"""


# Detects cards that are sweepstakes / punch cards / raffles. These show up
# in the More Activities section but DO NOT award points per click — they
# enter the user into a draw (or are multi-step punch cards). Clicking
# them in the auto-loop would just rack up sweepstake entries with zero
# point value, which is not what we want.
_CARD_EXCLUDED_BODY_JS = r"""
var card = arguments[0];
if (!card) return false;

var EXCLUDED_RE =
    /(?:^|[ -])(?:punch-card|punchcard|punch|sweepstake|sweepstakes|raffle|lottery|tirage|gives?away|prize-?wheel|enter-to-win)(?:$|[ -])/i;

// Card root class.
var selfCls = classOf(card).toLowerCase();
if (EXCLUDED_RE.test(selfCls)) return true;

// Any descendant class hint.
var nodes = card.querySelectorAll(
    '[class*="punch"], [class*="sweepstake"], [class*="raffle"], [class*="lottery"], [class*="tirage"]'
);
for (var i = 0; i < nodes.length; i++) {
    var cls = classOf(nodes[i]).toLowerCase();
    if (EXCLUDED_RE.test(cls)) return true;
}

// Wrapper element name (e.g. <mee-rewards-punch-card>).
var wrapper = card.closest('mee-rewards-punch-card-item-content, mee-rewards-punchcard-card');
if (wrapper) return true;

// Text-based last resort: localized phrases for sweepstakes / draws.
// Word-bounded to avoid catching "tirage" inside larger French words.
var text = (card.innerText || card.textContent || '').toLowerCase();
if (/\b(sweepstake|sweepstakes|enter\s+to\s+win|tirage\s+au\s+sort|grand\s+prize)\b/.test(text)) {
    return true;
}

return false;
"""


# Extracts a short user-facing title for the card, used in the run log so
# the user can follow which task the bot is currently clicking. We try a
# handful of common patterns (h3, .title, link aria-label) and truncate to
# keep log lines readable.
_CARD_TITLE_BODY_JS = r"""
var card = arguments[0];
if (!card) return '';

function clean(s) {
    if (!s) return '';
    return String(s).replace(/\s+/g, ' ').trim().slice(0, 80);
}

// Title-like elements first. Prefer the heading element specifically:
// the points value is rendered in a `<span class="c-heading pointsString">N</span>`
// that appears earlier in the DOM than the title `<h3 class="c-heading">`,
// so a bare `.c-heading` selector picks the number ("10") instead of the
// task name. h3.c-heading is unique to titles in the Rewards card template.
var titleSelectors = [
    'h3.title',
    '.title h3',
    'h3.c-heading',
    '.cardText',
    '.title',
    'h3',
    '[data-bi-name="title"]'
];
for (var i = 0; i < titleSelectors.length; i++) {
    var el = card.querySelector(titleSelectors[i]);
    if (!el) continue;
    var t = clean(el.innerText || el.textContent);
    if (t && t.length >= 2) return t;
}

// Fallback: aria-label of the clickable link is usually the full task name.
var link = card.querySelector('a.ds-card-sec, a[role="link"][href]');
if (link) {
    var aria = link.getAttribute('aria-label');
    if (aria) return clean(aria);
}

// Last resort: first non-empty line of card text.
var text = (card.innerText || card.textContent || '').trim();
if (text) {
    var lines = text.split(/\n|\s{3,}/).map(function (s) { return s.trim(); });
    for (var j = 0; j < lines.length; j++) {
        if (lines[j].length >= 2) return clean(lines[j]);
    }
}
return '';
"""


# Diagnostic dump: returns a short list of icon-class fragments visible on
# the card, used only when normal detection seems off (e.g. 0 of N detected).
# Lets us refine the regex without re-reading the whole DOM.
_CARD_DIAGNOSE_BODY_JS = r"""
var card = arguments[0];
if (!card) return [];

var seen = [];
var iconish = card.querySelectorAll('[class*="icon"], [class*="Icon"]');
for (var i = 0; i < iconish.length; i++) {
    var el = iconish[i];
    if (!isVisible(el)) continue;
    var cls = classOf(el).trim();
    if (!cls) continue;
    // Keep only fragments that look like icon-name tokens.
    var tokens = cls.split(/\s+/).filter(function (t) {
        return /icon/i.test(t);
    });
    if (tokens.length) seen.push(tokens.join(' '));
}
return seen.slice(0, 4);
"""


# Public exports — full JS programs ready to feed to driver.execute_script.
CARD_COMPLETED_JS = _JS_HELPERS + _CARD_COMPLETED_BODY_JS
CARD_VISIBLE_JS = _JS_HELPERS + _CARD_VISIBLE_BODY_JS
CARD_LOCKED_JS = _JS_HELPERS + _CARD_LOCKED_BODY_JS
CARD_HAS_POINTS_JS = _JS_HELPERS + _CARD_HAS_POINTS_BODY_JS
CARD_EXCLUDED_JS = _JS_HELPERS + _CARD_EXCLUDED_BODY_JS
CARD_TITLE_JS = _JS_HELPERS + _CARD_TITLE_BODY_JS
CARD_DIAGNOSE_JS = _JS_HELPERS + _CARD_DIAGNOSE_BODY_JS
