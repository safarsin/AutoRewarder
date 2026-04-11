import json
import random
import time
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By

from .utils import human_typing
from .human_behavior import HumanBehavior

class SearchEngine:
    def __init__(self, logger=None, history=None):
        self._logger = logger
        self._history = history

    def log(self, message):
        if self._logger:
            self._logger(message)

    def add_to_history(self, query_text, status):
        if self._history:
            self._history.add_to_history(query_text, status)

    # Load queries from JSON file and return a random sample
    def load_queries_from_json(self, filepath, num_needed):
        try:
            with open(filepath, "r", encoding="utf-8") as file:
                data = json.load(file)
                all_queries = data.get("queries", [])

                if len(all_queries) < num_needed:
                    self.log(f"[WARNING] In the JSON file, there are only {len(all_queries)} queries available, but {num_needed} are needed.")
                    return all_queries

                return random.sample(all_queries, num_needed)

        except FileNotFoundError:
            self.log(f"[ERROR] File {filepath} not found!")
            self.add_to_history("N/A", f"[ERROR] File {filepath} not found")
            return []
        
    def get_coffee_break_count(self):
        # 80% of the time, take a break after 4-9 searches
        if random.random() < 0.8:
            return random.randint(4, 9)
        # 20% of the time, take a break after 10-15 searches
        else:
            return random.randint(10, 15)
        
    # Perform searches with human-like behavior and log results
    def perform_searches(self, driver, queries):

        human = HumanBehavior(driver, show_cursor=True)

        next_coffee_break = self.get_coffee_break_count()
        searches_since_break = 0

        self.log(f"Loaded {len(queries)} queries. Starting searches...")
        self.log(f"Next coffee break after {next_coffee_break} searches.")

        for i, query in enumerate(queries):
            try:
                # Open Bing homepage
                driver.get("https://www.bing.com")
                time.sleep(random.uniform(4, 8))  # Random delay to mimic human behavior

                searches_since_break += 1

                # Longer break every few searches to mimic human behavior
                if searches_since_break >= next_coffee_break:

                    if next_coffee_break > 9:
                        pause_duration = random.uniform(45, 90)
                        self.log(f"Taking a big coffee break...")
                    else:
                        pause_duration = random.uniform(15, 30)
                        self.log(f"Taking a quick coffee break...")
                    
                    self.log(f"Sleeping for {pause_duration:.2f} seconds to mimic a coffee break.")
                    time.sleep(pause_duration)

                    next_coffee_break = self.get_coffee_break_count()
                    searches_since_break = 0
                    self.log(f"Next coffee break after {next_coffee_break} searches.")

                # Find the search box, clear it
                search_box = driver.find_element(By.NAME, "q")
                search_box.clear()

                # Log the search query in log area
                self.log(f"Search #{i + 1}: {query}")

                # Type the query with human-like delays
                human_typing(search_box, query)
                search_box.send_keys(Keys.RETURN) # Press Enter to search

                # Wait for result to load
                time.sleep(random.uniform(2, 4))

                tabs_config = [
                    {"name": "All", "priority": 0, "id": None},
                    {"name": "Images", "priority": 10, "id": "b-scopeListItem-images"},
                    {"name": "Videos", "priority": 10, "id": "b-scopeListItem-video"},
                    {"name": "News", "priority": 10, "id": "b-scopeListItem-news"}
                ]

                weights = [tab["priority"] for tab in tabs_config]
                chosen_tab = random.choices(tabs_config, weights=weights, k=1)[0]

                if chosen_tab["name"] != "All":
                    self.log(f"Chosen behavior: Switch to {chosen_tab['name']}")
                    try:
                        # Find the tab element using its id
                        xpath = f"//li[@id='{chosen_tab['id']}']//a"
                        tab_element = driver.find_element(By.XPATH, xpath)

                        # Move mouse and click the tab
                        human.click_element(tab_element)
                        time.sleep(random.uniform(3, 6))

                    except NoSuchElementException:
                        self.log(f"[WARNING] Tab {chosen_tab['name']} not found. Staying on 'All'.")

                        # Fallback to "All" if the chosen tab is not found
                        chosen_tab["name"] = "All"

                    except WebDriverException as e:
                        short_error = str(e).split("\n")[0][:28]
                        self.log(f"[WARNING] WebDriver error when switching to {chosen_tab['name']}: {short_error}.")
                        self.log(f"Staying on 'All'.")

                        chosen_tab["name"] = "All"

                # Scroll the page to mimic human behavior
                try:
                    if chosen_tab["name"] == "All":
                        human.scroll_page()
                except WebDriverException as e:
                    short_error = str(e).split("\n")[0][:28]
                    self.log(f"[WARNING] WebDriver error when scrolling: {short_error}. Continuing.")
                
                # Pause after scrolling
                time.sleep(random.uniform(2, 4))

                # Add to history.json
                self.add_to_history(query, "Success")

            except NoSuchElementException:
                self.log(f"[ERROR] Search box not found on attempt #{i+1}")
                self.add_to_history(query, "[ERROR] Search box not found")

            except WebDriverException as e:
                short_error = str(e).split("\n")[0][:28]
                self.log(f"[ERROR] WebDriver error on attempt #{i+1}: {short_error}")
                self.add_to_history(query, f"[ERROR] WebDriver Error: {short_error}")

            except Exception as e:
                self.log(f"[ERROR] Unknown error on attempt #{i+1}: {e}")
                self.add_to_history(query, f"[ERROR] Unknown Error: {str(e)[:50]}")