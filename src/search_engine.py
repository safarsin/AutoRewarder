import json
import random
import time
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By

from .utils import human_typing
from .human_behavior import HumanBehavior


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
        """

        human = HumanBehavior(driver, show_cursor=True, mobile=mobile)

        next_coffee_break = self.get_coffee_break_count()
        searches_since_break = 0

        self._log(f"Loaded {len(queries)} queries. Starting searches...")
        self._log(f"Next coffee break after {next_coffee_break} searches.")

        for i, query in enumerate(queries):
            if stop_event is not None and stop_event.is_set():
                self._log("Stop requested — halting search loop.")
                return

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
                            return
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
                    self._log(f"Chosen behavior: Switch to {chosen_tab['name']}")
                    try:
                        # Find the tab element using its id
                        xpath = f"//li[@id='{chosen_tab['id']}']//a"
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

                # Add to history.json
                self._add_to_history(query, "Success")

            except NoSuchElementException:
                if stop_event is not None and stop_event.is_set():
                    return
                self._log(f"[ERROR] Search box not found on attempt #{i+1}")
                self._add_to_history(query, "[ERROR] Search box not found")

            except WebDriverException as e:
                if stop_event is not None and stop_event.is_set():
                    return
                short_error = str(e).split("\n")[0][:28]
                self._log(f"[ERROR] WebDriver error on attempt #{i+1}: {short_error}")
                self._add_to_history(query, f"[ERROR] WebDriver Error: {short_error}")

            except Exception as e:
                if stop_event is not None and stop_event.is_set():
                    return
                self._log(f"[ERROR] Unknown error on attempt #{i+1}: {e}")
                self._add_to_history(query, f"[ERROR] Unknown Error: {str(e)[:50]}")
