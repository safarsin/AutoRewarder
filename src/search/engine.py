"""Search automation helpers for Bing queries."""

import json
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

# Entry points for the "search by image" widget, tried in order. The homepage
# only injects the camera button through a lazy fragment, and some flights ship
# no fragment at all, while the Images vertical always renders it server-side.
VISUAL_SEARCH_URLS = (
    REWARDS_VISUAL_SEARCH_URL,
    "https://www.bing.com",
    "https://www.bing.com/images",
)

# Selectors for the camera button, from the most to the least specific.
VISUAL_SEARCH_BUTTON_LOCATORS = (
    (By.ID, "sb_sbi"),
    (By.CSS_SELECTOR, "#sbiarea [role='button']"),
    (By.ID, "sbi_b"),
)

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
        self, driver, locators, timeout, poll_interval, require_displayed=False
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

        Returns:
            WebElement: The first matching element, or None if the timeout expired.
        """

        deadline = time.monotonic() + timeout

        while True:
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

    def _wait_for_visual_search_results(
        self, driver, start_url, timeout, poll_interval
    ):
        """
        Wait until the uploaded image actually lands on a visual search result page.

        Args:
            driver (WebDriver): An instance of Selenium WebDriver to control the browser.
            start_url (str): The URL the upload was started from.
            timeout (float): How long to keep polling, in seconds.
            poll_interval (float): Delay between two polling rounds, in seconds.

        Returns:
            bool: True if the results page was reached, False if the timeout expired.
        """

        deadline = time.monotonic() + timeout

        while True:
            try:
                current_url = driver.current_url or ""
            except WebDriverException:
                current_url = ""

            if current_url != start_url and any(
                marker in current_url.lower()
                for marker in VISUAL_SEARCH_RESULT_URL_MARKERS
            ):
                return True

            if time.monotonic() >= deadline:
                return False

            time.sleep(poll_interval)

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

    def _log_visual_search_failure(self, driver, step, error=None):
        """
        Log a visual search failure with the step that broke, for debugging.

        Selenium timeouts carry an empty message and a raw msedgedriver
        stacktrace, so the step name and the current URL are what make the
        failure readable in the logs.

        Args:
            driver (WebDriver): An instance of Selenium WebDriver to control the browser.
            step (str): A short description of the step that failed.
            error (Exception, optional): The exception that was raised, if any.

        Returns:
            bool: Always False, so callers can `return self._log_visual_search_failure(...)`.
        """

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

    def perform_visual_search(
        self, driver, image_path, stop_event=None, entry_url=None
    ):
        """
        Perform a visual search on Bing using an image file.

        Args:
            driver (WebDriver): An instance of Selenium WebDriver to control the browser.
            image_path (str): The path to the image file to use for the visual search.
            stop_event (threading.Event, optional): If provided and set, the search will be cancelled.
            entry_url (str, optional): Page to start from, tried before the
                defaults. Used for the Rewards mission link read off the
                dashboard, which is what makes the search credit the streak.

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
        start_url = ""
        visual_search_button = None

        entry_urls = list(VISUAL_SEARCH_URLS)
        if entry_url and entry_url not in entry_urls:
            entry_urls.insert(0, entry_url)

        try:
            for url in entry_urls:
                if stop_event is not None and stop_event.is_set():
                    self._log("Visual search stopped because Stop was requested.")
                    return False

                driver.get(url)
                start_url = driver.current_url

                time.sleep(random.uniform(1, 4))

                step = f"looking for the visual search button on {url}"
                visual_search_button = self._find_visual_search_element(
                    driver,
                    VISUAL_SEARCH_BUTTON_LOCATORS,
                    timeout=15,
                    poll_interval=poll_interval,
                    require_displayed=True,
                )

                if visual_search_button is not None:
                    break

                self._log(
                    f"[WARNING] No visual search button on {url}. Trying another entry point."
                )

            if visual_search_button is None:
                return self._log_visual_search_failure(
                    driver, "looking for the visual search button"
                )

            human.click_element(visual_search_button)

            time.sleep(random.uniform(1, 3))

            step = "looking for the image upload field"
            upload_input = self._find_visual_search_element(
                driver,
                VISUAL_SEARCH_INPUT_LOCATORS,
                timeout=15,
                poll_interval=poll_interval,
            )

            if upload_input is None:
                return self._log_visual_search_failure(driver, step)

            time.sleep(random.uniform(1, 4))

            # Send the file path to the hidden type="file" input element
            step = "uploading the image"
            upload_input.send_keys(image_path)

            # Wait until the visual search results page is actually rendered
            step = "waiting for the visual search results"
            if not self._wait_for_visual_search_results(
                driver,
                start_url,
                timeout=30,
                poll_interval=poll_interval,
            ):
                return self._log_visual_search_failure(driver, step)

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
            return self._log_visual_search_failure(driver, step, e)

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

                file_descriptor, temp_path = tempfile.mkstemp(
                    prefix="AutoRewarder_visual_search_",
                    suffix=".jpg",
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
