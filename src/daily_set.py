import json
import os
import random
import time
from datetime import date
from selenium.webdriver.common.by import By

from .config import STATUS_FILE_PATH

class DailySet:
    def __init__(self, logger=None):
        self.status_file = STATUS_FILE_PATH
        self.logger = logger

    def log(self, message):
        if self.logger:
            self.logger(message)

    def should_perform_daily_set(self):
        """Check if the daily set has already been completed today"""
        today = str(date.today())

        if not os.path.exists(self.status_file):
            return True
        
        try:
            with open(self.status_file, "r") as file:
                data = json.load(file)
                return data.get("last_daily_set_date") != today
        except Exception:
            self.log(f"[ERROR] Failed to read status file: {self.status_file}")
            return True
    
    def mark_as_completed(self):
        """Mark the daily set as completed for today"""
        today = str(date.today())

        data = {}
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, "r") as file:
                    data = json.load(file)
            except Exception:
                self.log(f"[ERROR] Failed to read status file: {self.status_file}")
        
        data["last_daily_set_date"] = today
        with open(self.status_file, "w") as file:
            json.dump(data, file)
    
    def perform_daily_set(self, driver, human):
        """The main method to perform the Daily Set and 'Claim' actions"""
        self.log("Performing Daily Set and 'Claim'...")
        
        try:
            driver.get("https://rewards.bing.com")
            time.sleep(random.uniform(4, 6))
            
            main_tab = driver.current_window_handle
            
            # Use a more specific selector to target only the Daily Set tasks
            selector = "mee-rewards-daily-set-item-content .rewards-card-container" 
            
            tasks = driver.find_elements(By.CSS_SELECTOR, selector)
            if not tasks:
                self.log("[WARNING] No Daily Set tasks found on the page.")
                return False

            for i in range(len(tasks)):
                current_tasks = driver.find_elements(By.CSS_SELECTOR, selector)
                if i >= len(current_tasks): break
                
                target_task = current_tasks[i]
                
                # Click the task to open it
                human.click_element(target_task)
                time.sleep(random.uniform(2, 4))
                
                # Scroll the task page and close it
                for tab in driver.window_handles:
                    if tab != main_tab:
                        driver.switch_to.window(tab)
                        time.sleep(random.uniform(2, 4))
                        human.scroll_page()
                        driver.close()
                
                driver.switch_to.window(main_tab)
                time.sleep(random.uniform(1, 2))
            
            self.log("Daily Set collection finished successfully.")
            return True
        
        except Exception as e:
            self.log(f"[ERROR] Failed to collect Daily Set: {e}")
            return False        