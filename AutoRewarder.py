import os
import json
import random
import time
import webview
import threading
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, WebDriverException

# Configs 
# Create a separate folder for the bot's profile to avoid conflicts with your main browser
APP_DIR = os.path.join(
    os.environ["USERPROFILE"],
    "AppData", 
    "Local", 
    "AutoRewarder"
)

# Base paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GUI_DIR = os.path.join(BASE_DIR, "GUI")

if not os.path.exists(APP_DIR):
    os.makedirs(APP_DIR)

EDGE_PROFILE_PATH = os.path.join(APP_DIR, "EdgeProfile")
HISTORY_FILE_PATH = os.path.join(APP_DIR, "history.json")
SETTINGS_FILE_PATH = os.path.join(APP_DIR, "settings.json")
JSON_FILE_PATH = os.path.join(BASE_DIR, "queries.json")

class AutoRewarderAPI:
    def __init__(self):
        self._webview_window = None # Reference to the webview window for logging
        self.history_file = HISTORY_FILE_PATH 
        self._driver_loader_thread_started = False

        # Load settings from file or create with default values if it doesn't exist
        settings = self.get_settings() 
        self.hide_browser = settings.get("hide_browser", False) # Default mode is visible browser or it will run in hidden mode (headless)

        self.is_driver_loading = False

    def set_window(self, window):
        # store reference to webview window so Python can call JS (evaluate_js)
        self._webview_window = window

        # Loading the driver in a bg thread to avoid UI freezing
        # This is especially important during the first start or when Edge updates are released
        # (every 1-2 weeks), because downloading a new driver can take some time.
        if not self._driver_loader_thread_started:
            self._driver_loader_thread_started = True
            threading.Thread(target=self.load_driver_in_background, daemon=True).start()

    # Open a new window to show search history
    def open_history_window(self):
        webview.create_window(
            title="Query History",
            url=os.path.join(GUI_DIR, "history.html"),
            js_api=self,  
            width=700,
            height=500,
            resizable=True,
            background_color='#0d1117',
            text_select=True
        )
    
    # Load the WebDriver in a bg thread
    def load_driver_in_background(self):
        self.is_driver_loading = True

        try:
            # Trigger Selenium Manager to download/prepare the driver
            driver = self.setup_driver(headless=True)
            driver.quit()
        except Exception as e:
            self.log(f"[ERROR] Error loading WebDriver: {e}")
        finally:
            self.is_driver_loading = False

            if hasattr(self, "_webview_window") and self._webview_window:
                self._webview_window.evaluate_js("stop_loader()")
    
    # Fun for JS to check status of the driver
    def check_driver_status(self):
        return self.is_driver_loading
    
    # Get settings from settings.json or create it with default values if it doesn't exist
    def get_settings(self):
        if not os.path.exists(SETTINGS_FILE_PATH):
            default_settings = {
                "first_setup_done": False,
                "hide_browser": False
            }

            with open(SETTINGS_FILE_PATH, "w", encoding="utf-8") as file:
                json.dump(default_settings, file, indent=4)
            return default_settings
        
        with open(SETTINGS_FILE_PATH, "r", encoding="utf-8") as file:
            return json.load(file)

    # Mark in settings that first setup is done    
    def mark_up_as_done(self):
        settings = self.get_settings()
        settings["first_setup_done"] = True

        with open(SETTINGS_FILE_PATH, "w", encoding="utf-8") as file:
            json.dump(settings, file, indent=4)
    
    # First setup function to let user log in to their Microsoft account and prepare the Edge profile for the bot
    def first_setup(self):
        self.log("Starting First Setup... Please log in to your Microsoft account.")

        setup_driver = self.setup_driver(headless=False)  # Open browser in normal mode for login

        try:
            self.log("Opening Bing page...")
            self.log(f"""Log in directly on the Bing page.
            IMPORTANT: Do NOT sync the Edge profile!
            Just log in and close the browser when done.""")
            time.sleep(4)
            setup_driver.get("https://www.bing.com")
            self.log("Waiting for you to log in...\nClose the browser window when done!")

            while len(setup_driver.window_handles) > 0:
                time.sleep(1)

        except Exception as e:
            error_msg = str(e).lower()

            if "target window already closed" in error_msg or "disconnected" in error_msg or "not reachable" in error_msg:
                pass 
            else:
                # If unexpected error, log it and add to history
                self.log(f"[ERROR] Error during setup: {e}")
                self.add_to_history("First Setup Failed", "Error")
                return

        finally:
            try:
                setup_driver.quit()
            except Exception:
                pass

            self.log("First Setup completed! You can now start the bot.")

            self.mark_up_as_done()

            self.add_to_history("First Setup Completed", "Success")

            if self._webview_window:
                self._webview_window.evaluate_js("enable_start_button()")
                self._webview_window.evaluate_js("hide_setup_button()")

    # Function for toggle browser hidden mode and save the setting
    def set_hide_browser(self, is_hide):
        self.hide_browser = is_hide

        settings = self.get_settings()
        settings["hide_browser"] = is_hide

        with open(SETTINGS_FILE_PATH, "w", encoding="utf-8") as file:
            json.dump(settings, file, indent=4)

        self.log(f"Browser hidden mode: {'ON' if is_hide else 'OFF'}")

    # Load search history from JSON file
    def get_history(self):
        if not os.path.exists(self.history_file) or os.path.getsize(self.history_file) == 0:
            return []
        
        try:
            with open(self.history_file, "r", encoding="utf-8") as file:
                return json.load(file)
        except json.JSONDecodeError:
            self.log("[ERROR] History file was empty or damaged. Starting with a fresh one.")
            return []

    # Save search history to temp file first and then replace the original file to avoid data corruption    
    def save_history(self, history_list):
        temp_file = self.history_file + ".tmp"

        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(history_list, file, indent=4)
        
        # Replace the original file with the updated one
        os.replace(temp_file, self.history_file)
    
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

        self.save_history(history_list)

    # Send message to UI log area
    def log(self, message):
        if self._webview_window:
            try:
                safe_message = json.dumps(message)
                self._webview_window.evaluate_js(f"update_log({safe_message})")
            except Exception as e:
                print(f"Log error: {e}")

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

    # Human-like typing with random delays between keystrokes
    def human_typing(self, element, text):
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.05, 0.18))

    # Setup Selenium WebDriver
    def setup_driver(self, headless=None):
        if headless is None:
            headless = self.hide_browser

        #Setup Microsoft Edge (driver will be downloaded automatically!)
        options = Options()
        options.add_argument(f"--user-data-dir={EDGE_PROFILE_PATH}")
        options.add_argument("--profile-directory=Default") # Use the default profile or change to a specific one if needed
        options.add_argument("--disable-blink-features=AutomationControlled") # Hide automation
        options.add_argument("--no-default-browser-check")  # Don't check if Edge is default
        options.add_experimental_option("excludeSwitches", ["enable-automation"]) # Remove "Browser is being controlled by automated test software" infobar
        
        if headless:
            # Run in headless mode (invisible)
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-gpu")  # Disable GPU for headless mode
        
        # Automatic driver dowload and setup
        _driver = webdriver.Edge(options=options)
        return _driver

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
                self.human_typing(search_box, query)
                search_box.send_keys(Keys.RETURN) # Press Enter to search

                # Wait for result to load
                time.sleep(random.uniform(2, 4))

                # JS script for smooth scroll down to mimic human behavior
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

    # Close running Edge processes to avoid conflicts with the Selenium profile
    # Optional, because the new bot uses a separate profile to avoid conflicts, so it should work even if the main Edge browser is open.
    # But can be useful if users have issues with the bot not working due to conflicts with their main Edge browser
    def close_running_edge(self):
        # Close running Edge processes to avoid conflicts with the Selenium profile
        # os.system("taskkill /f /im msedge.exe >nul 2>&1")
        # os.system("taskkill /f /im msedgedriver.exe >nul 2>&1")
        # time.sleep(2)
        return

    # Main function to run the bot
    def main(self, count):
        self.log("Starting AutoRewarder (Edge Edition)...")
        
        # 1. Get queries to search from JSON file
        queries_to_search = self.load_queries_from_json(JSON_FILE_PATH, num_needed=count)
        
        if not queries_to_search:
            self.log("No queries available for search. Exiting...")
            self.add_to_history("N/A", "[ERROR] No queries available for search")
            return

        # 2. Setup browser
        self._driver = self.setup_driver()
        try:
            # 3. Perform searches
            self.perform_searches(self._driver, queries_to_search)
        finally:
            try:
                self._driver.quit()
            except Exception as e:
                self.log(f"[WARNING] Error closing driver: {e}")
            
            time.sleep(0.5)  # pause for clean shutdown

            self.log("Done!")
            # Re-enable button after finish
            if self._webview_window:
                self._webview_window.evaluate_js("enable_start_button()")

# Entry point of the application
if __name__ == "__main__":
    api = AutoRewarderAPI()
    window = webview.create_window(
        title= "AutoRewarder",
        url=os.path.join(GUI_DIR, "index.html"),
        js_api=api,
        width=570,
        height=490,
        resizable=False,
        #frameless=True
    )
    api.set_window(window)  # pass window reference to AutoRewarderAPI for logging
    webview.start(icon=None) # add an icon 