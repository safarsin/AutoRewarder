import json
import random
import time
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, WebDriverException

from .utils import human_typing

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
        
    # Perform searches with human-like behavior and log results
    def perform_searches(self, driver, queries):
        for i, query in enumerate(queries):
            try:
                # Open Bing homepage
                driver.get("https://www.bing.com")
                time.sleep(random.uniform(4, 8))  # Random delay to mimic human behavior

                # Longer break every 5 searches to mimic human behavior and avoid detection
                if i % 5 == 0 and i != 0:
                    self.log("Taking a short break to mimic human behavior...")
                    time.sleep(random.uniform(15, 25))

                # Find the search box, clear it
                search_box = driver.find_element("name", "q")
                search_box.clear()

                # Log the search query in log area
                self.log(f"Search #{i + 1}: {query}")

                # Type the query with human-like delays
                human_typing(search_box, query)
                search_box.send_keys(Keys.RETURN) # Press Enter to search

                # Wait for result to load
                time.sleep(random.uniform(2, 4))

                # Generate random scroll divisor with probability
                # 70% of the time: scroll small portion (2-10 = 10% to 50%)
                # 30% of the time: scroll to end or near end (1-1.5 = 67% to 100%)
                # Based on studies showing users typically scroll 10-30% of a page
                if random.random() < 0.7:
                    random_scroll_divisor = random.uniform(2, 10)
                else:
                    random_scroll_divisor = random.uniform(1, 1.5)

                # JS script for smooth scroll down to mimic human behavior
                smooth_scroll_script = f"""
                    let currentScroll = 0;
                    let maxScroll = document.body.scrollHeight / {random_scroll_divisor};
                    let step = 40;

                    let scrollInterval = setInterval(() => {{
                        window.scrollBy(0, step);
                        currentScroll += step;

                        if (currentScroll >= maxScroll) {{
                            clearInterval(scrollInterval);
                        }}
                    }}, 50);
                """

                # Execute the smooth scroll script
                driver.execute_script(smooth_scroll_script)

                # Wait a bit after scrolling
                time.sleep(random.uniform(5, 10))

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