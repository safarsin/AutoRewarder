"""
Statistics storage + points-balance scraping for a single account.

Two complementary data sources feed the dashboard (see the design choice in
the GUI):

  * Activity counters — exact counts of PC / Mobile searches and Daily Set
    cards completed, accumulated from each run. These drive an *estimated*
    points figure (counters x per-item constants) used as a fallback when the
    real balance can't be scraped.
  * Real balance — the actual "available points" number scraped from
    rewards.bing.com at the end of a run that visits it. This is the source of
    truth for the total, and successive scrapes give the points delta for a
    session.

Persistence mirrors HistoryManager: atomic temp-file writes and graceful
recovery (back up + reset) when the JSON file is unreadable.
"""

import os
import json
from datetime import datetime

# Microsoft Rewards awards roughly these points per item. Used ONLY for the
# estimated-points figure shown when no real balance has been scraped yet;
# the scraped balance always takes precedence as the source of truth.
POINTS_PER_SEARCH = 3
POINTS_PER_CARD = 10

# How many recent days of activity to retain for the dashboard timeline.
# Stored as per-day aggregates (not per-run), so heavy advanced-scheduling days
# — which fire one session per query — can't evict older days.
_DAILY_KEEP = 90

# JS executed on rewards.bing.com (or a Bing SERP) to read the user's current
# available-points balance. Tries a series of known selectors and returns an
# object {value, via, candidates}. `value` is the first plausible integer found
# (thousand separators stripped) or null; `candidates` is a small sample of
# what each selector matched, logged when value is null so the real (locale-
# and version-dependent) DOM can be diagnosed without a live debugger.
# Defensive throughout: any DOM shift just yields a null value and the caller
# falls back to the estimate rather than crashing.
_SCRAPE_BALANCE_JS = r"""
return (function () {
  function toInt(raw) {
    if (raw == null) return null;
    var digits = String(raw).replace(/[^0-9]/g, '');
    if (!digits) return null;
    var n = parseInt(digits, 10);
    return (isFinite(n) && n >= 0) ? n : null;
  }
  // Ordered most-specific first. The available-points balance lives inside the
  // <mee-rewards-user-status-banner-balance> component as
  //   <p class="pointsValue"><mee-rewards-counter-animation>
  //       <span aria-label="9 494 ">9 494</span> ...
  // The span's aria-label is the authoritative final value (its text content
  // animates up from a lower number). Every selector MUST be scoped to the
  // balance component: the same .pointsValue markup is reused for "daily
  // points", "streak" and "referral" tiles, so an unscoped .pointsValue could
  // read (and persist) the wrong number. #id_rc / #fly_id_rc are the Bing SERP
  // rewards counter — a distinct element, not a decoy tile — used as a fallback
  // when the dashboard isn't loaded.
  var selectors = [
    'mee-rewards-user-status-banner-balance .pointsValue span[aria-label]',
    'mee-rewards-user-status-banner-balance mee-rewards-counter-animation span',
    'mee-rewards-user-status-banner-balance .pointsValue',
    '#balanceToolTipDiv .pointsValue',
    '#fly_id_rc', '#id_rc'
  ];
  var candidates = [];
  for (var i = 0; i < selectors.length; i++) {
    var nodes = document.querySelectorAll(selectors[i]);
    for (var j = 0; j < nodes.length; j++) {
      var el = nodes[j];
      var aria = el.getAttribute('aria-label');
      var txt = (el.textContent || '').replace(/\s+/g, ' ').trim();
      // aria-label is the reliable final value; text content may be mid-animation.
      var val = toInt(aria);
      if (val == null) val = toInt(txt);
      if (candidates.length < 14) {
        candidates.push(selectors[i] + ' => "' + (aria || txt).slice(0, 32) + '" [' + val + ']');
      }
      if (val != null && val >= 0) {
        return {
          value: val, via: selectors[i], candidates: candidates,
          url: location.href, title: document.title
        };
      }
    }
  }
  return {
    value: null, via: null, candidates: candidates,
    url: location.href, title: document.title
  };
})();
"""


def scrape_points_balance_debug(driver):
    """
    Run the balance-scraping JS and return its raw diagnostic object:
    {value, via, candidates, url, title}. `value` is the int balance or None.
    Returns a minimal dict with an `error` key if the JS itself failed. Used by
    the caller to both extract the balance and surface a diagnostic when it
    isn't found (which page were we on? what did the selectors match?).
    """
    try:
        result = driver.execute_script(_SCRAPE_BALANCE_JS)
    except Exception as e:
        return {"value": None, "via": None, "candidates": [], "error": str(e)[:120]}

    if isinstance(result, dict):
        return result
    if isinstance(result, (int, float)) and not isinstance(result, bool):
        return {"value": result, "via": "legacy", "candidates": []}
    return {"value": None, "via": None, "candidates": []}


