"""Search automation helpers for Bing queries."""

import base64
import json
import os
import random
import time
from urllib.parse import urlparse
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By

from ..utils import human_typing
from ..emulator import HumanBehavior

# Rewards' "visual search streak" mission credits a search only when it starts
# from the mission's own link: the Bing homepage carrying its promo code. The
# dashboard handler reads that link off the payload each run; this is the
# fallback for when it can't (mission not offered, legacy dashboard, daily-set
# pass skipped).
REWARDS_VISUAL_SEARCH_URL = (
    "https://www.bing.com/?features=vsstreak,vstooltip&form=ML2XES"
)

# The Images vertical, and the surface the search actually runs on: Bing stamps
# a search started there with FORM=SBIIRP, and that is the only code the Rewards
# streak has been observed to credit. The homepage camera reports FORM=SBIHMP
# and went uncredited even though the search itself succeeded. Bing replaces the
# entry page's own form code either way, so the mission's promo code never
# reaches the search — only the surface does.
VISUAL_SEARCH_IMAGES_URL = "https://www.bing.com/images"

# Entry points for the "search by image" widget, tried in order. Images first
# for the reason above; it also renders the camera button server-side, while the
# homepage only injects it through a lazy fragment that some flights don't ship.
VISUAL_SEARCH_URLS = (
    VISUAL_SEARCH_IMAGES_URL,
    REWARDS_VISUAL_SEARCH_URL,
    "https://www.bing.com",
)

# Selectors for the camera button, from the most to the least specific.
VISUAL_SEARCH_BUTTON_LOCATORS = (
    (By.ID, "sb_sbi"),
    (By.CSS_SELECTOR, "#sbiarea [role='button']"),
    (By.ID, "sbi_b"),
)

# Hand the image to Bing the way a person does: dropped on the flyout, which
# advertises a drop target (data-drpanywhr / drop-eff-id) and handles it with
# its own code path. Writing the file straight into the hidden input skips that
# path entirely — the search still runs, but whatever the flyout reports to
# Rewards on a real drop never fires.
_DROP_IMAGE_JS = r"""
var b64 = arguments[0], name = arguments[1], target = arguments[2] || document.body;
var bin = atob(b64), bytes = new Uint8Array(bin.length);
for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
var file = new File([bytes], name, {type: 'image/jpeg'});
var dt = new DataTransfer();
dt.items.add(file);
['dragenter', 'dragover', 'drop'].forEach(function (type) {
  target.dispatchEvent(
    new DragEvent(type, {bubbles: true, cancelable: true, dataTransfer: dt})
  );
});
return dt.files.length;
"""

# State of the upload zone, sampled before and after a drop. An accepted drop
# flips the flyout into its loading state within half a second (and navigates
# about a second later), so any of these moving is proof the page took the file
# — including Bing answering with an error, which the file input wouldn't fix.
_UPLOAD_ZONE_STATE_JS = r"""
var pane = document.querySelector(arguments[0]);
var loading = document.querySelector('#loadingimg, .loadingdiv, .dpload');
return {
  url: location.href,
  pane: pane ? (pane.innerText || '').replace(/\s+/g, ' ').trim() : null,
  shown: pane ? !!pane.getClientRects().length : null,
  loading: loading ? !!loading.getClientRects().length : false
};
"""

# The upload flyout itself. #sb_fileinput sits in the DOM whether or not the
# flyout is open, and a file sent to it while it is closed goes nowhere, so this
# is what tells us the camera click actually landed.
VISUAL_SEARCH_PANEL_SELECTOR = "#sb_sbipane, [class*='sbipane']"

# Selectors for the hidden file input of the upload flyout.
VISUAL_SEARCH_INPUT_LOCATORS = (
    (By.ID, "sb_fileinput"),
    (By.CSS_SELECTOR, "input.fileinput[type='file']"),
    (By.CSS_SELECTOR, "input[type='file'][accept*='image']"),
)

# URL fragments Bing redirects to once an uploaded image has been searched.
# Depending on what the image matches, results land either on the image detail
# page (view=detailv2&iss=sbi...) or on a web SERP for the detected entity
# (/search?q=...&bcid=...&FORM=SBIIRP), hence several markers.
VISUAL_SEARCH_RESULT_URL_MARKERS = ("form=sbi", "iss=sbi", "bcid=", "view=detailv2")


