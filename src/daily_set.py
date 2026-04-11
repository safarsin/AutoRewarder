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
        """The main method to perform the Daily Set"""
        self.log("Performing Daily Set")
        
        try:
            driver.get("https://rewards.bing.com")
            time.sleep(random.uniform(4, 6))
            
            main_tab = driver.current_window_handle
            
            # Locate Daily Set cards by their container, but prefer clicking the real
            # clickable anchor inside the card to avoid 0x0 / non-interactable containers.
            selector = "mee-rewards-daily-set-item-content .rewards-card-container" 
            clickable_selector = "a.ds-card-sec, a[role='link'][href]"
            
            tasks = driver.find_elements(By.CSS_SELECTOR, selector)
            if not tasks:
                self.log("[WARNING] No Daily Set tasks found on the page.")
                return False

            # One-time scroll to the Daily Set area before moving the mouse.
            # (No further scrolling during mouse movement: we pass scroll_into_view=False.)
            try:
                driver.execute_script(
                    "document.documentElement.style.scrollBehavior='auto';"
                    "document.body.style.scrollBehavior='auto';"
                )
            except Exception:
                pass

            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
                    tasks[0]
                )
                time.sleep(random.uniform(1, 2))
            except Exception:
                pass

            def _pick_click_target(card):
                # Rewards is a dynamic SPA; containers can temporarily become 0x0 during re-renders.
                # Prefer the inner link element when available.
                try:
                    candidates = card.find_elements(By.CSS_SELECTOR, clickable_selector)
                except Exception:
                    candidates = []

                for el in candidates:
                    try:
                        w, h = driver.execute_script(
                            """
                            const r = arguments[0].getBoundingClientRect();
                            return [r.width, r.height];
                            """,
                            el,
                        )
                        if float(w) > 6 and float(h) > 6:
                            return el
                    except Exception:
                        continue
                return card

            for i in range(len(tasks)):
                current_tasks = driver.find_elements(By.CSS_SELECTOR, selector)
                if i >= len(current_tasks): break
                
                target_task = current_tasks[i]

                click_target = _pick_click_target(target_task)

                try:
                    # Skip elements that are temporarily 0x0 (Rewards SPA re-renders a lot).
                    try:
                        w, h = driver.execute_script(
                            """
                            const r = arguments[0].getBoundingClientRect();
                            return [r.width, r.height];
                            """,
                            click_target,
                        )
                        if float(w) <= 6 or float(h) <= 6:
                            continue
                    except Exception:
                        pass

                    before_tabs = set(driver.window_handles)

                    # Click the task to open it
                    human.click_element(click_target, scroll_into_view=False)
                    time.sleep(random.uniform(2, 4))

                    # Scroll the task page and close newly opened tabs
                    # Detect newly opened tabs by comparing window handles before/after click.
                    new_tabs = [h for h in driver.window_handles if h != main_tab and h not in before_tabs]
                    for tab in new_tabs:
                        driver.switch_to.window(tab)
                        time.sleep(random.uniform(2, 4))
                        human.scroll_page()
                        driver.close()

                    driver.switch_to.window(main_tab)
                    time.sleep(random.uniform(1, 2))

                except Exception as e:
                    short_error = str(e).split("\n")[0][:160]
                    self.log(f"[WARNING] Daily Set task #{i+1} failed: {short_error}")

                    # Close any extra tabs, switch back to the main tab, and continue.
                    try:
                        for tab in list(driver.window_handles):
                            if tab != main_tab:
                                driver.switch_to.window(tab)
                                driver.close()
                    except Exception:
                        pass
                    try:
                        driver.switch_to.window(main_tab)
                    except Exception:
                        pass
                    time.sleep(random.uniform(0.5, 1.0))
            
            return True
        
        except Exception as e:
            self.log(f"[ERROR] Failed to collect Daily Set: {e}")
            return False        