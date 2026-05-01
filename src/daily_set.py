import json
import os
import random
import time
from datetime import date

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# The Rewards dashboard groups click-through tasks into two sections we can
# automate: the Daily Set (3 cards, refreshed each day) and "More Activities"
# / "Plus d'activité" (variable). Each section has its own wrapper element;
# we process them separately so logs and counts stay meaningful, but the
# inner card structure is the same.
SECTIONS = (
    ("Daily Set", "mee-rewards-daily-set-item-content .rewards-card-container"),
    (
        "More Activities",
        "mee-rewards-more-activities-card-item .rewards-card-container, "
        "mee-rewards-more-activities-card .rewards-card-container",
    ),
)

# Union selector used purely to decide when to give up waiting for the page
# to render — if no cards from either section have appeared, the page never
# loaded properly.
ANY_CARD_SELECTOR = ", ".join(sel for _, sel in SECTIONS)

CLICKABLE_SELECTOR = "a.ds-card-sec, a[role='link'][href]"


# JavaScript heuristic that decides whether a Rewards card is already
# completed. The previous broad version matched any descendant class that
# contained "complete" — including hidden state markers MS keeps in the DOM
# for both states, which produced false positives ("everything is done").
#
# Tighter rules:
#   1. Only specific, well-known completion icon classes (full word match).
#   2. The icon must be visible (non-zero rect, not display:none, not
#      visibility:hidden, not opacity:0). This is the key: MS includes both
#      the AddMedium ("+") icon and the CompletedSolid/SkypeCheck icon in
#      every card; only the relevant one is visible.
#   3. As a softer fallback, accept an explicit completion phrase in the
#      card's aria-label only.
# When in doubt, return false — a false negative means we re-click a card
# that's already done (mildly wasteful), but a false positive means we skip
# a card that needed clicking (the bug we're fixing).
_CARD_COMPLETED_JS = r"""
var card = arguments[0];
if (!card) return false;

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

// Broad completion-class fragments. MS varies these by SPA version, so we
// accept multiple substrings, word-bounded, and explicitly skip "incomplete".
// Built via new RegExp(...) so the alternation can wrap across lines (a
// regex literal /.../ would have to live on a single line).
var COMPLETED_RE = new RegExp(
    "(?:^|[ -])(?:" +
    "mee-icon-completedsolid|mee-icon-skypecheck|mee-icon-skypecirclecheck|" +
    "mee-icon-checkmark|mee-icon-completed|mee-icon-accept|" +
    "completedsolid|skypecheck|checkmark|completed" +
    ")(?:$|[ -])",
    "i"
);
var INCOMPLETE_RE = new RegExp(
    "(?:^|[ -])(?:mee-icon-addmedium|addmedium|mee-icon-add)(?:$|[ -])",
    "i"
);

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
# sized phantoms. `getBoundingClientRect()` reports 0x0 for any element
# with a `display:none` ancestor, which is the cleanest cross-cutting
# signal here; the explicit style checks catch the rare opacity:0 /
# visibility:hidden case where the rect is non-zero.
_CARD_VISIBLE_JS = r"""
var card = arguments[0];
if (!card) return false;
var r = card.getBoundingClientRect();
if (r.width <= 0 || r.height <= 0) return false;
var s = window.getComputedStyle(card);
if (!s) return true;
if (s.display === 'none' || s.visibility === 'hidden') return false;
if (parseFloat(s.opacity) === 0) return false;
return true;
"""


# Detects cards that are locked (only available later — tomorrow's Daily
# Set, future weekly More Activities). Multiple signals because MS doesn't
# always use the `card-banner-locked` class consistently:
#   - Visible "locked" / "card-banner-locked" / "mee-rewards-card-banner-locked"
#     class anywhere in the card subtree.
#   - Visible mee-icon-Lock / generic *icon-lock* class.
#   - aria-disabled="true" / data-locked="true" on the card root.
#   - Visible "Available" / "Disponible" / "Tomorrow" / "Demain" hint text.
_CARD_LOCKED_JS = r"""
var card = arguments[0];
if (!card) return false;

