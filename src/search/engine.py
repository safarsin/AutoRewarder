"""Search automation helpers for Bing queries."""

import json
import random
import time
from urllib.parse import urlparse
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By

from ..utils import human_typing
from ..emulator import HumanBehavior

SEARCH_METHODS = ("homepage", "address_bar")


def choose_search_method(rng=random.choice):
    return rng(SEARCH_METHODS)


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
        # Sampled once per account session so daily click/tab ratios drift
        # instead of being drawn fresh (and identically distributed) per query.
        self._session_behavior = None

    def _session_behavior_weights(self):
        """Return this session's result-click chance and tab weights."""
        if self._session_behavior is None:
            all_priority = random.uniform(55, 75)
            images = random.uniform(8, 18)
            videos = random.uniform(5, 15)
            news = max(5.0, min(12.0, 100.0 - all_priority - images - videos))
            self._session_behavior = {
                "result_click_chance": random.uniform(0.55, 0.75),
                "tabs": [
                    {"name": "All", "priority": all_priority, "id": None},
                    {
                        "name": "Images",
                        "priority": images,
                        "id": "b-scopeListItem-images",
                    },
                    {
                        "name": "Videos",
                        "priority": videos,
                        "id": "b-scopeListItem-video",
                    },
                    {"name": "News", "priority": news, "id": "b-scopeListItem-news"},
                ],
            }
        return self._session_behavior

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

    def _dump_debug(self, driver, tag):
        """
        Save the current page source and a screenshot for debugging missing elements.

        Non-fatal: any failure is logged and ignored so search flow continues.
        """

        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            html_path = f"/tmp/bing_debug_{tag}_{timestamp}.html"
            with open(html_path, "w", encoding="utf-8") as file:
                file.write(driver.page_source)
            try:
                screenshot_path = f"/tmp/bing_debug_{tag}_{timestamp}.png"
                driver.save_screenshot(screenshot_path)
            except WebDriverException:
                pass
        except Exception:
            pass

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

    def _click_random_result(self, driver, human, stop_event=None):
        """
        Click a random organic result link and briefly browse the page.

        Picks one organic link from the 'All' results page, clicks it with
        human-like gestures, dwells on the destination for a randomized period
        (interruptible via stop_event), scrolls a bit, then returns to the
        results page — closing any new tab the link opened, otherwise using
        browser back. If a click does not navigate (a dead link or an
        anti-bot interstitial), one retry on another link runs; if that also
        fails, the session falls back to scrolling the SERP instead of
        emitting repeated dead clicks.

        Args:
            driver (WebDriver): An instance of Selenium WebDriver.
            human (HumanBehavior): Human-behavior emulator for clicks and scrolls.
            stop_event (threading.Event, optional): When set, bails out early.
        """

        main_tab = driver.current_window_handle

        try:
            links = driver.find_elements(
                By.CSS_SELECTOR, "li.b_algo h2 a, #b_results h2 a"
            )
            if not links:
                self._log("[WARNING] No organic result links found — skipping click.")
                self._dump_debug(driver, "no_organic")
                return

            navigated = False
            for attempt in (1, 2):
                if not links:
                    break
                link = random.choice(links)
                self._log("Chosen behavior: Click result link")
                results_url = driver.current_url
                human.click_element(link)

                # Wait for navigation away from the results page (up to ~10s).
                for _ in range(20):
                    if stop_event is not None and stop_event.is_set():
                        return
                    time.sleep(0.5)
                    if (
                        driver.current_url != results_url
                        or len(driver.window_handles) > 1
                    ):
                        navigated = True
                        break
                if navigated:
                    break
                self._log("[WARNING] Result click did not navigate — retrying.")
                links = driver.find_elements(
                    By.CSS_SELECTOR, "li.b_algo h2 a, #b_results h2 a"
                )

            if not navigated:
                # Fall back to an engaged SERP dwell so the session does not
                # produce a stream of dead clicks with no pageview.
                self._log(
                    "[WARNING] Result clicks did not navigate — SERP dwell fallback."
                )
                self._dump_debug(driver, "click_no_nav")
                try:
                    human.scroll_page()
                except WebDriverException:
                    pass
                if stop_event is not None:
                    if stop_event.wait(random.uniform(8, 25)):
                        return
                else:
                    time.sleep(random.uniform(8, 25))
                return

            # Browse the destination page for a randomized period.
            if stop_event is not None:
                if stop_event.wait(random.uniform(8, 35)):
                    return
            else:
                time.sleep(random.uniform(8, 35))

            try:
                human.scroll_page()
            except WebDriverException as e:
                short_error = str(e).split("\n")[0][:28]
                self._log(
                    f"[WARNING] WebDriver error when scrolling result page: {short_error}. Continuing."
                )

            # Return to the results page: close any new tab, else go back.
            if len(driver.window_handles) > 1:
                for tab in driver.window_handles:
                    if tab == main_tab:
                        continue
                    try:
                        driver.switch_to.window(tab)
                        driver.close()
                    except WebDriverException as e:
                        short_error = str(e).split("\n")[0][:28]
                        self._log(
                            f"[WARNING] WebDriver error when closing result tab: {short_error}. Continuing."
                        )
                if main_tab in driver.window_handles:
                    driver.switch_to.window(main_tab)
            else:
                try:
                    driver.back()
                except WebDriverException as e:
                    short_error = str(e).split("\n")[0][:28]
                    self._log(
                        f"[WARNING] WebDriver error when going back: {short_error}. Continuing."
                    )

            time.sleep(random.uniform(3, 8))

        except WebDriverException as e:
            short_error = str(e).split("\n")[0][:28]
            self._log(
                f"[WARNING] WebDriver error when clicking result link: {short_error}. Continuing."
            )

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
                search_method = choose_search_method()

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

                # Log the search query in log area
                self._log(f"Search #{i + 1}: {query} ({search_method})")

                if search_method == "address_bar":
                    ActionChains(driver).key_down(Keys.CONTROL).send_keys("l").key_up(
                        Keys.CONTROL
                    ).perform()
                    time.sleep(random.uniform(0.2, 0.8))
                    for char in query:
                        ActionChains(driver).send_keys(char).perform()
                        time.sleep(random.uniform(0.05, 0.18))
                    ActionChains(driver).send_keys(Keys.RETURN).perform()
                else:
                    # Open Bing homepage
                    driver.get("https://www.bing.com")
                    # Longer, human-paced delay before the first interaction.
                    time.sleep(random.uniform(6, 20))

                    # Find the search box, clear it
                    search_box = driver.find_element(By.NAME, "q")
                    search_box.clear()

                    # Type the query with human-like delays
                    human_typing(search_box, query)
                    search_box.send_keys(Keys.RETURN)  # Press Enter to search

                # Wait for result to load
                time.sleep(random.uniform(2, 4))

                session = self._session_behavior_weights()
                tabs_config = session["tabs"]
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
                        self._dump_debug(
                            driver, f"tab_missing_{chosen_tab['name'].lower()}"
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
                time.sleep(random.uniform(3, 8))

                # Occasionally click a result link and browse it briefly
                if (
                    chosen_tab["name"] == "All"
                    and random.random()
                    < self._session_behavior_weights()["result_click_chance"]
                ):
                    self._click_random_result(driver, human, stop_event)

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
