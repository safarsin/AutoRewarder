"""
RewardsCard — DOM operations on a Rewards dashboard card.

Wraps every JS heuristic from `card_js` into a typed Python method, plus the
click-target geometry check and the click + tab-management dance. Constructed
once per `perform_daily_set` call (the heuristics are stateless; one instance
covers the whole run).

Failures (stale element, JS error) are swallowed with sensible defaults:
- DOM checks default to `False` — better to attempt a click than skip a card.
- `is_visible` defaults to `True` — same logic, and lets MS's frequent re-renders
  not silently drop real cards.
- `click` returns `False` on failure so the caller can move on.
"""

import random
import time

from selenium.webdriver.common.by import By

from .card_js import (
    CARD_COMPLETED_JS,
    CARD_DIAGNOSE_JS,
    CARD_EXCLUDED_JS,
    CARD_HAS_POINTS_JS,
    CARD_LOCKED_JS,
    CARD_TITLE_JS,
    CARD_VISIBLE_JS,
    CardStatus,
)

# Inner anchor used by Rewards cards. We click this rather than the card root
# because (a) the root often re-renders to 0x0 during SPA updates, and (b)
# only the anchor carries the `ng-click` handler that triggers the points URL.
CLICKABLE_SELECTOR = "a.ds-card-sec, a[role='link'][href]"


class RewardsCard:
    """
    DOM-side helpers for a single Rewards card. One instance per browser
    session (driver).
    """

    def __init__(self, driver, logger=None):
        self.driver = driver
        self.logger = logger

    def _log(self, message):
        if self.logger:
            self.logger(message)

    # -- Classification helpers ------------------------------------------------

    def is_visible(self, card):
        """
        True if the card root is visually rendered. False when the card lives
        in a hidden subtree (e.g. tomorrow's Daily Set group is kept in the
        DOM with `ng-hide`/`display:none`).
        """
        try:
            return bool(self.driver.execute_script(CARD_VISIBLE_JS, card))
        except Exception:
            # If we can't tell, assume visible — better to attempt a click
            # than silently drop a real card.
            return True

    def is_completed(self, card):
        """True if the card visually shows as already completed."""
        try:
            return bool(self.driver.execute_script(CARD_COMPLETED_JS, card))
        except Exception:
            return False

    def is_locked(self, card):
        """True if the card is locked / not yet available (e.g. tomorrow's Daily Set)."""
        try:
            return bool(self.driver.execute_script(CARD_LOCKED_JS, card))
        except Exception:
            return False

    def has_points(self, card):
        """True if the card visibly renders a points value to be earned."""
        try:
            return bool(self.driver.execute_script(CARD_HAS_POINTS_JS, card))
        except Exception:
            return False

    def is_excluded(self, card, section_name=None):
        """
        True if the card is a sweepstake / punch card / raffle, or — for the
        More Activities section — a promotional banner that doesn't show a
        points value (RAF, extension installs, Microsoft 365 / Xbox offers,
        redemption nudges). Daily Set cards always carry a points value, so
        the no-points check is gated on section to avoid false positives.
        """
        try:
            if bool(self.driver.execute_script(CARD_EXCLUDED_JS, card)):
                return True
        except Exception:
            pass

        if section_name == "More Activities" and not self.has_points(card):
            return True

        return False

    def classify(self, card, section_name=None):
        """
        Single-call classifier. Order matters: locked > excluded > complete >
        incomplete (a locked card that also looks complete is still locked).
        """
        if self.is_locked(card):
            return CardStatus.LOCKED
        if self.is_excluded(card, section_name):
            return CardStatus.EXCLUDED
        if self.is_completed(card):
            return CardStatus.COMPLETE
        return CardStatus.INCOMPLETE

    def get_title(self, card):
        """Best-effort short label for a card (used in the run log)."""
        try:
            t = self.driver.execute_script(CARD_TITLE_JS, card)
        except Exception:
            return ""
        return (t or "").strip()

    def diagnose(self, card):
        """List of visible icon-class fragments — for tuning detection regexes."""
        try:
            return self.driver.execute_script(CARD_DIAGNOSE_JS, card) or []
        except Exception:
            return []

    # -- Click handling --------------------------------------------------------

    def pick_click_target(self, card):
        """
        Pick the most appropriate click target for a card. Rewards is a
        dynamic SPA; containers can temporarily become 0x0 during re-renders,
        so prefer the inner link element when its rect is sane.
        """
        try:
            candidates = card.find_elements(By.CSS_SELECTOR, CLICKABLE_SELECTOR)
        except Exception:
            candidates = []

        for el in candidates:
            try:
                w, h = self.driver.execute_script(
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

    def click(self, card, human, main_tab, label="", stop_event=None):
        """
        Click a single card, handle any new tab(s) it opens, and return to
        the main tab. Returns True on success, False on exception.

        If `stop_event` is set when an exception fires, the failure is
        considered a side-effect of the user stopping the run and not logged
        as a warning (the driver was force-quit, every Selenium call from
        here on will throw HTTPConnectionPool errors).

        Args:
            card: Selenium WebElement representing the Rewards card to click.
            human: An instance of HumanBehavior for performing human-like interactions.
            main_tab: The handle of the main browser tab to return to after clicking.
            label: Optional short label for logging.
            stop_event: Optional threading.Event that signals if the run has been stopped by the user.

        Returns:
            bool: True if the card was clicked and handled successfully, False if an exception occurred.
        """
        click_target = self.pick_click_target(card)

        try:
            # Skip elements that are temporarily 0x0 (Rewards SPA re-renders a lot).
            try:
                w, h = self.driver.execute_script(
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
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
                    click_target,
                )
                time.sleep(random.uniform(0.4, 0.8))
            except Exception:
                pass

            before_tabs = set(self.driver.window_handles)

            # scroll_into_view=False here because we just scrolled above —
            # letting the human-like mouse movement re-scroll causes a
            # visible "jump" on the rewards page.
            human.click_element(click_target, scroll_into_view=False)
            time.sleep(random.uniform(2, 4))

            new_tabs = [
                h
                for h in self.driver.window_handles
                if h != main_tab and h not in before_tabs
            ]
            for tab in new_tabs:
                self.driver.switch_to.window(tab)
                time.sleep(random.uniform(2, 4))
                human.scroll_page()
                self.driver.close()

            self.driver.switch_to.window(main_tab)
            time.sleep(random.uniform(1, 2))
            return True

        except Exception as e:
            if stop_event is not None and stop_event.is_set():
                # Stop in flight: driver was force-quit, swallow follow-up errors.
                return False
            short_error = str(e).split("\n")[0][:160]
            label_str = f" {label}" if label else ""
            self._log(f"[WARNING] Card{label_str} click failed: {short_error}")

            # Close any extra tabs, switch back to the main tab.
            try:
                for tab in list(self.driver.window_handles):
                    if tab != main_tab:
                        self.driver.switch_to.window(tab)
                        self.driver.close()
            except Exception:
                pass
            try:
                self.driver.switch_to.window(main_tab)
            except Exception:
                pass
            time.sleep(random.uniform(0.5, 1.0))
            return False
