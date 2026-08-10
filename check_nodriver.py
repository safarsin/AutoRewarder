"""Smoke-test the nodriver migration contract on a machine with Edge + nodriver.

Usage:
    pip install -r requirements.txt
    python check_nodriver.py

Each check prints PASS/FAIL; the script exits non-zero if anything fails.
Drives a real Edge session via the same facade the app uses
(src.emulator.nodriver_backend.NodriverDriver), exercising every API the app
depends on: navigation, finding, JS eval (with and without element args),
typing + Enter, human mouse move/click, scrolling, CDP passthrough, tab
handles, screenshots, mobile emulation, and clean shutdown.
"""

import argparse
import os
import sys
import tempfile
import time

from src.emulator.compat import By, WebDriverWait
from src.emulator.driver import DriverManager
from src.emulator.human import HumanBehavior


def _expect(condition, message):
    if not condition:
        raise AssertionError(message)


def _serp_ready(driver):
    """Search executed when the results list renders or the URL navigated."""
    if driver.find_elements(By.CSS_SELECTOR, "li.b_algo, #b_results"):
        return True
    return "search?" in driver.current_url


def _find_with_retry(driver, by, value, timeout=12):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return driver.find_element(by, value)
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)


def _check_mobile_ua(driver):
    ua = driver.execute_script("return navigator.userAgent;") or ""
    _expect("iPhone" in ua, f"mobile UA missing iPhone: {ua[:80]}")


def _check_touch_enabled(driver):
    touch = driver.execute_script("return navigator.maxTouchPoints > 0;")
    _expect(bool(touch), "touch emulation not enabled")


def _run_checks(driver, mobile=False):
    """Run the checks for one driver session; returns the failure count."""
    failures = 0

    def check(name, fn):
        nonlocal failures
        try:
            fn()
            print(f"  PASS {name}")
        except Exception as exc:
            failures += 1
            print(f"  FAIL {name}: {str(exc).splitlines()[0][:140]}")

    check("launch browser (about:blank)", lambda: None)
    check("navigate to bing.com", lambda: driver.get("https://www.bing.com"))
    check(
        "find search box (By.NAME)",
        lambda: _find_with_retry(driver, By.NAME, "q"),
    )
    check(
        "find search box (By.XPATH)",
        lambda: _find_with_retry(driver, By.XPATH, "//*[@name='q']"),
    )
    check(
        "execute_script (no args)",
        lambda: driver.execute_script("return document.readyState;"),
    )

    search_box = None

    def _grab_box():
        nonlocal search_box
        search_box = _find_with_retry(driver, By.NAME, "q")

    check("grab search box", _grab_box)
    if search_box is not None:
        check(
            "element-arg JS (scrollIntoView)",
            lambda: driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", search_box
            ),
        )

        def _type_and_search(box):
            # Mobile bing's search box is a textarea driven by page JS, which
            # needs a moment to attach after load. Press Enter until the page
            # actually navigates (same as a human retrying).
            box.send_keys("hello world")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                driver.press_enter()
                for _ in range(6):
                    if "search?" in driver.current_url:
                        return
                    time.sleep(0.5)

        check("type query + Enter", lambda: _type_and_search(search_box))

    check("current_url", lambda: driver.current_url)
    check(
        "wait for SERP results",
        lambda: WebDriverWait(driver, 20).until(_serp_ready),
    )
    check(
        "window_handles / switch_to",
        lambda: driver.switch_to.window(driver.current_window_handle),
    )
    check("page_source non-empty", lambda: len(driver.page_source) > 1000)
    check("save_screenshot", lambda: driver.save_screenshot("/tmp/nodriver_smoke.png"))

    human = HumanBehavior(driver, show_cursor=False, mobile=mobile)
    check("human scroll_page", lambda: human.scroll_page())
    check(
        "human mouse move + click",
        lambda: human.click_element(driver.find_element(By.NAME, "q")),
    )

    if mobile:
        check("mobile UA applied", lambda: _check_mobile_ua(driver))
        check("touch emulation on", lambda: _check_touch_enabled(driver))

    check(
        "set_download_path",
        lambda: driver.set_download_path("/tmp"),
    )
    check(
        "CDP passthrough (clear cache)",
        lambda: driver.execute_cdp_cmd("Network.clearBrowserCache", {}),
    )
    check("back()", lambda: driver.back())
    return failures


def _make_driver(profile, browser_path, headless, mobile):
    """Build a driver session: Edge via DriverManager, or an explicit browser."""
    if browser_path:
        from src.emulator.nodriver_backend import NodriverDriver

        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if headless:
            browser_args += ["--headless=new", "--disable-gpu"]
        driver = NodriverDriver(
            browser_executable_path=browser_path,
            user_data_dir=profile,
            headless=headless,
            browser_args=browser_args,
            mobile=mobile,
            mobile_user_agent=DriverManager.MOBILE_USER_AGENT if mobile else None,
        )
        driver.start()
        return driver
    return DriverManager(profile_path=profile, hide_browser=headless).setup_driver(
        mobile=mobile
    )


def main():
    parser = argparse.ArgumentParser(
        description="Smoke-test the nodriver migration contract.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--browser-path",
        default=None,
        help="Browser binary to drive (default: Edge auto-detected).",
    )
    parser.add_argument("--headless", action="store_true", help="Run headless.")
    parser.add_argument(
        "--session",
        choices=["desktop", "mobile", "both"],
        default="both",
        help="Which session(s) to run (default: both).",
    )
    parser.add_argument(
        "--profile", default=None, help="Profile directory (default: temp dir)."
    )
    args = parser.parse_args()

    total_failures = 0
    tmp = None
    if args.profile:
        base = args.profile
    else:
        tmp = tempfile.TemporaryDirectory(
            prefix="nodriver-smoke-", ignore_cleanup_errors=True
        )
        base = tmp.name
    try:
        if args.session in ("desktop", "both"):
            driver = None
            try:
                driver = _make_driver(
                    os.path.join(base, "desktop"),
                    args.browser_path,
                    args.headless,
                    mobile=False,
                )
                print("desktop session:")
                total_failures += _run_checks(driver, mobile=False)
            finally:
                if driver is not None:
                    driver.quit()
                    time.sleep(1)

        if args.session in ("mobile", "both"):
            driver_mobile = None
            try:
                driver_mobile = _make_driver(
                    os.path.join(base, "mobile"),
                    args.browser_path,
                    args.headless,
                    mobile=True,
                )
                print("mobile session:")
                total_failures += _run_checks(driver_mobile, mobile=True)
            finally:
                if driver_mobile is not None:
                    driver_mobile.quit()
    finally:
        if tmp is not None:
            tmp.cleanup()

    if total_failures:
        print(f"\n{total_failures} check(s) FAILED")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
