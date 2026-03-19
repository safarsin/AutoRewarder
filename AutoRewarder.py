import os
import json
import random
import time
import webview
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, WebDriverException

# Configs 
# Create a separate folder for the bot's profile to avoid conflicts with your main browser
EDGE_PROFILE_PATH = os.path.join(
    os.environ['USERPROFILE'],
    'AppData', 
    'Local', 
    'SeleniumEdgeProfile'
)

JSON_FILE_PATH = "queries.json"

class AutoRewarderAPI:
    def __init__(self):
        self.webview_window = None
    
    def set_window(self, window):
        # store reference to webview window for JS to call
        self.webview_window = window
    
    def log(self, message):
        # send message to UI
        if self.webview_window:
            self.webview_window.evaluate_js(f"update_log('{message}')")

    def load_queries_from_json(self, filepath, num_needed):
        # load queries from JSON file and return a random sample
        try:
            with open(filepath, 'r', encoding='utf-8') as file:
                data = json.load(file)
                all_queries = data.get("queries", [])
                
                if len(all_queries) < num_needed:
                    self.log(f"[WARNING] In the JSON file, there are only {len(all_queries)} queries available, but {num_needed} are needed.")
                    return all_queries
                
                return random.sample(all_queries, num_needed)
            
        except FileNotFoundError:
            self.log(f"[ERROR] File {filepath} not found!")
            return []

    def human_typing(self, element, text):
        # Human-like typing with random delays between keystrokes
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.05, 0.18))

    def setup_driver(self):
        #Setup Microsoft Edge (driver will be downloaded automatically!)
        options = Options()
        options.add_argument(f"--user-data-dir={EDGE_PROFILE_PATH}")
        options.add_argument("--disable-blink-features=AutomationControlled") # Hide automation
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        
        # Automatic driver dowload and setup
        driver = webdriver.Edge(options=options)
        return driver

    def perform_searches(self, driver, queries):
        # Perform searches
        for i, query in enumerate(queries):
            try:
                driver.get("https://www.bing.com")
                time.sleep(random.uniform(4, 8))  # Random delay to mimic human behavior

                search_box = driver.find_element("name", "q")
                search_box.clear()

                self.log(f"Search #{i + 1}: {query}")

                self.human_typing(search_box, query)
                search_box.send_keys(Keys.RETURN)

                time.sleep(random.uniform(5, 10))
                
            except NoSuchElementException:
                self.log(f"[ERROR] Search box not found on attempt #{i+1}")
            except WebDriverException as e:
                self.log(f"[ERROR] WebDriver error on attempt #{i+1}: {e}")
            except Exception as e:
                self.log(f"[ERROR] Unknown error on attempt #{i+1}: {e}")

    def close_running_edge(self):
        # Close running Edge processes to avoid conflicts with the Selenium profile
        # os.system("taskkill /f /im msedge.exe >nul 2>&1")
        # os.system("taskkill /f /im msedgedriver.exe >nul 2>&1")
        # time.sleep(2)
        return

    def main(self, count):
        self.log("Starting AutoRewarder (Edge Edition)...")
        self.close_running_edge()
        
        # 1. Get queries to search from JSON file
        queries_to_search = self.load_queries_from_json(JSON_FILE_PATH, num_needed=count)
        
        if not queries_to_search:
            self.log("No queries available for search. Exiting.")
            return

        # 2. Setup browser
        self.driver = self.setup_driver()
        try:
            # 3. Perform searches
            self.perform_searches(self.driver, queries_to_search)
        finally:
            self.driver.quit()
            self.log("Done!")
            # Re-enable button after finish
            if self.webview_window:
                self.webview_window.evaluate_js("enable_start_button()")

if __name__ == "__main__":
    api = AutoRewarderAPI()
    window = webview.create_window(
        title= "AutoRewarder",
        url='GUI/index.html',
        js_api=api,
        width=570,
        height=494,
        resizable=False,
        #frameless=True
    )
    api.set_window(window)  # pass window reference to AutoRewarderAPI for logging
    webview.start(icon=None) # add an icon 