function classOf(el) {
    var c = el && el.className;
    if (typeof c === 'string') return c;
    if (c && typeof c.baseVal === 'string') return c.baseVal;
    return '';
}
function isVisible(el) {
    if (!el) return false;
    var r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    var s = window.getComputedStyle(el);
    if (!s) return true;
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    if (parseFloat(s.opacity) === 0) return false;
    return true;
}

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
// Built via new RegExp(...) so the alternation can wrap across lines.
// Note: \b/\s/\d become \\b/\\s/\\d in the string form (one backslash
// escapes for the JS string lexer, the other reaches the regex engine).
var bannerText = (card.innerText || card.textContent || '').toLowerCase();
var LATER_RE = new RegExp(
    "\\b(" +
    "available\\s+(?:tomorrow|in\\s+\\d|later)" +
    "|disponible\\s+demain" +
    "|unlocks?\\s+(?:tomorrow|in)" +
    "|d[ée]bloqu[eé][a-z]*\\s+(?:demain|le)" +
    ")\\b"
);
if (LATER_RE.test(bannerText)) {
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
_CARD_HAS_POINTS_JS = r"""
var card = arguments[0];
if (!card) return false;

function isVisible(el) {
    if (!el) return false;
    var r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    var s = window.getComputedStyle(el);
    if (!s) return true;
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    if (parseFloat(s.opacity) === 0) return false;
    return true;
}

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
_CARD_EXCLUDED_JS = r"""
var card = arguments[0];
if (!card) return false;

function classOf(el) {
    var c = el && el.className;
    if (typeof c === 'string') return c;
    if (c && typeof c.baseVal === 'string') return c.baseVal;
    return '';
}

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
_CARD_TITLE_JS = r"""
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
_CARD_DIAGNOSE_JS = r"""
var card = arguments[0];
if (!card) return [];

function classOf(el) {
    var c = el && el.className;
    if (typeof c === 'string') return c;
    if (c && typeof c.baseVal === 'string') return c.baseVal;
    return '';
}
function isVisible(el) {
    if (!el) return false;
    var r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    var s = window.getComputedStyle(el);
    if (!s) return true;
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    if (parseFloat(s.opacity) === 0) return false;
    return true;
}

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


class DailySet:
    """
    A class to manage the Daily Set tasks in Microsoft Rewards, scoped to one account.
    """

    def __init__(self, status_file, logger=None):
        """
        Initialize the DailySet manager.

        Args:
            status_file (str): Absolute path to this account's status.json.
            logger (callable, optional): A function to log messages. Defaults to None.
        """

        self.status_file = status_file
        self.logger = logger

    def _log(self, message):
        """
        Log a message using the provided logger, if available.

        Args:
            message (str): The message to log.
        """
        if self.logger:
            self.logger(message)

    def should_perform_daily_set(self):
        """
        Check if the daily set has already been completed today

        Returns:
            bool: True if the daily set should be performed, False if it has already been completed
        """

        today = str(date.today())

        if not os.path.exists(self.status_file):
            return True

        try:
            with open(self.status_file, "r", encoding="utf-8") as file:
                data = json.load(file)
                return data.get("last_daily_set_date") != today
        except Exception:
            self._log(f"[ERROR] Failed to read status file: {self.status_file}")
            return True

    def mark_as_completed(self):
        """
        Mark the daily set as completed for today.
        """
        today = str(date.today())

        data = {}
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, "r", encoding="utf-8") as file:
                    data = json.load(file)
            except Exception:
                self._log(f"[ERROR] Failed to read status file: {self.status_file}")

        data["last_daily_set_date"] = today

        # Write atomically to reduce the chance of leaving a partially-written JSON file.
        os.makedirs(os.path.dirname(self.status_file), exist_ok=True)
        temp_file = self.status_file + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(data, file)
        os.replace(temp_file, self.status_file)

    def _is_card_visible(self, driver, card):
        """
        Return True if the card root is visually rendered. False when the
        card lives in a hidden subtree (e.g. tomorrow's Daily Set group is
        kept in the DOM with `ng-hide`/`display:none`). Treating a hidden
        card as "incomplete" would make the bot try to click a phantom; we
        filter them out before classification so they don't show up in
        counts at all.
        """
        try:
            return bool(driver.execute_script(_CARD_VISIBLE_JS, card))
        except Exception:
            # If we can't tell, assume visible — better to attempt a click
            # than to silently drop a real card.
            return True

    def _is_card_completed(self, driver, card):
        """
        Return True if a Daily Set card visually shows as already completed.

        Failures (stale element, JS error) are treated as "not completed" so the
        bot still attempts the click rather than silently skipping a card.
        """
        try:
            return bool(driver.execute_script(_CARD_COMPLETED_JS, card))
        except Exception:
            return False

    def _is_card_locked(self, driver, card):
        """
        Return True if a card is locked / not yet available (e.g. tomorrow's
        Daily Set entry). Locked cards must not be counted as 'to-do' nor
        clicked — they'd just open a useless tab.
        """
        try:
            return bool(driver.execute_script(_CARD_LOCKED_JS, card))
        except Exception:
            return False

    def _is_card_excluded(self, driver, card, section_name=None):
        """
        Return True if a card is a sweepstake / punch card / raffle, or — for
        the More Activities section — a promotional banner that doesn't show a
        points value (refer-a-friend, extension installs, Microsoft 365 /
        Xbox offers, redemption nudges). Daily Set cards always carry a points
        value, so the no-points check is gated on section to avoid false
        positives there.
        """
        try:
            if bool(driver.execute_script(_CARD_EXCLUDED_JS, card)):
                return True
        except Exception:
            pass

        if section_name == "More Activities":
            try:
                if not bool(driver.execute_script(_CARD_HAS_POINTS_JS, card)):
                    return True
            except Exception:
                return False

        return False

    def _get_card_title(self, driver, card):
        """Best-effort short label for a card (used in the run log)."""
        try:
            t = driver.execute_script(_CARD_TITLE_JS, card)
        except Exception:
            return ""
        return (t or "").strip()

    def _count_completed(self, driver, cards):
        """Tally how many cards in the given list look completed."""
        count = 0
        for c in cards:
            if self._is_card_completed(driver, c):
                count += 1
        return count

    def _pick_click_target(self, driver, card):
        """
        Pick the most appropriate click target for a given card.

        Rewards is a dynamic SPA; containers can temporarily become 0x0 during
        re-renders. Prefer the inner link element when available.
        """
        try:
            candidates = card.find_elements(By.CSS_SELECTOR, CLICKABLE_SELECTOR)
        except Exception:
            candidates = []

        for el in candidates:
            try:
                w, h = driver.execute_script(
                    """
                    const r = arguments[0].getBoundingClientRect();
                    return [r.width, r.height];
                    """,
                    el,
                )
                if float(w) > 6 and float(h) > 6:
                    return el
            except Exception:
                continue
        return card

    def _click_card(self, driver, human, card, label_idx, main_tab, stop_event=None):
        """
        Click a single Daily Set card, handle any new tab(s) it opens, and
        return to the main tab. Returns True on success, False on exception.

        If `stop_event` is set when an exception fires, the failure is
        considered a side-effect of the user stopping the run and not logged
        as a warning (the driver was force-quit, every Selenium call from
        here on will throw HTTPConnectionPool errors).
        """
        click_target = self._pick_click_target(driver, card)

        try:
            # Skip elements that are temporarily 0x0 (Rewards SPA re-renders a lot).
            try:
                w, h = driver.execute_script(
                    """
                    const r = arguments[0].getBoundingClientRect();
                    return [r.width, r.height];
                    """,
                    click_target,
                )
                if float(w) <= 6 or float(h) <= 6:
                    return False
            except Exception:
                pass

            # Scroll the target into view BEFORE the human-like mouse movement.
            # Clicks are dispatched at viewport coordinates derived from
            # getBoundingClientRect(); if the element sits below the fold,
            # those coords get clamped to the viewport edge and the click
            # silently lands on whatever's under that edge (usually empty
            # page chrome) — the link never fires, no points are credited.
            # Daily Set cards are at the top so this rarely bit them, but
            # More Activities point-earning cards (positions 11–19) are
            # always below the fold on first paint.
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
                    click_target,
                )
                time.sleep(random.uniform(0.4, 0.8))
            except Exception:
                pass

            before_tabs = set(driver.window_handles)

            # scroll_into_view=False here because we just scrolled above —
            # letting the human-like mouse movement re-scroll causes a
            # visible "jump" on the rewards page.
            human.click_element(click_target, scroll_into_view=False)
            time.sleep(random.uniform(2, 4))

            new_tabs = [
                h
                for h in driver.window_handles
                if h != main_tab and h not in before_tabs
            ]
            for tab in new_tabs:
                driver.switch_to.window(tab)
                time.sleep(random.uniform(2, 4))
                human.scroll_page()
                driver.close()

            driver.switch_to.window(main_tab)
            time.sleep(random.uniform(1, 2))
            return True

        except Exception as e:
            if stop_event is not None and stop_event.is_set():
                # Stop in flight: driver was force-quit, swallow follow-up errors.
                return False
            short_error = str(e).split("\n")[0][:160]
            self._log(
                f"[WARNING] Daily Set task #{label_idx + 1} failed: {short_error}"
            )

            # Close any extra tabs, switch back to the main tab.
            try:
                for tab in list(driver.window_handles):
                    if tab != main_tab:
                        driver.switch_to.window(tab)
                        driver.close()
            except Exception:
                pass
            try:
                driver.switch_to.window(main_tab)
            except Exception:
                pass
            time.sleep(random.uniform(0.5, 1.0))
            return False

    def _process_section(
        self, driver, human, section_name, selector, main_tab, stop_event=None
    ):
        """
        Process one card section (Daily Set or More Activities). Returns a
        dict {already, newly, final, total, attempted} so the caller can
        aggregate stats across sections and make the mark-as-done decision.
        """
        all_cards = driver.find_elements(By.CSS_SELECTOR, selector)
        if not all_cards:
            self._log(f"[INFO] No {section_name} cards on page.")
            return {"already": 0, "newly": 0, "final": 0, "total": 0, "attempted": 0}

        # Drop cards whose root is hidden (tomorrow's Daily Set lives in the
        # same DOM as today's, wrapped in an `ng-hide` group). Without this,
        # we'd report misleading "X/6 already complete, attempting 3 remaining"
        # where the 3 remaining are tomorrow's phantoms.
        cards = [c for c in all_cards if self._is_card_visible(driver, c)]
        hidden_count = len(all_cards) - len(cards)
        if hidden_count:
            self._log(
                f"{section_name}: {hidden_count} hidden card(s) ignored (likely tomorrow's preview)."
            )
        if not cards:
            self._log(f"[INFO] No visible {section_name} cards on page.")
            return {"already": 0, "newly": 0, "final": 0, "total": 0, "attempted": 0}

        # Bring the section into view once so subsequent clicks aren't blocked
        # by a 0x0 rect on the first card.
        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
                cards[0],
            )
            time.sleep(random.uniform(0.6, 1.2))
        except Exception:
            pass

        # Classify each card: locked / excluded / complete / incomplete.
        # Locked = available later (tomorrow's Daily Set, etc.).
        # Excluded = sweepstakes / punch cards (no per-click points).
        # Both are skipped and excluded from the 'X/Y' count.
        status = []
        for c in cards:
            if self._is_card_locked(driver, c):
                status.append("locked")
            elif self._is_card_excluded(driver, c, section_name):
                status.append("excluded")
            elif self._is_card_completed(driver, c):
                status.append("complete")
            else:
                status.append("incomplete")

        locked_count = status.count("locked")
        excluded_count = status.count("excluded")
        already_complete = status.count("complete")
        incomplete_indices = [i for i, s in enumerate(status) if s == "incomplete"]
        total_actionable = len(cards) - locked_count - excluded_count

        if locked_count:
            self._log(
                f"{section_name}: {locked_count} card(s) locked (unlocks later) — skipped."
            )
        if excluded_count:
            self._log(
                f"{section_name}: {excluded_count} promo/sweepstake card(s) — skipped (no per-click points)."
            )

        # Diagnostic when detection looks off — only fires on sections with
        # actionable cards (excluding locked) where the all-or-nothing pattern
        # is suspicious.
        if total_actionable >= 2 and (
            already_complete == 0 or already_complete == total_actionable
        ):
            try:
                sample = driver.execute_script(_CARD_DIAGNOSE_JS, cards[0])
                if sample:
                    self._log(
                        f"[DIAG] {section_name} card #1 visible icon classes: {sample}"
                    )
            except Exception:
                pass

        if not incomplete_indices:
            if total_actionable == 0:
                self._log(
                    f"{section_name}: all {len(cards)} cards locked, nothing to do."
                )
            else:
                self._log(
                    f"{section_name}: {already_complete}/{total_actionable} already complete."
                )
            return {
                "already": already_complete,
                "newly": 0,
                "final": already_complete,
                "total": total_actionable,
                "attempted": 0,
            }

        self._log(
            f"{section_name}: {already_complete}/{total_actionable} already complete, "
            f"attempting {len(incomplete_indices)} remaining."
        )

        for idx in incomplete_indices:
            if stop_event is not None and stop_event.is_set():
                self._log(f"Stop requested — halting {section_name} loop.")
                break

            current = driver.find_elements(By.CSS_SELECTOR, selector)
            if idx >= len(current):
                self._log(
                    f"[WARNING] {section_name} card #{idx + 1} disappeared between "
                    f"snapshot and click; skipping."
                )
                continue
            target_card = current[idx]

            # State may have shifted (became locked, became complete) while
            # we processed earlier cards.
            if self._is_card_locked(driver, target_card):
                continue
            if self._is_card_excluded(driver, target_card, section_name):
                continue
            if self._is_card_completed(driver, target_card):
                continue

            title = self._get_card_title(driver, target_card)
            if title:
                self._log(f"  → {section_name} #{idx + 1}: {title}")
            else:
                self._log(f"  → {section_name} #{idx + 1}: clicking…")

            self._click_card(
                driver, human, target_card, idx, main_tab, stop_event=stop_event
            )

        # If the user stopped, skip the post-run validation entirely — the
        # driver is dead and we don't want to log misleading 0/N counts.
        if stop_event is not None and stop_event.is_set():
            return {
                "already": already_complete,
                "newly": 0,
                "final": already_complete,
                "total": total_actionable,
                "attempted": len(incomplete_indices),
            }

        # Settle so MS has time to reflect earned points back to the card UI.
        time.sleep(random.uniform(2.5, 4))

        final_cards = [
            c
            for c in driver.find_elements(By.CSS_SELECTOR, selector)
            if self._is_card_visible(driver, c)
        ]
        if not final_cards:
            self._log(
                f"[WARNING] {section_name} cards vanished after run; "
                f"assuming attempted."
            )
            return {
                "already": already_complete,
                "newly": 0,
                "final": already_complete,
                "total": total_actionable,
                "attempted": len(incomplete_indices),
            }

        # Re-tally excluding both locked and excluded (sweepstake) cards.
        final_actionable = 0
        final_complete = 0
        for c in final_cards:
            if self._is_card_locked(driver, c):
                continue
            if self._is_card_excluded(driver, c, section_name):
                continue
            final_actionable += 1
            if self._is_card_completed(driver, c):
                final_complete += 1
        newly_completed = max(0, final_complete - already_complete)

        self._log(
            f"{section_name} result: {final_complete}/{final_actionable} complete "
            f"(+{newly_completed} this run)."
        )

        return {
            "already": already_complete,
            "newly": newly_completed,
            "final": final_complete,
            "total": final_actionable,
            "attempted": len(incomplete_indices),
        }

    def perform_daily_set(self, driver, human, stop_event=None):
        """
        Visit the Rewards dashboard and process every click-through task we
        know about: the Daily Set and the "More Activities" / "Plus d'activité"
        section. Cards already marked complete are skipped, and each clicked
        card's status is re-checked after the run to validate progress.

        Args:
            stop_event (threading.Event, optional): When set, the per-section
                card loop breaks at the next iteration so the run aborts
                cleanly without re-clicking remaining cards.

        Returns:
            bool: True if it's reasonable to mark today as done — either all
                  known cards are now complete, or at least one new card was
                  completed this run. Returns False only when we made zero
                  progress despite having incomplete cards (likely a real
                  failure: broken selectors, login redirect, anti-bot), so
                  the next run can retry.
        """
        self._log("Performing daily Rewards tasks")

        try:
            driver.get("https://rewards.bing.com")

            # Wait for at least one card from any tracked section to render.
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_all_elements_located(
                        (By.CSS_SELECTOR, ANY_CARD_SELECTOR)
                    )
                )
            except TimeoutException:
                self._log("[WARNING] Rewards cards never appeared on the page.")
                return False

            # Brief settle for SPA hydration after the cards mount.
            time.sleep(random.uniform(2, 3))

            try:
                driver.execute_script(
                    "document.documentElement.style.scrollBehavior='auto';"
                    "document.body.style.scrollBehavior='auto';"
                )
            except Exception:
                pass

            main_tab = driver.current_window_handle

            totals = {"already": 0, "newly": 0, "final": 0, "total": 0, "attempted": 0}
            for section_name, selector in SECTIONS:
                if stop_event is not None and stop_event.is_set():
                    self._log("Stop requested — skipping remaining sections.")
                    break
                section_result = self._process_section(
                    driver,
                    human,
                    section_name,
                    selector,
                    main_tab,
                    stop_event=stop_event,
                )
                for k in totals:
                    totals[k] += section_result[k]

            if totals["total"] == 0:
                self._log("[WARNING] No Rewards cards found across any section.")
                return False

            self._log(
                f"All sections: {totals['final']}/{totals['total']} complete "
                f"(+{totals['newly']} this run)."
            )

            if totals["final"] == totals["total"]:
                return True

            if totals["newly"] > 0:
                self._log(
                    "[INFO] Some Rewards cards still incomplete after run "
                    "(likely quizzes / polls that need manual answers). "
                    "Marking today done to avoid retries."
                )
                return True

            if totals["attempted"] == 0:
                # Nothing was incomplete to begin with → already-done state.
                return True

            self._log(
                "[WARNING] No Rewards cards were completed this run. "
                "Will retry on next run."
            )
            return False

        except Exception as e:
            if stop_event is not None and stop_event.is_set():
                # Stop in flight: driver was force-quit, the WebDriver call
                # that raised this is collateral. Log neutrally and return.
                self._log("Rewards tasks halted by Stop.")
                return False
            self._log(f"[ERROR] Failed to collect Rewards tasks: {e}")
            return False
