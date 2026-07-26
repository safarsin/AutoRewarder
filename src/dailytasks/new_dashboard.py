"""
New (Next.js) Microsoft Rewards dashboard — Daily Set handler.

Microsoft's redesigned dashboard is a React/Next.js app: the legacy
`mee-rewards-*` DOM is gone and its Tailwind class names are obfuscated. But the
daily-set data is streamed into the page as an RSC payload (`window.__next_f`)
that contains, for each activity, its `destination` (the Bing search URL the
card links to), `isCompleted`, `points`, `title` and `date`.

Rather than scrape fragile markup, we read that JSON and then visit each
incomplete activity's `destination` — the exact URL a real click would open,
which is what credits the daily-set offer server-side. Completion tracking
(status.json) is handled by the caller (`DailySet`), so this handler only
returns whether it's reasonable to mark today as done.
"""

import random
import time

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

DASHBOARD_URL = "https://rewards.bing.com/dashboard"
EARN_URL = "https://rewards.bing.com/earn"

# Concatenate every streamed RSC chunk (`window.__next_f` is a list of
# `[1, "<chunk>"]` entries) and pull out each `dailySetItems` array, returning
# the parsed items to Python. A balanced-bracket scan that respects string
# literals extracts each array so JSON.parse gets a well-formed slice. The
# payload may repeat the array across chunks; the Python side dedupes by offerId.
_EXTRACT_DAILY_SET_JS = r"""
try {
  var raw = window.__next_f || [];
  var parts = [];
  for (var n = 0; n < raw.length; n++) {
    var e = raw[n];
    if (Array.isArray(e)) { if (typeof e[1] === 'string') parts.push(e[1]); }
    else if (typeof e === 'string') { parts.push(e); }
  }
  var blob = parts.join('');
  var out = [];
  var key = '"dailySetItems"';
  var idx = 0;
  while ((idx = blob.indexOf(key, idx)) !== -1) {
    var i = blob.indexOf('[', idx + key.length);
    if (i === -1) break;
    var depth = 0, inStr = false, esc = false, start = i;
    for (; i < blob.length; i++) {
      var c = blob[i];
      if (inStr) {
        if (esc) esc = false;
        else if (c === '\\') esc = true;
        else if (c === '"') inStr = false;
      } else {
        if (c === '"') inStr = true;
        else if (c === '[') depth++;
        else if (c === ']') { depth--; if (depth === 0) { i++; break; } }
      }
    }
    try {
      var arr = JSON.parse(blob.slice(start, i));
      if (Array.isArray(arr)) { for (var j = 0; j < arr.length; j++) out.push(arr[j]); }
    } catch (err) { /* skip malformed slice */ }
    idx = i;
  }
  return out;
} catch (e) { return []; }
"""

# DOM fallback: read today's daily-set activities straight from the rendered
# `#dailyset` section when the RSC JSON isn't available. The section holds only
# today's cards, each an <a> pointing at the Bing search that credits it.
# Completion is read from the green "success" badge (a design-system class),
# which is language-independent.
_DOM_DAILY_SET_JS = r"""
try {
  var out = [];
  var root = document.getElementById('dailyset');
  if (!root) return out;
  var links = root.querySelectorAll('a[href]');
  for (var i = 0; i < links.length; i++) {
    var a = links[i];
    var href = a.href || a.getAttribute('href') || '';
    // Only real daily-set activities point at a Bing search (this also excludes
    // the section header's "earn more" link, whose absolute href has bing.com).
    if (href.indexOf('bing.com/earn') > 0) continue;
    // Title only: the card's bold title node, not the whole card text.
    var tEl = a.querySelector('.text-globalBody2Strong') || a.querySelector('p');
    var title = tEl ? (tEl.textContent || '').replace(/\s+/g, ' ').trim() : '';
    // Completed cards carry a green "success" badge (language-independent).
    var done = !!a.querySelector('[class*="statusSuccess"]');
    out.push({ destination: href, title: title.slice(0, 80), isCompleted: done, date: null });
  }
  return out;
} catch (e) { return []; }
"""

# The /earn "more activities" (#moreactivities) section: point-earning search
# cards. An earnable, not-yet-done card shows a "+N" points badge; completed ones
# show a green "success" badge instead, and promos (referral, redeem, extension)
# have no "+N" badge — the "+N" gate keeps only the ones worth clicking.
_MORE_ACTIVITIES_JS = r"""
try {
  var out = [];
  var root = document.getElementById('moreactivities');
  if (!root) return out;
  var links = root.querySelectorAll('a[href]');
  for (var i = 0; i < links.length; i++) {
    var a = links[i];
    var href = a.href || a.getAttribute('href') || '';
    if (href.indexOf('bing.com') < 0) continue;
    // Quests are multi-task punchcards handled separately (see _run_quests);
    // their entry card links to /earn/quest/<id>, not a Bing search.
    if (href.indexOf('/earn/quest/') >= 0) continue;
    // Skip completed cards via their green "success" badge (language-independent).
    if (a.querySelector('[class*="statusSuccess"]')) continue;
    var txt = (a.textContent || '').replace(/\s+/g, ' ').trim();
    var m = txt.match(/\+\s*(\d+)/);
    if (!m) continue;
    var tEl = a.querySelector('.text-globalBody2Strong') || a.querySelector('p');
    var title = tEl ? (tEl.textContent || '').replace(/\s+/g, ' ').trim() : '';
    out.push({ destination: href, title: title.slice(0, 80), points: parseInt(m[1], 10) });
  }
  return out;
} catch (e) { return []; }
"""

