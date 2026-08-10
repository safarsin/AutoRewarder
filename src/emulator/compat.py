"""Selenium-compatible aliases for code that used to import Selenium.

The app was written against Selenium's API surface (``By`` constants,
exception types, ``WebDriverWait``, ``expected_conditions``). After the
nodriver migration those are provided here so call sites keep working
unchanged; the actual browser driver is ``NodriverDriver`` in
``nodriver_backend.py``.
"""

import time


class WebDriverException(Exception):
    """Base error for browser-driver failures (mirrors Selenium)."""


class NoSuchElementException(WebDriverException):
    """Raised when an element cannot be found."""


class TimeoutException(WebDriverException):
    """Raised when a wait or page load exceeds its timeout."""


class By:
    """Mirror of ``selenium.webdriver.common.by.By``."""

    ID = "id"
    XPATH = "xpath"
    LINK_TEXT = "link text"
    PARTIAL_LINK_TEXT = "partial link text"
    NAME = "name"
    TAG_NAME = "tag name"
    CLASS_NAME = "class name"
    CSS_SELECTOR = "css selector"


class WebDriverWait:
    """Minimal re-implementation of Selenium's polling wait."""

    def __init__(
        self,
        driver,
        timeout,
        poll_frequency=0.5,
        ignored_exceptions=None,
    ):
        self._driver = driver
        self._timeout = timeout
        self._poll = poll_frequency
        if ignored_exceptions is None:
            ignored_exceptions = (NoSuchElementException,)
        self._ignored = tuple(ignored_exceptions)

    def until(self, method, message=""):
        deadline = time.monotonic() + self._timeout
        last_exc = None
        while True:
            try:
                value = method(self._driver)
                if value:
                    return value
            except self._ignored as exc:
                last_exc = exc
            if time.monotonic() >= deadline:
                break
            time.sleep(self._poll)
        if last_exc is not None:
            raise TimeoutException(
                message or f"Timed out after {self._timeout} seconds: {last_exc}"
            ) from last_exc
        raise TimeoutException(message or f"Timed out after {self._timeout} seconds")


class expected_conditions:
    """The subset of Selenium's expected_conditions the app uses."""

    @staticmethod
    def presence_of_all_elements_located(locator):
        by, value = locator

        def _predicate(driver):
            return driver.find_elements(by, value)

        return _predicate