def scrape_points_balance(driver, logger=None):
    """
    Read the current Microsoft Rewards available-points balance from the page
    the driver is currently on (expected to be rewards.bing.com or a Bing
    results page where the rewards counter is visible).

    Logs the value on success; stays silent on failure (raw debug details are
    available via scrape_points_balance_debug for the dashboard's on-demand
    refresh diagnostic).

    Args:
        driver: Selenium WebDriver, already navigated to a page that shows the
            rewards balance.
        logger (callable, optional): logging function.

    Returns:
        int | None: the scraped balance, or None if it couldn't be read.
    """
    info = scrape_points_balance_debug(driver)
    value = info.get("value")

    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        balance = int(value)
        if logger:
            logger(f"Points balance scraped: {balance:,}")
        return balance

    # Not found: stay silent in the activity feed. The raw debug info is
    # available via scrape_points_balance_debug() for the dashboard's on-demand
    # refresh diagnostic.
    return None


class StatsManager:
    """
    Manages the statistics file for a single account. Each instance is bound to
    a specific stats.json file path.
    """

    def __init__(self, stats_file, logger=None):
        """
        Args:
            stats_file (str): Absolute path to this account's stats.json.
            logger (callable, optional): Logging function.
        """
        self.stats_file = stats_file
        self._logger = logger

    def _log(self, message):
        if self._logger:
            self._logger(message)

    @staticmethod
    def _default():
        """Return a fresh, fully-populated stats structure."""
        return {
            # Cumulative totals over the account's whole lifetime.
            "lifetime": {
                "pc_searches": 0,
                "mobile_searches": 0,
                "daily_cards": 0,
                "runs": 0,
                "points_estimate": 0,
            },
            # Real scraped balance (source of truth for the total). `previous`
            # is the value before the most recent scrape, used for the delta.
            "balance": {
                "current": None,
                "previous": None,
                "updated_at": None,
            },
            # Snapshot of the most recently recorded run.
            "last_session": {
                "ended_at": None,
                "pc_searches": 0,
                "mobile_searches": 0,
                "daily_cards": 0,
                "points_estimate": 0,
                "points_delta": None,
            },
            # Per-day activity aggregates for the dashboard timeline, keyed by
            # "YYYY-MM-DD" → {pc, mobile, cards, runs}. Capped to _DAILY_KEEP
            # days. Per-day (not per-run) so a busy day can't evict old days.
            "daily": {},
        }

    @staticmethod
    def _trim_daily(daily):
        """Keep only the most recent _DAILY_KEEP days (by sorted date key)."""
        if not isinstance(daily, dict):
            return {}
        keys = sorted(daily.keys())
        for k in keys[:-_DAILY_KEEP]:
            daily.pop(k, None)
        return daily

    @staticmethod
    def _daily_from_runs(runs):
        """
        Build per-day aggregates from the legacy per-run `runs` list, so an
        existing stats.json keeps whatever history its rolling window still has.
        """
        daily = {}
        for r in runs:
            if not isinstance(r, dict):
                continue
            day = str(r.get("ts", ""))[:10]
            if len(day) != 10:
                continue
            bucket = daily.setdefault(
                day, {"pc": 0, "mobile": 0, "cards": 0, "runs": 0}
            )
            bucket["pc"] += int(r.get("pc", 0) or 0)
            bucket["mobile"] += int(r.get("mobile", 0) or 0)
            bucket["cards"] += int(r.get("cards", 0) or 0)
            bucket["runs"] += 1
        return daily

    def _merge_defaults(self, data):
        """Overlay stored data onto the default shape so missing keys can't KeyError."""
        merged = self._default()
        if not isinstance(data, dict):
            return merged
        for section in ("lifetime", "balance", "last_session"):
            stored = data.get(section)
            if isinstance(stored, dict):
                merged[section].update(stored)

        # Prefer the new per-day aggregates; otherwise migrate from any legacy
        # per-run `runs` list left in an older stats.json.
        daily = data.get("daily")
        if isinstance(daily, dict):
            merged["daily"] = self._trim_daily(dict(daily))
        elif isinstance(data.get("runs"), list):
            merged["daily"] = self._trim_daily(self._daily_from_runs(data["runs"]))
        return merged

    def get_stats(self):
        """
        Retrieve the statistics from the JSON file. Returns a fresh default
        structure if the file is missing; recovers (back up + reset) if it is
        unreadable, mirroring HistoryManager.
        """
        if not os.path.exists(self.stats_file) or os.path.getsize(self.stats_file) == 0:
            return self._default()

        try:
            with open(self.stats_file, "r", encoding="utf-8") as file:
                data = json.load(file)
                if not isinstance(data, dict):
                    raise ValueError("Stats data must be an object")
                return self._merge_defaults(data)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            self._log(
                "[ERROR] Stats file was unreadable or damaged. Starting with a fresh one."
            )
            backup_path = self.stats_file + ".backup"
            if os.path.exists(backup_path):
                os.remove(backup_path)
            os.replace(self.stats_file, backup_path)
            fresh = self._default()
            self.save_stats(fresh)
            return fresh

    def save_stats(self, data):
        """Save the statistics to the JSON file atomically via a temp file."""
        os.makedirs(os.path.dirname(self.stats_file), exist_ok=True)
        temp_file = self.stats_file + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)
        os.replace(temp_file, self.stats_file)

    def update_balance(self, balance):
        """
        Update only the real points balance, without recording any activity or
        run. Used by the on-launch / manual balance refresh, which scrapes the
        balance outside of a normal run.

        Args:
            balance (int | None): the freshly scraped balance. None is a no-op.

        Returns:
            dict: the updated stats structure (also persisted to disk).
        """
        if balance is None:
            return self.get_stats()

        stats = self.get_stats()
        stats["balance"]["previous"] = stats["balance"]["current"]
        stats["balance"]["current"] = int(balance)
        stats["balance"]["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.save_stats(stats)
        return stats

    def record_session(
        self, pc_searches=0, mobile_searches=0, daily_cards=0, balance=None
    ):
        """
        Record one completed run: bump lifetime counters, refresh the
        last-session snapshot, fold in a freshly-scraped balance (if any), and
        add this run's activity to today's per-day aggregate.

        Args:
            pc_searches (int): successful PC searches this run.
            mobile_searches (int): successful Mobile searches this run.
            daily_cards (int): Daily Set / More Activities cards newly completed.
            balance (int | None): scraped real balance, or None if unavailable.

        Returns:
            dict: the updated stats structure (also persisted to disk).
        """
        pc = max(0, int(pc_searches or 0))
        mobile = max(0, int(mobile_searches or 0))
        cards = max(0, int(daily_cards or 0))

        # Nothing happened (e.g. an empty batch in advanced scheduling and no
        # balance to refresh) — don't pollute the timeline with a no-op run.
        if pc == 0 and mobile == 0 and cards == 0 and balance is None:
            return self.get_stats()

        stats = self.get_stats()
        session_estimate = (
            pc * POINTS_PER_SEARCH
            + mobile * POINTS_PER_SEARCH
            + cards * POINTS_PER_CARD
        )

        lifetime = stats["lifetime"]
        lifetime["pc_searches"] += pc
        lifetime["mobile_searches"] += mobile
        lifetime["daily_cards"] += cards
        lifetime["runs"] += 1
        lifetime["points_estimate"] += session_estimate

        now_iso = datetime.now().isoformat(timespec="seconds")

        # Balance delta: difference against the previously-stored balance. Only
        # meaningful when we have both a fresh scrape and a prior value.
        points_delta = None
        if balance is not None:
            prior = stats["balance"]["current"]
            if isinstance(prior, int):
                points_delta = balance - prior
            stats["balance"]["previous"] = prior
            stats["balance"]["current"] = balance
            stats["balance"]["updated_at"] = now_iso

        stats["last_session"] = {
            "ended_at": now_iso,
            "pc_searches": pc,
            "mobile_searches": mobile,
            "daily_cards": cards,
            "points_estimate": session_estimate,
            "points_delta": points_delta,
        }

        # Fold this run into today's per-day aggregate.
        today = now_iso[:10]
        bucket = stats["daily"].setdefault(
            today, {"pc": 0, "mobile": 0, "cards": 0, "runs": 0}
        )
        bucket["pc"] += pc
        bucket["mobile"] += mobile
        bucket["cards"] += cards
        bucket["runs"] += 1
        stats["daily"] = self._trim_daily(stats["daily"])

        self.save_stats(stats)
        return stats