# Discover /earn "quest" punchcards. Each is an <a> linking to its own
# /earn/quest/<id> page (not a Bing search), with a "+N" points badge and an
# "N/M" progress counter. Both markers are numeric / design-token based, so this
# stays language-independent. The progress lets the caller skip finished quests.
_QUESTS_JS = r"""
try {
  var out = [];
  var seen = {};
  var links = document.querySelectorAll('a[href*="/earn/quest/"]');
  for (var i = 0; i < links.length; i++) {
    var a = links[i];
    var href = a.href || a.getAttribute('href') || '';
    if (!href) continue;
    var key = href.split('?')[0].split('#')[0];
    if (seen[key]) continue;
    seen[key] = 1;
    // Read points and progress from their own elements — NOT the card's
    // concatenated textContent, where adjacent nodes like "+50" and "1/4" merge
    // into "+501/4" and get misparsed. The informative-tint badge shows points
    // to earn; the success badge shows points already earned on a done quest.
    var pts = 0;
    var badge = a.querySelector('[class*="statusInformativeTintFg"]')
             || a.querySelector('[class*="statusSuccess"]');
    if (badge) {
      var bm = (badge.textContent || '').match(/(\d+)/);
      if (bm) pts = parseInt(bm[1], 10);
    }
    // Progress "N/M": the leaf node whose own text IS a fraction (never merged
    // with the neighbouring points badge).
    var done = null, total = null;
    var nodes = a.querySelectorAll('*');
    for (var k = 0; k < nodes.length; k++) {
      if (nodes[k].children.length) continue;
      var pm = (nodes[k].textContent || '').match(/(\d+)\s*\/\s*(\d+)/);
      if (pm) { done = parseInt(pm[1], 10); total = parseInt(pm[2], 10); break; }
    }
    var tEl = a.querySelector('.text-globalBody2Strong') || a.querySelector('p');
    var title = tEl ? (tEl.textContent || '').replace(/\s+/g, ' ').trim() : '';
    out.push({ url: key, title: title.slice(0, 80), points: pts, done: done, total: total });
  }
  return out;
} catch (e) { return []; }
"""

# Read the actionable tasks on a quest page. Tasks live in the design-token
# "rewardsTableAltBg" list; each is a Bing-search link that must be really
# clicked to credit. A task is actionable only if its link is NOT disabled:
# punchcard tasks unlock one per ~24h and carry aria-disabled / data-disabled
# until then, and completed tasks have no link at all.
_QUEST_TASKS_JS = r"""
try {
  var out = [];
  var scope = document.querySelector('[class*="rewardsTableAltBg"]') || document;
  var links = scope.querySelectorAll('[href*="bing.com/search"]');
  for (var i = 0; i < links.length; i++) {
    var el = links[i];
    if ((el.getAttribute('aria-disabled') || '') === 'true') continue;
    if ((el.getAttribute('data-disabled') || '') === 'true') continue;
    if (el.hasAttribute('disabled')) continue;
    // For an <a> el.href is the resolved absolute URL, matching Selenium's
    // get_attribute('href') used to relocate it; a <span role="link"> has no
    // .href property so we keep its raw attribute (also what Selenium returns).
    var href = el.href || el.getAttribute('href') || '';
    if (!href) continue;
    var row = el.closest('div');
    var tEl = row ? row.querySelector('h3, .text-globalBody2Strong') : null;
    var title = tEl ? (tEl.textContent || '').replace(/\s+/g, ' ').trim() : '';
    // The heading ends with a call-to-action sentence (e.g. "... Click to
    // complete."); keep only the first sentence. Language-independent.
    title = title.split('. ')[0].trim();
    out.push({ destination: href, title: title.slice(0, 80) });
  }
  return out;
} catch (e) { return []; }
"""

# Diagnostic snapshot logged when no activities are found, so a failure can be
# understood from the logs (did the RSC chunk stream in? is the section there?).
_DIAG_JS = r"""
try {
  var chunks = window.__next_f || [];
  var parts = [];
  for (var n = 0; n < chunks.length; n++) {
    var e = chunks[n];
    if (Array.isArray(e)) { if (typeof e[1] === 'string') parts.push(e[1]); }
    else if (typeof e === 'string') { parts.push(e); }
  }
  var blob = parts.join('');
  return {
    chunks: chunks.length,
    blobLen: blob.length,
    hasKey: blob.indexOf('"dailySetItems"') >= 0,
    hasDailyset: !!document.getElementById('dailyset'),
    url: location.href,
    title: document.title
  };
} catch (e) { return { error: String(e).slice(0, 120) }; }
"""