class SearchEngine:
    """
    A class to handle search operations with human-like behavior.
    """

    def __init__(self, logger=None, history=None):
        """
        Initialize the SearchEngine with an optional logger and history manager.

        Args:
            logger (callable, optional): A logging function to log messages. Defaults to None.
            history (HistoryManager, optional): An instance of HistoryManager to manage search history. Defaults to None.
        """

        self._logger = logger
        self._history = history
        # Surface the last successful search ran on, so the caller can ask for
        # the other one when Rewards doesn't credit that one.
        self.last_search_url = None

    def _log(self, message):
        """
        Log a message using the provided logger, if available.

        Args:
            message (str): The message to log.
        """

        if self._logger:
            self._logger(message)

    def _add_to_history(self, query_text, status):
        """
        Add a search query and its status to the history manager.

        Args:
            query_text (str): The search query.
            status (str): The status of the search.
        """

        if self._history:
            self._history.add_to_history(query_text, status)

    def load_queries_from_json(self, filepath, num_needed):
        """
        Load search queries from a JSON file and return a random sample.

        Args:
            filepath (str): The path to the JSON file containing search queries.
            num_needed (int): The number of random queries to return.

        Returns:
            list: A list of randomly selected search queries.
            If the file is not found, an error is logged and an empty list is returned.
        """

        try:
            with open(filepath, "r", encoding="utf-8") as file:
                data = json.load(file)
                all_queries = data.get("queries", [])

                if len(all_queries) < num_needed:
                    self._log(
                        f"[WARNING] In the JSON file, there are only {len(all_queries)} queries available, but {num_needed} are needed."
                    )
                    return all_queries

                return random.sample(all_queries, num_needed)

        except FileNotFoundError:
            self._log(f"[ERROR] File {filepath} not found!")
            self._add_to_history("N/A", f"[ERROR] File {filepath} not found")
            return []

    def get_coffee_break_count(self):
        """
        Determine how many searches to perform before taking a coffee break, with a bias towards shorter breaks.

        Returns:
            int: The number of searches to perform before taking a break.
        """

        # 80% of the time, take a break after 4-9 searches
        if random.random() < 0.8:
            return random.randint(4, 9)
        # 20% of the time, take a break after 10-15 searches
        else:
            return random.randint(10, 15)

    def perform_searches(self, driver, queries, mobile=False, stop_event=None):
        """
        Perform searches on Bing using Selenium WebDriver with human-like behavior.

        Args:
            driver (WebDriver): An instance of Selenium WebDriver to control the browser.
            queries (list): A list of search queries to perform.
            mobile (bool): When True, HumanBehavior emits touch gestures instead
                of mouse events — pair with a mobile-emulated driver.
            stop_event (threading.Event, optional): If provided and set, the
                loop bails out at the next checkpoint and any in-progress
                coffee break is interrupted immediately.

        Returns:
            int: the number of searches that completed successfully (used by
                the stats layer to record activity for this run).
        """

        human = HumanBehavior(driver, show_cursor=True, mobile=mobile)

        next_coffee_break = self.get_coffee_break_count()
        searches_since_break = 0
        successful = 0

        self._log(f"Loaded {len(queries)} queries. Starting searches...")
        self._log(f"Next coffee break after {next_coffee_break} searches.")

        for i, query in enumerate(queries):
            if stop_event is not None and stop_event.is_set():
                self._log("Stop requested — halting search loop.")
                return successful

            try:
                # Open Bing homepage
                driver.get("https://www.bing.com")
                time.sleep(random.uniform(4, 8))  # Random delay to mimic human behavior

                searches_since_break += 1

                # Longer break every few searches to mimic human behavior
                if searches_since_break >= next_coffee_break:

                    if next_coffee_break > 9:
                        pause_duration = random.uniform(45, 90)
                        self._log("Taking a big coffee break...")
                    else:
                        pause_duration = random.uniform(15, 30)
                        self._log("Taking a quick coffee break...")

                    self._log(
                        f"Sleeping for {pause_duration:.2f} seconds to mimic a coffee break."
                    )
                    # Interruptible sleep: Event.wait returns True early if Stop is pressed.
                    if stop_event is not None:
                        if stop_event.wait(pause_duration):
                            self._log("Stop requested during coffee break — halting.")
                            return successful
                    else:
                        time.sleep(pause_duration)

                    next_coffee_break = self.get_coffee_break_count()
                    searches_since_break = 0
                    self._log(f"Next coffee break after {next_coffee_break} searches.")

                # Find the search box, clear it
                search_box = driver.find_element(By.NAME, "q")
                search_box.clear()

                # Log the search query in log area
                self._log(f"Search #{i + 1}: {query}")

                # Type the query with human-like delays
                human_typing(search_box, query)
                search_box.send_keys(Keys.RETURN)  # Press Enter to search

                # Wait for result to load
                time.sleep(random.uniform(2, 4))

                tabs_config = [
                    {"name": "All", "priority": 70, "id": None},
                    {"name": "Images", "priority": 10, "id": "b-scopeListItem-images"},
                    {"name": "Videos", "priority": 10, "id": "b-scopeListItem-video"},
                    {"name": "News", "priority": 10, "id": "b-scopeListItem-news"},
                ]

                weights = [tab["priority"] for tab in tabs_config]
                chosen_tab = random.choices(tabs_config, weights=weights, k=1)[0]

                if chosen_tab["name"] != "All":
                    main_tab = driver.current_window_handle
                    tab_element = None

                    # Check if news tab exists, if it doesn't choose Images or Videos
                    if chosen_tab["name"] == "News":
                        try:
                            xpath = f"//nav/ul/li[@id='{chosen_tab['id']}']/a"
                            tab_element = driver.find_element(By.XPATH, xpath)
                        except NoSuchElementException:
                            chosen_tab = random.choice(tabs_config[1:3])

                    self._log(f"Chosen behavior: Switch to {chosen_tab['name']}")
                    try:
                        # Find the tab element using its id
                        if not tab_element:
                            xpath = f"//nav/ul/li[@id='{chosen_tab['id']}']/a"
                            tab_element = driver.find_element(By.XPATH, xpath)

                        # Move mouse and click the tab
                        human.click_element(tab_element)

                        time.sleep(random.uniform(3, 6))

                    except NoSuchElementException:
                        self._log(
                            f"[WARNING] Tab {chosen_tab['name']} not found. Staying on 'All'."
                        )

                        # Fallback to "All" if the chosen tab is not found
                        chosen_tab["name"] = "All"

                    except WebDriverException as e:
                        short_error = str(e).split("\n")[0][:28]
                        self._log(
                            f"[WARNING] WebDriver error when switching to {chosen_tab['name']}: {short_error}."
                        )
                        self._log("Staying on 'All'.")

                        chosen_tab["name"] = "All"

                # Scroll the page to mimic human behavior
                try:
                    if chosen_tab["name"] == "All":
                        human.scroll_page()
                except WebDriverException as e:
                    short_error = str(e).split("\n")[0][:28]
                    self._log(
                        f"[WARNING] WebDriver error when scrolling: {short_error}. Continuing."
                    )

                # Pause after scrolling
                time.sleep(random.uniform(2, 4))

                # Close all tabs other than main
                if chosen_tab["name"] != "All":
                    new_tabs = [tab for tab in driver.window_handles if tab != main_tab]
                    for tab in new_tabs:
                        try:
                            driver.switch_to.window(tab)
                            hostname = (
                                (urlparse(driver.current_url).hostname or "")
                                .lower()
                                .rstrip(".")
                            )
                            if hostname != "bing.com" and not hostname.endswith(
                                ".bing.com"
                            ):
                                continue
                            driver.close()
                        except WebDriverException as e:
                            short_error = str(e).split("\n")[0][:28]
                            self._log(
                                f"[WARNING] WebDriver error when closing tab: {short_error}. Continuing."
                            )

                    if main_tab in driver.window_handles:
                        driver.switch_to.window(main_tab)

                # Add to history.json
                self._add_to_history(query, "Success")
                successful += 1

            except NoSuchElementException:
                if stop_event is not None and stop_event.is_set():
                    return successful
                self._log(f"[ERROR] Search box not found on attempt #{i+1}")
                self._add_to_history(query, "[ERROR] Search box not found")

            except WebDriverException as e:
                if stop_event is not None and stop_event.is_set():
                    return successful
                short_error = str(e).split("\n")[0][:28]
                self._log(f"[ERROR] WebDriver error on attempt #{i+1}: {short_error}")
                self._add_to_history(query, f"[ERROR] WebDriver Error: {short_error}")

            except Exception as e:
                if stop_event is not None and stop_event.is_set():
                    return successful
                self._log(f"[ERROR] Unknown error on attempt #{i+1}: {e}")
                self._add_to_history(query, f"[ERROR] Unknown Error: {str(e)[:50]}")

        return successful

    def _find_visual_search_element(
        self,
        driver,
        locators,
        timeout,
        poll_interval,
        require_displayed=False,
        stop_event=None,
    ):
        """
        Poll the page until one of the given locators matches an element.

        Bing renames the ids of its "search by image" widget from time to time,
        so every step tries a few known selectors instead of a single one.

        Args:
            driver (WebDriver): An instance of Selenium WebDriver to control the browser.
            locators (tuple): Tuples of (By, selector) to try, in order of preference.
            timeout (float): How long to keep polling, in seconds.
            poll_interval (float): Delay between two polling rounds, in seconds.
            require_displayed (bool): Whether the element must be visible and enabled.
                Hidden file inputs still accept send_keys, so this stays False for them.
            stop_event (threading.Event, optional): When set, polling gives up at
                once instead of running to the timeout.

        Returns:
            WebElement: The first matching element, or None if the timeout
                expired or Stop was requested.
        """

        deadline = time.monotonic() + timeout

        while True:
            if stop_event is not None and stop_event.is_set():
                return None

            for by, selector in locators:
                try:
                    element = driver.find_element(by, selector)

                    if require_displayed and not (
                        element.is_displayed() and element.is_enabled()
                    ):
                        continue

                    return element

                except WebDriverException:
                    continue

            if time.monotonic() >= deadline:
                return None

            time.sleep(poll_interval)

    def _attempt_visual_search(
        self, driver, human, url, image_path, poll_interval, stop_event=None
    ):
        """
        Run one full search-by-image attempt from a single entry page.

        Returns:
            str: "done" when the results were reached, "stopped" on Stop,
                "no widget" when the page never offered a usable camera button
                or upload field, and "no results" when the image was uploaded
                but nothing came back — the case worth retrying elsewhere.
        """
        if stop_event is not None and stop_event.is_set():
            return "stopped"

        driver.get(url)
        start_url = driver.current_url

        time.sleep(random.uniform(1, 4))

        button = self._find_visual_search_element(
            driver,
            VISUAL_SEARCH_BUTTON_LOCATORS,
            timeout=15,
            poll_interval=poll_interval,
            require_displayed=True,
            stop_event=stop_event,
        )

        if stop_event is not None and stop_event.is_set():
            return "stopped"

        if button is None:
            self._log(f"[INFO] No visual search button on {url}.")
            return "no widget"

        human.click_element(button)

        time.sleep(random.uniform(1, 3))

        if not self._open_upload_panel(
            driver, human, button, poll_interval, stop_event
        ):
            self._log(f"[INFO] Upload flyout stayed closed on {url}.")
            return "stopped" if self._stopped(stop_event) else "no widget"

        upload_input = self._find_visual_search_element(
            driver,
            VISUAL_SEARCH_INPUT_LOCATORS,
            timeout=15,
            poll_interval=poll_interval,
            stop_event=stop_event,
        )

        panel = self._find_visual_search_element(
            driver,
            ((By.CSS_SELECTOR, VISUAL_SEARCH_PANEL_SELECTOR),),
            timeout=0,
            poll_interval=poll_interval,
        )

        time.sleep(random.uniform(1, 4))

        known_tabs = self._tab_snapshot(driver)

        # Drop it on the flyout first; fall back to writing the path into the
        # hidden input, which works but skips the flyout's own drop handling.
        if not self._drop_image(driver, image_path, panel):
            if upload_input is None:
                self._log(f"[INFO] No way to hand over the image on {url}.")
                return "stopped" if self._stopped(stop_event) else "no widget"

            self._log("[INFO] Drop not accepted; using the file input instead.")
            upload_input.send_keys(image_path)

        if self._wait_for_visual_search_results(
            driver,
            start_url,
            timeout=45,
            poll_interval=poll_interval,
            stop_event=stop_event,
            known_tabs=known_tabs,
        ):
            self.last_search_url = url
            return "done"

        if self._stopped(stop_event):
            return "stopped"

        self._log(
            f"[INFO] Uploaded from {url} but no results came back "
            f"({self._page_state(driver)})."
        )
        return "no results"

    def _stopped(self, stop_event):
        """Whether Stop was requested."""
        return stop_event is not None and stop_event.is_set()

    def _drop_image(self, driver, image_path, target=None):
        """
        Drop the image on Bing's upload zone, as a drag-and-drop would.

        Args:
            driver (WebDriver): An instance of Selenium WebDriver to control the browser.
            image_path (str): Path of the image to hand over.
            target (WebElement, optional): Element to drop on. Defaults to the
                page body, which the flyout listens on (data-drpanywhr).

        Returns:
            bool: True when the drop was dispatched with the file attached.
        """
        try:
            with open(image_path, "rb") as image:
                payload = base64.b64encode(image.read()).decode("ascii")
        except OSError as e:
            self._log(f"[INFO] Could not read the image to drop it: {e}")
            return False

        before = self._upload_zone_state(driver)

        try:
            files = driver.execute_script(
                _DROP_IMAGE_JS, payload, os.path.basename(image_path), target
            )
        except WebDriverException as e:
            short_error = str(e).split("\n")[0][:40]
            self._log(f"[INFO] Drop upload failed ({short_error}).")
            return False

        if not files:
            return False

        # A DataTransfer carrying the file proves nothing about the page: a
        # build that ignores synthetic drag events leaves it just as full. So
        # wait for the zone to actually react, and let the caller fall back to
        # the file input when it doesn't.
        return self._drop_accepted(driver, before, timeout=5, poll_interval=0.25)

    def _upload_zone_state(self, driver):
        """Sample the upload zone's URL, flyout text and loading state."""
        try:
            state = driver.execute_script(
                _UPLOAD_ZONE_STATE_JS, VISUAL_SEARCH_PANEL_SELECTOR
            )
        except WebDriverException:
            return {}

        return state if isinstance(state, dict) else {}

    def _drop_accepted(self, driver, before, timeout, poll_interval, stop_event=None):
        """
        Whether the page reacted to the drop within `timeout` seconds.

        Returns:
            bool: True once the flyout starts loading, changes what it says,
                closes, or the page navigates. False if nothing moved.
        """
        deadline = time.monotonic() + timeout

        while True:
            if stop_event is not None and stop_event.is_set():
                return False

            after = self._upload_zone_state(driver)

            if after and (
                after.get("loading")
                or after.get("url") != before.get("url")
                or after.get("pane") != before.get("pane")
                or after.get("shown") != before.get("shown")
            ):
                return True

            if time.monotonic() >= deadline:
                return False

            time.sleep(poll_interval)

    def _open_upload_panel(self, driver, human, button, poll_interval, stop_event=None):
        """
        Make sure the camera click actually opened the upload flyout.

        A pointer click can land on an overlay (Bing shows a coach mark on the
        Rewards mission entry page) and the file input stays inert, which used
        to surface much later as an unexplained "no results" timeout. Retry the
        click through JS, which ignores whatever is on top, then with Escape
        first to dismiss it.

        Returns:
            bool: True when the flyout is open, or when this build of Bing has
                no flyout element at all (unknown markup — don't block on it).
                False when the flyout exists but stayed closed.
        """
        for attempt in range(3):
            if stop_event is not None and stop_event.is_set():
                return False

            try:
                panels = driver.find_elements(
                    By.CSS_SELECTOR, VISUAL_SEARCH_PANEL_SELECTOR
                )
            except WebDriverException:
                panels = []

            if not panels:
                self._log(
                    "[INFO] No upload flyout found on this page; uploading anyway."
                )
                return True

            if any(panel.is_displayed() for panel in panels):
                return True

            if attempt == 0:
                self._log("[INFO] Upload flyout didn't open. Clicking again.")
                try:
                    driver.execute_script("arguments[0].click();", button)
                except WebDriverException:
                    pass
            elif attempt == 1:
                try:
                    driver.switch_to.active_element.send_keys(Keys.ESCAPE)
                    human.click_element(button)
                except WebDriverException:
                    pass

            time.sleep(poll_interval + random.uniform(0.5, 1.5))

        return False

    def _tab_snapshot(self, driver):
        """Map each open tab to its current URL, to spot which one moves."""
        snapshot = {}

        try:
            origin = driver.current_window_handle
            handles = driver.window_handles
        except WebDriverException:
            return snapshot

        for handle in handles:
            try:
                driver.switch_to.window(handle)
                snapshot[handle] = self._current_url(driver)
            except WebDriverException:
                continue

        try:
            driver.switch_to.window(origin)
        except WebDriverException:
            pass

        return snapshot

    def _wait_for_visual_search_results(
        self,
        driver,
        start_url,
        timeout,
        poll_interval,
        stop_event=None,
        known_tabs=None,
    ):
        """
        Wait until the uploaded image actually lands on a visual search result page.

        Bing may render the results in the current tab or open them in a new
        one, so every window is checked and the driver is left on whichever one
        holds the results.

        Args:
            driver (WebDriver): An instance of Selenium WebDriver to control the browser.
            start_url (str): The URL the upload was started from.
            timeout (float): How long to keep polling, in seconds.
            poll_interval (float): Delay between two polling rounds, in seconds.
            stop_event (threading.Event, optional): When set, polling gives up at
                once instead of running to the timeout.
            known_tabs (dict, optional): Tab -> URL before the upload. A tab that
                was already open and hasn't moved since is not our result, even
                when its URL looks like one (a daily-set activity can leave an
                image page open); without this the search would report a success
                it didn't make, and skip the retry that would have made it.

        Returns:
            bool: True if the results page was reached, False if the timeout
                expired or Stop was requested.
        """

        deadline = time.monotonic() + timeout
        origin = None

        try:
            origin = driver.current_window_handle
        except WebDriverException:
            pass

        while True:
            if stop_event is not None and stop_event.is_set():
                return False

            if self._is_results_url(self._current_url(driver), start_url):
                return True

            # Results opened in another tab: adopt it and carry on there.
            try:
                handles = driver.window_handles
            except WebDriverException:
                handles = []

            for handle in handles:
                if handle == origin:
                    continue
                try:
                    driver.switch_to.window(handle)
                except WebDriverException:
                    continue
                url = self._current_url(driver)
                if known_tabs and url == known_tabs.get(handle):
                    continue
                if self._is_results_url(url, start_url):
                    self._log("Visual search results opened in a new tab.")
                    return True

            if origin is not None and handles:
                try:
                    driver.switch_to.window(origin)
                except WebDriverException:
                    pass

            if time.monotonic() >= deadline:
                return False

            time.sleep(poll_interval)

    def _current_url(self, driver):
        """Return the driver's current URL, or "" when it can't be read."""
        try:
            return driver.current_url or ""
        except WebDriverException:
            return ""

    def _is_results_url(self, url, start_url):
        """Whether `url` is a visual search result page and not the entry page."""
        return url != start_url and any(
            marker in url.lower() for marker in VISUAL_SEARCH_RESULT_URL_MARKERS
        )

    def _page_state(self, driver):
        """
        One-line snapshot of where the browser ended up, for failure logs.

        Reports the tab count, the page title and what the upload flyout itself
        is showing — an error Bing puts in the flyout ("we couldn't process this
        image") is the one thing that explains an upload going nowhere.
        """
        try:
            tabs = len(driver.window_handles)
        except WebDriverException:
            tabs = "?"

        try:
            title = (driver.title or "")[:60]
        except WebDriverException:
            title = "?"

        try:
            panel = driver.execute_script(
                "var p = document.querySelector(arguments[0]);"
                "return p ? (p.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120)"
                " : null;",
                VISUAL_SEARCH_PANEL_SELECTOR,
            )
        except WebDriverException:
            panel = "?"

        return f"tabs={tabs}, title={title!r}, flyout says {panel!r}"

    def _search_surface(self, driver):
        """Return the FORM code of the current page, or its path as a fallback."""
        try:
            current_url = driver.current_url or ""
        except WebDriverException:
            return "URL unknown"

        for part in current_url.split("?", 1)[-1].split("&"):
            if part.upper().startswith("FORM="):
                return part
        return urlparse(current_url).path or "no FORM code"

    def _log_visual_search_failure(self, driver, step, error=None, stop_event=None):
        """
        Log a visual search failure with the step that broke, for debugging.

        Selenium timeouts carry an empty message and a raw msedgedriver
        stacktrace, so the step name and the current URL are what make the
        failure readable in the logs.

        Args:
            driver (WebDriver): An instance of Selenium WebDriver to control the browser.
            step (str): A short description of the step that failed.
            error (Exception, optional): The exception that was raised, if any.
            stop_event (threading.Event, optional): When set, the step didn't
                fail — it was cancelled — so say that instead.

        Returns:
            bool: Always False, so callers can `return self._log_visual_search_failure(...)`.
        """

        if stop_event is not None and stop_event.is_set():
            self._log("Visual search stopped because Stop was requested.")
            return False

        try:
            current_url = driver.current_url
        except WebDriverException:
            current_url = "unknown"

        if error is None:
            reason = "timed out"
        else:
            short_error = str(error).split("\n")[0][:80].strip()
            reason = (
                f"{type(error).__name__}: {short_error}"
                if short_error
                else type(error).__name__
            )

        self._log(
            f"[ERROR] Visual search failed while {step} ({reason}). URL: {current_url}"
        )

        return False

    def other_surface_url(self):
        """
        The surface to try when Rewards ignored the search we just made.

        Which surface credits the streak is Microsoft's call and has changed
        before, so the caller retries on the other one rather than trusting
        our own ordering.

        Returns:
            str: The other surface's URL, or None if the last search's surface
                isn't known.
        """
        if not self.last_search_url:
            return None

        if self.last_search_url == VISUAL_SEARCH_IMAGES_URL:
            return REWARDS_VISUAL_SEARCH_URL

        return VISUAL_SEARCH_IMAGES_URL

    def perform_visual_search(
        self, driver, image_path, stop_event=None, entry_url=None, search_url=None
    ):
        """
        Perform a visual search on Bing using an image file.

        Args:
            driver (WebDriver): An instance of Selenium WebDriver to control the browser.
            image_path (str): The path to the image file to use for the visual search.
            stop_event (threading.Event, optional): If provided and set, the search will be cancelled.
            entry_url (str, optional): The Rewards mission link read off the
                dashboard, opened once before searching. Falls back to the
                known mission URL.
            search_url (str, optional): Surface to run the search on, tried
                before the defaults. Used to retry on the other surface when
                Rewards didn't credit the first one.

        Returns:
            bool: True if the visual search was successful, False otherwise.
        """
        from ..config import APP_DIR

        # In --onefile environments, aggressive polling overloads msedgedriver
        # and causes a GetHandleVerifier crash, so portable builds look for
        # elements at a slower pace.
        portable_mode = "config" in APP_DIR
        poll_interval = 1.5 if portable_mode else 0.5

        if stop_event is not None and stop_event.is_set():
            self._log("Skipping visual search because Stop was requested.")
            return False

        human = HumanBehavior(driver, show_cursor=True, mobile=False)
        step = "opening Bing"

        mission_url = entry_url or REWARDS_VISUAL_SEARCH_URL

        entry_urls = list(VISUAL_SEARCH_URLS)
        if mission_url not in entry_urls:
            entry_urls.insert(1, mission_url)
        if search_url:
            if search_url in entry_urls:
                entry_urls.remove(search_url)
            entry_urls.insert(0, search_url)

        try:
            # Open the mission's own link once before searching, the way the
            # dashboard's "Search now" button does. Every search that has
            # credited the streak so far happened after this visit, so it stays
            # — it costs one page load and the search itself runs on Images.
            try:
                driver.get(mission_url)
                time.sleep(random.uniform(1, 3))
            except WebDriverException as e:
                short_error = str(e).split("\n")[0][:28]
                self._log(
                    f"[INFO] Could not open the mission link ({short_error}). Continuing."
                )

            outcome = "no widget"

            for url in entry_urls:
                outcome = self._attempt_visual_search(
                    driver, human, url, image_path, poll_interval, stop_event
                )

                if outcome in ("done", "stopped"):
                    break

                if outcome == "no results":
                    # The upload went nowhere on this surface. The homepage and
                    # the mission link share one uploader, so the only retry
                    # worth the time is the other surface: Images.
                    alternate = (
                        mission_url
                        if url == VISUAL_SEARCH_IMAGES_URL
                        else VISUAL_SEARCH_IMAGES_URL
                    )
                    if url != alternate:
                        self._log(f"Retrying the visual search from {alternate}.")
                        outcome = self._attempt_visual_search(
                            driver,
                            human,
                            alternate,
                            image_path,
                            poll_interval,
                            stop_event,
                        )
                    break

            if outcome == "stopped":
                self._log("Visual search stopped because Stop was requested.")
                return False

            if outcome != "done":
                step = (
                    "waiting for the visual search results"
                    if outcome == "no results"
                    else "reaching Bing's image upload flyout"
                )
                return self._log_visual_search_failure(
                    driver, step, stop_event=stop_event
                )

            time.sleep(random.uniform(4, 8))

            try:
                human.scroll_page()
            except WebDriverException as e:
                short_error = str(e).split("\n")[0][:28]
                self._log(
                    f"[WARNING] WebDriver error when scrolling visual search results: {short_error}. Continuing."
                )

            if stop_event is not None and stop_event.is_set():
                self._log("Visual search stopped because Stop was requested.")
                return False

            # Log where the search landed: Bing's FORM code identifies the
            # surface that credited it (SBIHMP from the homepage, SBIIRP from
            # the Images vertical, a promo code when started from a Rewards
            # offer link), which is the first thing to check when the search
            # runs but the Rewards task stays uncredited.
            self._log(
                f"Visual search completed successfully ({self._search_surface(driver)})."
            )
            return True

        except Exception as e:
            return self._log_visual_search_failure(
                driver, step, e, stop_event=stop_event
            )

    def get_next_image_id(self, used_images_list):
        """
        Selects the next available image ID that hasn't been used recently.
        If all images have been used, resets the cycle.

        Args:
            used_images_list (list): A list of image IDs that have been used recently.

        Returns:
            tuple: A tuple with the selected image ID and the updated list of used images.
        """
        all_images = set(range(1, 31))
        used_images = set(used_images_list)

        available_images = list(all_images - used_images)

        if not available_images:
            self._log("[INFO] All images have been used. Resetting the cycle.")
            available_images = list(all_images)
            used_images_list = []

        selected_image = random.choice(available_images)
        used_images_list.append(selected_image)

        return selected_image, used_images_list

    def prepare_unique_image(self, image_id):
        """
        Prepares a unique version of the image to bypass hash-based detection.
        Crops 1-5 pixels and randomizes JPEG compression quality.

        Args:
            image_id (int): The ID of the image to prepare.

        Returns:
            str: The path to the prepared image, or None if preparation failed.
        """
        import os
        import secrets
        import tempfile

        from PIL import Image

        from ..config import VISUAL_SEARCH_ASSETS_DIR

        original_path = os.path.join(
            VISUAL_SEARCH_ASSETS_DIR,
            f"{image_id}.jpg",
        )

        if not os.path.exists(original_path):
            self._log(f"[ERROR] Source image not found: {original_path}")
            return None

        temp_path = None
        file_descriptor = None

        try:
            with Image.open(original_path) as img:
                width, height = img.size

                # 54 684 unique variations
                crop_left = random.randint(0, 5)
                crop_top = random.randint(0, 5)
                crop_right = random.randint(1, 7)
                crop_bottom = random.randint(1, 7)

                cropped_img = img.crop(
                    (crop_left, crop_top, width - crop_right, height - crop_bottom)
                )

                random_quality = random.randint(65, 95)

                # A plain random name: the temp file's name travels with the
                # upload, and there is no reason for this app's name to end up
                # in it. O_EXCL keeps the creation race-free, as mkstemp did.
                temp_path = os.path.join(
                    tempfile.gettempdir(), f"{secrets.token_hex(16)}.jpg"
                )
                file_descriptor = os.open(
                    temp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )

                with os.fdopen(file_descriptor, "wb") as temp_file:
                    file_descriptor = None

                    cropped_img.save(temp_file, format="JPEG", quality=random_quality)

            return temp_path

        except Exception as e:
            if file_descriptor is not None:
                os.close(file_descriptor)

            if temp_path is not None:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

            self._log(f"[ERROR] Failed to process image {image_id}: {e}")
            return None
