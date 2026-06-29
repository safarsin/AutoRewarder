"""
DailySet — orchestration of the Microsoft Rewards click-through tasks.

Status persistence (today-marker JSON) + section-by-section processing of the
Daily Set and "More Activities" / "Plus d'activité" rows on rewards.bing.com.
DOM-side card detection and click logic live in `RewardsCard` (card.py); this
module just decides which sections exist, classifies their cards, and loops.
"""

import json
import os
import random
import time
from datetime import date

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .card import RewardsCard
from .card_js import CardStatus

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


class DailySet:
    """
    Manages the Daily Set + More Activities tasks in Microsoft Rewards,
    scoped to one account.
    """

    def __init__(self, status_file, logger=None):
        """
        Args:
            status_file (str): Absolute path to this account's status.json.
            logger (callable, optional): A function to log messages. Defaults to None.
        """
        self.status_file = status_file
        self.logger = logger
        # Filled in on each `perform_daily_set` call after the driver is ready.
        self.cards = None
        # Aggregated card counts from the most recent perform_daily_set call,
        # so the caller (api) can record `newly` completed cards in the stats
        # layer without changing this method's bool return contract.
        self.last_totals = {
            "already": 0,
            "newly": 0,
            "final": 0,
            "total": 0,
            "attempted": 0,
        }

    def _log(self, message):
        if self.logger:
            self.logger(message)

    # -- Status persistence ----------------------------------------------------

    def should_perform_daily_set(self):
        """
        Check if the Daily Set has already been completed today.

        Returns:
            bool: True if the Daily Set should be performed, False if it has
                  already been completed today.
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
        """Mark the daily set as completed for today."""
        today = str(date.today())

        data = {}
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, "r", encoding="utf-8") as file:
                    data = json.load(file)
            except Exception:
                self._log(f"[ERROR] Failed to read status file: {self.status_file}")

        data["last_daily_set_date"] = today

        # Atomic write to reduce the chance of leaving a partially-written JSON file.
        os.makedirs(os.path.dirname(self.status_file), exist_ok=True)
        temp_file = self.status_file + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(data, file)
        os.replace(temp_file, self.status_file)

    # -- Section processing ----------------------------------------------------

    def _process_section(
        self, driver, human, section_name, selector, main_tab, stop_event=None
    ):
        """
        Process one card section (Daily Set or More Activities). Returns a
        dict {already, newly, final, total, attempted} so the caller can
        aggregate stats across sections and make the mark-as-done decision.

        Args:
            driver: Selenium WebDriver instance.
            human: An instance of HumanBehavior for performing human-like interactions.
            section_name: The name of the section being processed (e.g. "Daily Set", "More Activities"), used for logging.
            selector: The CSS selector to find cards within this section.
            main_tab: The handle of the main browser tab to return to after processing.
            stop_event: Optional threading.Event that signals if the run has been stopped by the user.

        Returns:
            dict: A dictionary containing counts of card statuses:
                {
                    "already": int,  # Number of cards already completed before processing.
                    "newly": int,    # Number of cards newly completed during processing.
                    "final": int,    # Total number of cards completed after processing.
                    "total": int,    # Total number of actionable cards (excluding locked/excluded).
                    "attempted": int # Number of cards that the bot attempted to click.
                }
        """
        all_cards = driver.find_elements(By.CSS_SELECTOR, selector)
        if not all_cards:
            self._log(f"[INFO] No {section_name} cards on page.")
            return {"already": 0, "newly": 0, "final": 0, "total": 0, "attempted": 0}

        # Drop cards whose root is hidden (tomorrow's Daily Set lives in the
        # same DOM as today's, wrapped in an `ng-hide` group). Without this,
        # we'd report misleading "X/6 already complete, attempting 3 remaining"
        # where the 3 remaining are tomorrow's phantoms.
        cards = [c for c in all_cards if self.cards.is_visible(c)]
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
        # Excluded = sweepstakes / punch / promo banners (no per-click points).
        # Both are skipped and excluded from the 'X/Y' count.
        statuses = [self.cards.classify(c, section_name) for c in cards]

        locked_count = statuses.count(CardStatus.LOCKED)
        excluded_count = statuses.count(CardStatus.EXCLUDED)
        already_complete = statuses.count(CardStatus.COMPLETE)
        incomplete_indices = [
            i for i, s in enumerate(statuses) if s == CardStatus.INCOMPLETE
        ]
        total_actionable = len(cards) - locked_count - excluded_count

        if locked_count:
            self._log(
                f"{section_name}: {locked_count} card(s) locked (unlocks later) — skipped."
            )
        if excluded_count:
            self._log(
                f"{section_name}: {excluded_count} promo/sweepstake card(s) — skipped (no per-click points)."
            )

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

            # Re-apply the same visibility filter used to build
            # incomplete_indices. Without it, tomorrow's hidden cards
            # (kept in the DOM under ng-hide) re-enter the list and
            # shift the indices — we'd then click the wrong card or
            # hit a 0x0 element.
            current_all = driver.find_elements(By.CSS_SELECTOR, selector)
            current = [c for c in current_all if self.cards.is_visible(c)]
            if idx >= len(current):
                self._log(
                    f"[WARNING] {section_name} card #{idx + 1} disappeared between "
                    f"snapshot and click; skipping."
                )
                continue
            target_card = current[idx]

            # State may have shifted (became locked, became complete) while
            # we processed earlier cards.
            current_status = self.cards.classify(target_card, section_name)
            if current_status != CardStatus.INCOMPLETE:
                continue

            title = self.cards.get_title(target_card)
            label = title or f"#{idx + 1}"
            if title:
                self._log(f"  → {section_name} #{idx + 1}: {title}")
            else:
                self._log(f"  → {section_name} #{idx + 1}: clicking…")

            self.cards.click(
                target_card, human, main_tab, label=label, stop_event=stop_event
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
            if self.cards.is_visible(c)
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
            status = self.cards.classify(c, section_name)
            if status in (CardStatus.LOCKED, CardStatus.EXCLUDED):
                continue
            final_actionable += 1
            if status == CardStatus.COMPLETE:
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

    # -- Top-level entry point -------------------------------------------------

    def perform_daily_set(self, driver, human, stop_event=None):
        """
        Visit the Rewards dashboard and process every click-through task we
        know about: the Daily Set and the "More Activities" / "Plus d'activité"
        section. Cards already marked complete are skipped, and each clicked
        card's status is re-checked after the run to validate progress.

        Args:
            driver: Selenium WebDriver instance.
            human: An instance of HumanBehavior for performing human-like interactions.
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

        # Reset so an early return (timeout, no cards) reports zeros rather
        # than counts left over from a previous run.
        self.last_totals = {
            "already": 0,
            "newly": 0,
            "final": 0,
            "total": 0,
            "attempted": 0,
        }

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

            self.cards = RewardsCard(driver, logger=self.logger)
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

            # Expose the run's aggregated counts for the stats layer.
            self.last_totals = dict(totals)

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
