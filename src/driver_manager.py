from selenium import webdriver
from selenium.webdriver.edge.options import Options
from .config import EDGE_PROFILE_PATH

class DriverManager:
    def __init__(self, hide_browser=False):
        self.hide_browser = hide_browser

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

    def close_running_edge(self):
        """ 
        Close running Edge processes to avoid conflicts with the Selenium profile.
        Optional, because the new bot uses a separate profile to avoid conflicts, so it should work even if the main Edge browser is open.
        But can be useful if users have issues with the bot not working due to conflicts with their main Edge browser. 
        """

        # Close running Edge processes to avoid conflicts with the Selenium profile
        # os.system("taskkill /f /im msedge.exe >nul 2>&1")
        # os.system("taskkill /f /im msedgedriver.exe >nul 2>&1")
        # time.sleep(2)
        return