class NewDashboardDailySet:
    """Daily Set handler for the new Next.js Microsoft Rewards dashboard."""

    def __init__(self, logger=None):
        """
        Args:
            logger (callable, optional): A function to log messages.
        """
        self.logger = logger
        # Aggregated counts from the most recent `perform` call, mirroring
        # DailySet.last_totals so the stats layer can record new-dashboard
        # runs the same way it records legacy ones. `newly` counts verified
        # daily-set completions only; `earn` and `quests` count the /earn cards
        # and quest tasks opened this run (clicked, not re-verified).
        self.last_totals = {
            "already": 0,
            "newly": 0,
            "final": 0,
            "total": 0,
            "attempted": 0,
            "earn": 0,
            "quests": 0,
        }

    def _log(self, message):
        if self.logger:
            self.logger(message)

    # -- Data extraction -------------------------------------------------------

    def _read_items(self, driver):
        """Read and dedupe the daily-set items embedded in the current page."""
        try:
            raw = driver.execute_script(_EXTRACT_DAILY_SET_JS)
        except Exception as e:
            self._log(f"[WARNING] Could not read new-dashboard data: {e}")
            return []

        if not isinstance(raw, list):
            return []

        # Dedupe by offerId; prefer the record that reports completion so a
        # stale "incomplete" copy in another chunk can't re-trigger a visit.
        by_id = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = item.get("offerId") or item.get("hash") or item.get("destination")
            if key is None:
                continue
            prev = by_id.get(key)
            if prev is None or (
                item.get("isCompleted") and not prev.get("isCompleted")
            ):
                by_id[key] = item
        return list(by_id.values())

    def _read_items_polling(self, driver, attempts=8, delay=1.5):
        """
        Poll `_read_items` until the item set stabilizes. The dashboard streams
        the daily-set RSC chunks progressively, so an early read can catch a
        partial payload (e.g. 2 of 3 cards streamed in at that instant);
        returning on the first non-empty read would silently drop the cards
        still in flight. Done when the count stops changing between two
        consecutive reads, or when the payload drains post-hydration (a
        non-empty snapshot followed by an empty read — nothing more will
        stream). Always returns the largest snapshot seen.
        """
        best = []
        prev_count = None
        for _ in range(max(1, attempts)):
            items = self._read_items(driver)
            if len(items) > len(best):
                best = items
            if best and (not items or len(items) == prev_count):
                return best
            prev_count = len(items)
            time.sleep(delay)
        return best

    @staticmethod
    def _choose_today(json_today, dom_today):
        """
        Pick the trustworthy "today" card set between the two sources.

        The rendered #dailyset section is ground truth for WHICH cards are
        today's (it only ever shows today); the RSC JSON is authoritative for
        completion flags but can be partially streamed — worst case its
        snapshot holds only another, already-completed day, which would read
        as "nothing to do" and silently skip (and mark) the whole set.

        Rules: DOM wins when it sees more of today than the JSON group, or
        when the JSON group shares no destination with the DOM cards (i.e. the
        JSON group is some other day). Otherwise the JSON group wins.

        Returns:
            tuple: (items, source) with source "dom" or "json".
        """
        if len(dom_today) > len(json_today):
            return dom_today, "dom"
        if dom_today:
            dom_dests = {it.get("destination") for it in dom_today}
            if not any(it.get("destination") in dom_dests for it in json_today):
                return dom_today, "dom"
        return json_today, "json"

    def _read_items_dom(self, driver):
        """Fallback: read today's daily-set activities from the rendered DOM."""
        try:
            raw = driver.execute_script(_DOM_DAILY_SET_JS)
        except Exception as e:
            self._log(f"[WARNING] Could not read new-dashboard DOM: {e}")
            return []
        if not isinstance(raw, list):
            return []
        return [it for it in raw if isinstance(it, dict) and it.get("destination")]

    def _diagnostics(self, driver):
        """Return a small diagnostic dict about the current page (for logging)."""
        try:
            info = driver.execute_script(_DIAG_JS)
            return info if isinstance(info, dict) else {}
        except Exception as e:
            return {"error": str(e)[:120]}

    # -- Clicking activities ---------------------------------------------------

    def _expand_section(self, driver, section_id="dailyset"):
        """
        Expand a collapsed section so its cards become visible and clickable.
        react-aria marks the Disclosure toggle with slot="trigger"; clicking it
        when aria-expanded="false" opens the panel.
        """
        try:
            triggers = driver.find_elements(
                By.CSS_SELECTOR, f"#{section_id} button[slot='trigger']"
            )
        except Exception:
            return
        for btn in triggers:
            try:
                if (btn.get_attribute("aria-expanded") or "").lower() == "false":
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(random.uniform(0.6, 1.2))
            except Exception:
                continue

    def _expand_all(self, driver):
        """
        Expand every collapsed react-aria disclosure on the page. Used on /earn,
        where quest punchcards live in their own collapsible panel (not
        #moreactivities) and would otherwise stay unrendered/undiscovered.
        """
        try:
            triggers = driver.find_elements(By.CSS_SELECTOR, "button[slot='trigger']")
        except Exception:
            return
        for btn in triggers:
            try:
                if (btn.get_attribute("aria-expanded") or "").lower() == "false":
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(random.uniform(0.3, 0.6))
            except Exception:
                continue

    def _locate_anchor(self, driver, destination, section_id="dailyset"):
        """
        Find the card <a> matching `destination` in a section by its exact href.

        Returns None when there's no exact match: the activity list is filtered
        (completed cards, quests and badge-less promos are dropped), so a
        positional fallback would index the raw anchors out of step with that
        list and could click the wrong card. Callers fall back to direct
        navigation instead.
        """
        try:
            anchors = driver.find_elements(By.CSS_SELECTOR, f"#{section_id} a[href]")
        except Exception:
            return None
        for a in anchors:
            try:
                if (a.get_attribute("href") or "") == destination:
                    return a
            except Exception:
                continue
        return None

    def _locate_quest_task(self, driver, destination):
        """
        Find the actionable task link for `destination` on a quest page. Unlike
        daily-set cards, a quest task's clickable is a <span role="link"> (not an
        <a>), so this queries by href within the task list and skips disabled
        (locked) links.
        """
        try:
            links = driver.find_elements(
                By.CSS_SELECTOR,
                '[class*="rewardsTableAltBg"] [href*="bing.com/search"]',
            )
        except Exception:
            return None
        for el in links:
            try:
                if (el.get_attribute("aria-disabled") or "").lower() == "true":
                    continue
                if (el.get_attribute("data-disabled") or "").lower() == "true":
                    continue
                if el.get_attribute("href") == destination:
                    return el
            except Exception:
                continue
        return None

    def _click_anchor(
        self,
        driver,
        human,
        anchor,
        main_tab,
        stop_event,
        return_url=DASHBOARD_URL,
        section_id="dailyset",
    ):
        """
        Click a card the way a user does (a real pointer click that opens the
        card's new tab) — this is what credits the offer; a bare navigation to
        the destination URL does not. Handles the new tab (dwell + close) or a
        same-tab navigation.

        On a same-tab navigation, returns to `return_url` and expands
        `section_id` so the caller's remaining anchors stay discoverable (each
        flow — daily set, earn page — has its own page and section). Returns True
        if the click was dispatched and handled.
        """
        try:
            # Skip a card that's momentarily 0x0 (SPA re-render / still collapsed).
            try:
                w, h = driver.execute_script(
                    "const r=arguments[0].getBoundingClientRect();"
                    "return [r.width, r.height];",
                    anchor,
                )
                if float(w) <= 6 or float(h) <= 6:
                    return False
            except Exception:
                pass

            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center', inline:'nearest'});",
                    anchor,
                )
                time.sleep(random.uniform(0.4, 0.8))
            except Exception:
                pass

            before = set(driver.window_handles)
            cur_url = driver.current_url
            human.click_element(anchor, scroll_into_view=False)
            time.sleep(random.uniform(2, 4))

            new_tabs = [
                x for x in driver.window_handles if x != main_tab and x not in before
            ]
            if new_tabs:
                for tab in new_tabs:
                    driver.switch_to.window(tab)
                    # Dwell so the rewards credit beacon on the search page fires.
                    time.sleep(random.uniform(3, 6))
                    try:
                        human.scroll_page()
                    except Exception:
                        pass
                    time.sleep(random.uniform(1, 2))
                    driver.close()
                driver.switch_to.window(main_tab)
                time.sleep(random.uniform(1, 2))
                return True

            if driver.current_url != cur_url:
                # Opened in the same tab: dwell, then return to the caller's
                # page/section so its remaining anchors stay discoverable.
                time.sleep(random.uniform(3, 6))
                try:
                    human.scroll_page()
                except Exception:
                    pass
                driver.get(return_url)
                self._wait_ready(driver)
                time.sleep(random.uniform(1.5, 2.5))
                self._expand_section(driver, section_id)
                return True

            # Nothing happened — click missed.
            return False

        except Exception as e:
            if stop_event is not None and stop_event.is_set():
                return False
            self._log(f"[WARNING] Card click failed: {str(e).splitlines()[0][:140]}")
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
            return False

    @staticmethod
    def _date_key(item):
        """Parse an item's MM/DD/YYYY date into a comparable (Y, M, D) tuple."""
        raw = item.get("date")
        if not isinstance(raw, str):
            return None
        parts = raw.split("/")
        if len(parts) != 3:
            return None
        try:
            month, day, year = (int(p) for p in parts)
        except ValueError:
            return None
        return (year, month, day)

    def _todays_items(self, items):
        """
        Return the subset of items for "today".

        The dashboard returns today's set plus a few upcoming days, all of which
        are `isCompleted: false` until unlocked. Past days are never returned, so
        the smallest date present is today — using it avoids crediting (locked)
        future-day activities and sidesteps any client/server timezone mismatch.
        """
        keyed = [(self._date_key(it), it) for it in items]
        dated = [(k, it) for k, it in keyed if k is not None]
        if not dated:
            # No parseable dates — fall back to treating everything as today.
            return items
        today = min(k for k, _ in dated)

        # Some Daily Set cards don't carry a date in the payload (for example,
        # referral offers) but they still belong to today's set. Keep
        # undated items alongside the actual today's cards instead of dropping
        # them once any dated card is present.
        return [it for k, it in keyed if k is None or k == today]

    # -- Navigation helpers ----------------------------------------------------

    def _wait_ready(self, driver, timeout=15):
        """Wait until the new dashboard has streamed its data / rendered."""

        def _ready(d):
            try:
                return bool(
                    d.execute_script(
                        "return !!(window.__next_f || document.getElementById('dailyset'));"
                    )
                )
            except Exception:
                return False

        try:
            WebDriverWait(driver, timeout).until(_ready)
        except TimeoutException:
            pass

    def _wait_for(self, driver, selector, timeout=15):
        """Wait until `selector` matches an element. Returns True if it appeared."""

        def _ready(d):
            try:
                return bool(
                    d.execute_script(
                        "return !!document.querySelector(arguments[0]);", selector
                    )
                )
            except Exception:
                return False

        try:
            WebDriverWait(driver, timeout).until(_ready)
            return True
        except TimeoutException:
            return False

    # -- Top-level entry point -------------------------------------------------

    def perform(self, driver, human, stop_event=None):
        """
        Run the new-dashboard point-earning tasks: the Daily Set (/dashboard),
        claiming pending points, then the "earn-page" activities and the quests
        (/earn). Returns the Daily Set outcome (used to mark today done); the
        claim/earn/quest passes are best-effort.
        """
        daily_ok = self._run_daily_set(driver, human, stop_event=stop_event)
        if stop_event is not None and stop_event.is_set():
            return daily_ok
        try:
            self._run_claim(driver, human, stop_event=stop_event)
        except Exception as e:
            if not (stop_event is not None and stop_event.is_set()):
                self._log(f"[WARNING] Claim pass failed: {e}")
        if stop_event is not None and stop_event.is_set():
            return daily_ok
        try:
            self._run_more_activities(driver, human, stop_event=stop_event)
        except Exception as e:
            if not (stop_event is not None and stop_event.is_set()):
                self._log(f"[WARNING] 'earn-page' pass failed: {e}")
        if stop_event is not None and stop_event.is_set():
            return daily_ok
        try:
            self._run_quests(driver, human, stop_event=stop_event)
        except Exception as e:
            if not (stop_event is not None and stop_event.is_set()):
                self._log(f"[WARNING] Quest pass failed: {e}")
        return daily_ok

    def _run_claim(self, driver, human, stop_event=None):
        """
        Claim pending points from the dashboard "ready to claim" tile.

        New-dashboard points must be claimed before they count toward the balance
        (and they expire ~1 month after being earned). The tile shows a pending
        count with a danger dot; clicking it opens a flyout whose primary button
        claims them. Best-effort and language-independent — matched by the
        coins-icon asset, the danger-status token and the brand-button token,
        never by localized labels.
        """
        self._log("Checking for claimable points (new dashboard)")
        try:
            driver.get(DASHBOARD_URL)
            self._wait_ready(driver)
            time.sleep(random.uniform(1.5, 2.5))
        except Exception as e:
            self._log(f"[WARNING] Could not open the dashboard to claim: {e}")
            return

        # The claim tile: a clickable (non-link) card with the coins icon and a
        # danger-status dot (pending points). The balance tile also shows a coins
        # icon but is an <a href="/redeem"> with no danger dot, so it's excluded.
        card = None
        pending = ""
        try:
            icons = driver.find_elements(
                By.CSS_SELECTOR, 'img[src*="CoinsTransparent"]'
            )
        except Exception:
            icons = []
        for icon in icons:
            try:
                anc = icon.find_element(
                    By.XPATH,
                    "./ancestor::*[contains(@class,'cursor-pointer')][1]",
                )
                if anc.tag_name.lower() == "a":
                    continue
                if not anc.find_elements(By.CSS_SELECTOR, '[class*="statusDanger"]'):
                    continue
                card = anc
                try:
                    pending = anc.find_element(
                        By.CSS_SELECTOR, ".text-pageHeader"
                    ).text.strip()
                except Exception:
                    pending = ""
                break
            except Exception:
                continue

        if card is None:
            self._log("No claimable points.")
            return

        self._log(f"Opening claim flyout (pending: {pending or '?'} points).")
        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", card
            )
            time.sleep(random.uniform(0.4, 0.8))
            human.click_element(card, scroll_into_view=False)
        except Exception as e:
            if stop_event is not None and stop_event.is_set():
                return
            self._log(f"[WARNING] Could not open the claim flyout: {e}")
            return

        # Wait for the flyout, then click its primary (brand) button — not the
        # close (slot="close") or the "how it works" disclosure (slot="trigger").
        if not self._wait_for(driver, '[class*="bg-flyout"]', timeout=10):
            self._log("[WARNING] Claim flyout did not open.")
            return
        time.sleep(random.uniform(0.8, 1.4))
        try:
            flyout = driver.find_element(By.CSS_SELECTOR, '[class*="bg-flyout"]')
            btn = None
            for b in flyout.find_elements(
                By.CSS_SELECTOR, 'button[class*="bgCtrlBrandRest"]'
            ):
                if b.get_attribute("slot"):
                    continue
                if not b.is_enabled():
                    continue
                btn = b
                break
        except Exception as e:
            self._log(f"[WARNING] Could not find the claim button: {e}")
            return

        if btn is None:
            self._log("[WARNING] Claim button not found in the flyout.")
            return
        try:
            human.click_element(btn, scroll_into_view=True)
            time.sleep(random.uniform(1.5, 2.5))
            self.last_totals["attempted"] = self.last_totals.get("attempted", 0) + 1
            self._log("Clicked claim — pending points submitted.")
        except Exception as e:
            if stop_event is not None and stop_event.is_set():
                return
            self._log(f"[WARNING] Could not click the claim button: {e}")

    def _run_more_activities(self, driver, human, stop_event=None):
        """
        Click the incomplete point-earning cards in the /earn "earn-page"
        section (#moreactivities). Mirrors the legacy "More Activities" section.
        """
        self._log("Checking 'earn-page' activities (new dashboard)")
        try:
            driver.get(EARN_URL)
        except Exception as e:
            self._log(f"[WARNING] Could not open the earn page: {e}")
            return

        self._wait_for(driver, "#moreactivities", timeout=15)
        time.sleep(random.uniform(1.5, 2.5))
        self._expand_section(driver, "moreactivities")
        time.sleep(random.uniform(0.5, 1.0))

        try:
            items = driver.execute_script(_MORE_ACTIVITIES_JS)
        except Exception as e:
            self._log(f"[WARNING] Could not read 'earn-page' cards: {e}")
            return
        if not isinstance(items, list) or not items:
            self._log("'earn-page': nothing to do.")
            return

        self._log(f"'earn-page': {len(items)} activity(ies) to do.")
        main_tab = driver.current_window_handle
        done = 0
        for item in items:
            if stop_event is not None and stop_event.is_set():
                self._log("Stop requested — halting 'earn-page'.")
                break
            dest = item.get("destination")
            title = item.get("title") or "activity"
            if not isinstance(dest, str) or not dest.startswith("http"):
                continue
            self._log(f"Opening activity: {title} (+{item.get('points')})")
            anchor = self._locate_anchor(driver, dest, section_id="moreactivities")
            if anchor is not None and self._click_anchor(
                driver,
                human,
                anchor,
                main_tab,
                stop_event,
                return_url=EARN_URL,
                section_id="moreactivities",
            ):
                done += 1
                continue
            # Fallback: direct navigation (less likely to credit, but better than skip).
            self._log(f"[INFO] Falling back to direct navigation for '{title}'.")
            try:
                driver.get(dest)
                done += 1
                time.sleep(random.uniform(2, 4))
                try:
                    human.scroll_page()
                except Exception:
                    pass
                time.sleep(random.uniform(2, 4))
                driver.get(EARN_URL)
                self._wait_for(driver, "#moreactivities", timeout=10)
                time.sleep(random.uniform(1, 2))
                self._expand_section(driver, "moreactivities")
            except Exception as e:
                if stop_event is not None and stop_event.is_set():
                    break
                self._log(f"[WARNING] Failed to open '{title}': {e}")

        if done:
            # These opens aren't re-read/confirmed, so they count in their own
            # `earn` bucket (and as attempts); `newly` stays reserved for
            # verified daily-set completions.
            self.last_totals["earn"] = self.last_totals.get("earn", 0) + done
            self.last_totals["attempted"] = self.last_totals.get("attempted", 0) + done
        self._log(f"'earn-page': opened {done} activity(ies) this run.")

    def _run_quests(self, driver, human, stop_event=None):
        """
        Complete the currently-actionable tasks inside /earn "quest" punchcards.

        A quest is a multi-task card that links to its own /earn/quest/<id> page;
        each task is a Bing-search link that must be really clicked to credit
        (like a daily-set card). Punchcard tasks are time-gated — typically only
        one unlocks per ~24h — so a run completes only what's unlocked right now;
        locked tasks carry aria-disabled / data-disabled and are skipped. Full
        completion of a quest therefore takes several daily runs.
        """
        self._log("Checking 'earn-page' quests (new dashboard)")
        try:
            driver.get(EARN_URL)
            self._wait_ready(driver)
        except Exception as e:
            self._log(f"[WARNING] Could not open the earn page for quests: {e}")
            return

        # Quest cards sit in a collapsible panel and stream in progressively.
        # Expand every collapsed section, then poll discovery until the set of
        # quests stops growing so a late-rendered card isn't missed.
        self._expand_all(driver)
        quests = []
        for _ in range(6):
            time.sleep(random.uniform(0.8, 1.4))
            try:
                current = driver.execute_script(_QUESTS_JS) or []
            except Exception as e:
                self._log(f"[WARNING] Could not read quests: {e}")
                return
            if isinstance(current, list) and len(current) > len(quests):
                quests = current
            elif quests:
                break
        if not quests:
            self._log("Quests: none found.")
            return

        # Keep only quests that award points and aren't finished. Points-earning
        # quests carry a "+N" badge on their card; promo quests (partner offers,
        # e.g. Spotify/MasterClass) show none and are skipped, as are quests
        # already complete (progress N/N).
        pending = []
        for q in quests:
            if not isinstance(q, dict):
                continue
            url = q.get("url")
            if not isinstance(url, str) or "/earn/quest/" not in url:
                continue
            pts = q.get("points")
            if not isinstance(pts, int) or pts <= 0:
                continue
            d, t = q.get("done"), q.get("total")
            if isinstance(d, int) and isinstance(t, int) and t > 0 and d >= t:
                continue
            pending.append(q)

        if not pending:
            self._log("Quests: no points-earning quest to do.")
            return

        self._log(f"Quests: {len(pending)} points-earning quest(s) to check.")
        main_tab = driver.current_window_handle
        opened = 0
        for q in pending:
            if stop_event is not None and stop_event.is_set():
                self._log("Stop requested — halting quests.")
                break
            url = q["url"]
            title = q.get("title") or "quest"
            try:
                driver.get(url)
                self._wait_ready(driver)
            except Exception as e:
                self._log(f"[WARNING] Could not open quest '{title}': {e}")
                continue

            # The task list streams in after hydration; _wait_ready only gates on
            # the Next.js payload existing. Wait for a task heading to render
            # before reading, so a not-yet-loaded list isn't mistaken for
            # "nothing to do" (which would skip an unlocked task).
            if not self._wait_for(
                driver, '[class*="rewardsTableAltBg"] h3', timeout=15
            ):
                self._log(f"Quest '{title}': task list did not render — skipping.")
                continue
            time.sleep(random.uniform(1.0, 1.8))

            try:
                tasks = driver.execute_script(_QUEST_TASKS_JS)
            except Exception as e:
                self._log(f"[WARNING] Could not read tasks for quest '{title}': {e}")
                continue
            if not isinstance(tasks, list) or not tasks:
                self._log(
                    f"Quest '{title}': no actionable task right now "
                    "(locked or complete)."
                )
                continue

            self._log(f"Quest '{title}': {len(tasks)} actionable task(s).")
            for task in tasks:
                if stop_event is not None and stop_event.is_set():
                    break
                dest = task.get("destination")
                ttitle = task.get("title") or "task"
                if not isinstance(dest, str) or not dest.startswith("http"):
                    continue
                self._log(f"Opening quest task: {ttitle}")
                anchor = self._locate_quest_task(driver, dest)
                if anchor is not None and self._click_anchor(
                    driver, human, anchor, main_tab, stop_event, return_url=url
                ):
                    opened += 1
                    # Re-open the quest page so the next task's element can be
                    # relocated fresh (the DOM re-renders after each click).
                    try:
                        driver.get(url)
                        self._wait_ready(driver)
                        time.sleep(random.uniform(1, 2))
                    except Exception:
                        pass

        if opened:
            # Unverified opens count in their own `quests` bucket (and as
            # attempts); `newly` is reserved for verified completions.
            self.last_totals["quests"] = self.last_totals.get("quests", 0) + opened
            self.last_totals["attempted"] = (
                self.last_totals.get("attempted", 0) + opened
            )
        self._log(f"Quests: opened {opened} task(s) this run.")

    def _run_daily_set(self, driver, human, stop_event=None):
        """
        Open the new dashboard, visit each incomplete daily-set activity for
        today, then re-read to confirm progress.

        Args:
            driver: Selenium WebDriver instance.
            human: HumanBehavior instance (used for human-like dwell/scroll).
            stop_event (threading.Event, optional): When set, aborts cleanly.

        Returns:
            bool: True if it's reasonable to mark today as done, False if we made
                  no progress (so the next run can retry).
        """
        self._log("Performing daily Rewards tasks (new dashboard)")

        try:
            driver.get(DASHBOARD_URL)
            self._wait_ready(driver)
            # Brief settle so late RSC chunks finish streaming in.
            time.sleep(random.uniform(2, 3))

            # Primary: poll the embedded RSC JSON (streams in progressively). It
            # is authoritative — it carries the exact destination + isCompleted.
            # Cross-checked against the rendered #dailyset DOM by _choose_today:
            # the JSON is often drained post-hydration or partially streamed, so
            # the DOM decides which cards really are today's. A genuine failure
            # (neither source yields cards) is reported by the "No daily-set
            # activities found" warning below.
            json_today = self._todays_items(self._read_items_polling(driver))
            dom_today = self._todays_items(self._read_items_dom(driver))
            todays, source = self._choose_today(json_today, dom_today)
            if not todays:
                diag = self._diagnostics(driver)
                self._log(
                    "[WARNING] No daily-set activities found in the new dashboard — "
                    f"url={diag.get('url')!r} title={diag.get('title')!r} "
                    f"chunks={diag.get('chunks')} blobLen={diag.get('blobLen')} "
                    f"hasDailySetItems={diag.get('hasKey')} "
                    f"hasDailysetSection={diag.get('hasDailyset')}"
                )
                return False

            self._log(
                f"New dashboard daily set: read {len(todays)} item(s) via {source}."
            )

            incomplete = [it for it in todays if not it.get("isCompleted")]
            total = len(todays)
            already = total - len(incomplete)
            self.last_totals = {
                "already": already,
                "newly": 0,
                "final": already,
                "total": total,
                "attempted": 0,
                "earn": 0,
                "quests": 0,
            }
            self._log(f"New dashboard daily set: {already}/{total} already complete.")

            if not incomplete:
                return True

            # Clicking the card (which opens its search in a new tab from the
            # dashboard) is what credits the offer — a bare driver.get() to the
            # destination does not. Expand the section, then click each incomplete
            # card like a user would.
            main_tab = driver.current_window_handle
            self._expand_section(driver)

            attempted = 0
            for item in todays:
                if stop_event is not None and stop_event.is_set():
                    self._log("Stop requested — halting new-dashboard daily set.")
                    break
                if item.get("isCompleted"):
                    continue

                destination = item.get("destination")
                title = item.get("title") or item.get("offerId") or "activity"
                if not isinstance(destination, str) or not destination.startswith(
                    "http"
                ):
                    self._log(f"[WARNING] Skipping '{title}': no valid destination.")
                    continue

                self._log(f"Opening daily-set activity: {title}")
                anchor = self._locate_anchor(driver, destination)
                if anchor is not None and self._click_anchor(
                    driver, human, anchor, main_tab, stop_event
                ):
                    attempted += 1
                    continue

                # Last resort if the card can't be located/clicked: navigate
                # directly (often won't credit, but better than skipping).
                self._log(f"[INFO] Falling back to direct navigation for '{title}'.")
                try:
                    driver.get(destination)
                    attempted += 1
                    time.sleep(random.uniform(2, 4))
                    try:
                        human.scroll_page()
                    except Exception:
                        pass
                    time.sleep(random.uniform(2, 4))
                    driver.get(DASHBOARD_URL)
                    self._wait_ready(driver)
                    time.sleep(random.uniform(1, 2))
                    self._expand_section(driver)
                except Exception as e:
                    if stop_event is not None and stop_event.is_set():
                        break
                    self._log(f"[WARNING] Failed to open '{title}': {e}")

            if attempted == 0:
                self._log("[WARNING] No daily-set activities could be opened.")
                return False

            if stop_event is not None and stop_event.is_set():
                return False

            # Re-read the dashboard to measure how many activities actually
            # flipped to complete. window.__next_f is drained after hydration, so
            # the re-read relies on the same JSON-then-DOM strategy as the initial
            # read — reading JSON only here would always look "all done" (empty)
            # and falsely report success.
            newly = 0
            verified = False
            try:
                driver.get(DASHBOARD_URL)
                self._wait_ready(driver)
                time.sleep(random.uniform(1.5, 2.5))
                # The re-read can race a still-streaming (partial) snapshot; one
                # missing cards would make them look completed and inflate
                # `newly`. Only trust a snapshot that covers at least as many
                # cards as we started with — retry (JSON then DOM) until it does.
                after = []
                for _ in range(5):
                    # Same source arbitration as the initial read: a partial
                    # (or other-day) JSON snapshot must not beat the DOM, or
                    # missing cards would be counted as completed.
                    after, _src = self._choose_today(
                        self._todays_items(self._read_items(driver)),
                        self._todays_items(self._read_items_dom(driver)),
                    )
                    if len(after) >= len(todays):
                        break
                    time.sleep(1.5)
                if after and len(after) >= len(todays):
                    verified = True
                    still_incomplete = sum(
                        1 for it in after if not it.get("isCompleted")
                    )
                    newly = max(0, len(incomplete) - still_incomplete)
                else:
                    self._log(
                        "[INFO] Post-run snapshot incomplete "
                        f"({len(after)}/{len(todays)} cards) — not confirming "
                        "completion this run."
                    )
            except Exception:
                pass

            self.last_totals["attempted"] = attempted
            self.last_totals["newly"] = newly
            self.last_totals["final"] = already + newly

            if newly > 0:
                self._log(f"New dashboard daily set: +{newly} completed this run.")
                return True

            if verified:
                # We could re-read the cards and they are still incomplete: the
                # visits did not credit (common in headless — Rewards often won't
                # credit a headless session) or the items are quizzes needing
                # manual answers. Report honestly and don't mark today done, so a
                # later (visible) run can retry.
                self._log(
                    "[WARNING] Daily-set activities were opened but none are marked "
                    "complete on the dashboard. Not marking today done — if this is "
                    "a headless run, try again with the browser visible."
                )
            else:
                self._log(
                    "[WARNING] Could not re-read the dashboard to confirm daily-set "
                    "completion. Not marking today done."
                )
            return False

        except Exception as e:
            if stop_event is not None and stop_event.is_set():
                self._log("New-dashboard daily set halted by Stop.")
                return False
            self._log(f"[ERROR] New-dashboard daily set failed: {e}")
            return False
