import os
import json
import random
import time
import webview
from datetime import datetime
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
        self.history_file = "history.json"
        # store reference to webview window so Python can call JS (evaluate_js)
        self.webview_window = window

    def open_history_window(self):
        # open a new window to show search history
        webview.create_window(
            title="Query History",
            url='GUI/history.html',
            js_api=self,
            width=700,
            height=500,
            resizable=True,
            background_color='#0d1117',
            text_select=True
        )

    # Load search history from JSON file
    def get_history(self):
        if not os.path.exists(self.history_file):
            return []
        
        with open(self.history_file, 'r', encoding='utf-8') as file:
            return json.load(file)
    
    # Add a search query to history JSON file
    def add_to_history(self, query_text, status):
        now = datetime.now()
        current_date = now.strftime("%m-%d-%Y")
        current_time = now.strftime("%H:%M:%S")

        # Create a new record with date, time, query, and status
        new_record = {
            "date": current_date,
            "time": current_time,
            "query": query_text, 
            "status": status
        }

        history_list = self.get_history()
        
        history_list.append(new_record)

        with open(self.history_file, 'w', encoding='utf-8') as file:
            json.dump(history_list, file, ensure_ascii=False, indent=4)

    def log(self, message):
        # send message to UI
        if self.webview_window:
            try:
                safe_message = json.dumps(message)
                self.webview_window.evaluate_js(f"update_log({safe_message})")
            except Exception as e:
                print(f"Log error: {e}")

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
            self.add_to_history("N/A", f"[ERROR] File {filepath} not found")
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
        options.add_argument("--no-default-browser-check")  # Don't check if Edge is default
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

                if i % 5 == 0 and i != 0: 
                    self.log("Taking a short break to mimic human behavior...")
                    time.sleep(random.uniform(15, 25))  # Longer break every 5 searches

                search_box = driver.find_element("name", "q")
                search_box.clear()

                self.log(f"Search #{i + 1}: {query}")

                self.human_typing(search_box, query)
                search_box.send_keys(Keys.RETURN)

                time.sleep(random.uniform(2, 4))

                # Smooth scroll down to mimic human behavior
                smooth_scroll_script = """
                    let currentScroll = 0;
                    let maxScroll = document.body.scrollHeight / 2;
                    let step = 40;
                    
                    let scrollInterval = setInterval(() => {
                        window.scrollBy(0, step);
                        currentScroll += step;
                        
                        if (currentScroll >= maxScroll) {
                            clearInterval(scrollInterval);
                        }
                    }, 50);
                """

                driver.execute_script(smooth_scroll_script)

                time.sleep(random.uniform(5, 10))

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

    def close_running_edge(self):
        # Close running Edge processes to avoid conflicts with the Selenium profile
        # os.system("taskkill /f /im msedge.exe >nul 2>&1")
        # os.system("taskkill /f /im msedgedriver.exe >nul 2>&1")
        # time.sleep(2)
        return

    def main(self, count):
        self.log("Starting AutoRewarder (Edge Edition)...")
        
        # 1. Get queries to search from JSON file
        queries_to_search = self.load_queries_from_json(JSON_FILE_PATH, num_needed=count)
        
        if not queries_to_search:
            self.log("No queries available for search. Exiting...")
            self.add_to_history("N/A", "[ERROR] No queries available for search")
            return

        # 2. Setup browser
        self.driver = self.setup_driver()
        try:
            # 3. Perform searches
            self.perform_searches(self.driver, queries_to_search)
        finally:
            try:
                self.driver.quit()
            except Exception as e:
                self.log(f"[WARNING] Error closing driver: {e}")
            
            time.sleep(0.5)  # pause for clean shutdown

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
        height=490,
        resizable=False,
        #frameless=True
    )
    api.set_window(window)  # pass window reference to AutoRewarderAPI for logging
    webview.start(icon=None) # add an icon 