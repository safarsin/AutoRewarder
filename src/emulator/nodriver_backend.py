"""Selenium-compatible facade over nodriver for the rest of AutoRewarder.

nodriver is fully asynchronous, while the app (GUI + CLI + run threads) is
synchronous. ``NodriverDriver`` bridges the two: it owns a dedicated asyncio
event loop running in a daemon thread and exposes a Selenium-like sync API
(get, find_element(s), execute_script, execute_cdp_cmd, window handles,
switch_to, back/close/quit, page_source, screenshots, ...). Elements are
wrapped as ``NodriverElement`` (click, send_keys, clear, is_displayed, ...).

nodriver itself is imported lazily so this module — and therefore the whole
app — still imports on machines where nodriver is not installed yet (tests,
CI linting).
"""

import asyncio
import concurrent.futures
import inspect
import json
import queue
import threading

from .compat import By, NoSuchElementException, TimeoutException, WebDriverException

# Builds a unique CSS path for a DOM node. Used to resolve XPath results back
# to nodriver Elements, because nodriver's Tab.xpath relies on the DOM domain,
# which some nodriver/browser combinations reject (-32601 'DOM.enable' wasn't
# found).
_CSS_PATH_FUNCTION = r"""
function cssPath(el) {
  const parts = [];
  let node = el;
  while (node && node.nodeType === 1) {
    if (node.id) {
      parts.unshift(node.tagName.toLowerCase() + '#' + CSS.escape(node.id));
      break;
    }
    let part = node.tagName.toLowerCase();
    const parent = node.parentElement;
    if (parent) {
      const same = Array.prototype.filter.call(
        parent.children, (c) => c.tagName === node.tagName
      );
      if (same.length > 1) {
        part += ':nth-of-type(' + (Array.prototype.indexOf.call(same, node) + 1) + ')';
      }
    }
    parts.unshift(part);
    node = parent;
  }
  return parts.join(' > ');
}
"""


def _is_exception_details(value):
    return hasattr(value, "exception") and hasattr(value, "text")


def _deserialize_deep(value):
    """Convert CDP deep-serialized values into plain Python values."""
    if isinstance(value, dict) and "type" in value and "value" in value:
        kind = value["type"]
        payload = value["value"]
        if kind == "object":
            if isinstance(payload, list):
                return {k: _deserialize_deep(v) for k, v in payload}
            return payload
        if kind == "array":
            return [_deserialize_deep(item) for item in (payload or [])]
        if kind in ("string", "number", "boolean"):
            return payload
        return None
    if isinstance(value, list):
        return [_deserialize_deep(item) for item in value]
    return value


class NodriverElement:
    """Selenium-like wrapper around a nodriver Element."""

    def __init__(self, driver, element):
        self._driver = driver
        self._el = element

    # -- Finding -----------------------------------------------------------

    def find_element(self, by, value):
        elements = self.find_elements(by, value)
        if not elements:
            raise NoSuchElementException(f"Unable to locate element: {value}")
        return elements[0]

    def find_elements(self, by, value):
        if by == By.CSS_SELECTOR:
            nodes = self._driver._run(self._el.query_selector_all(value))
        elif by == By.XPATH:
            nodes = self._driver._run(self._element_xpath(value))
        elif by == By.NAME:
            nodes = self._driver._run(self._el.query_selector_all(f'[name="{value}"]'))
        elif by == By.ID:
            nodes = self._driver._run(self._el.query_selector_all(f"#{value}"))
        elif by == By.TAG_NAME:
            nodes = self._driver._run(self._el.query_selector_all(value))
        else:
            raise NotImplementedError(
                f"By.{by} is not supported by the nodriver backend"
            )
        return [
            NodriverElement(self._driver, node)
            for node in (nodes or [])
            if node is not None
        ]

    async def _element_xpath(self, xpath):
        # nodriver has no element-scoped xpath; resolve the first match via
        # JS, then look it back up page-level through a unique CSS path.
        js = (
            "(elem) => {\n" + _CSS_PATH_FUNCTION + "\n"
            "  const doc = elem.ownerDocument || document;\n"
            "  const res = doc.evaluate("
            + json.dumps(xpath)
            + ", elem, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);\n"
            "  const node = res.singleNodeValue;\n"
            "  if (!node || node.nodeType !== 1) return null;\n"
            "  return cssPath(node);\n"
            "}"
        )
        path = await self._el.apply(js, return_by_value=True)
        if not path:
            return []
        return await self._el.tab.query_selector_all(path)

    # -- State -------------------------------------------------------------

    @property
    def text(self):
        return self._driver._run(
            self._el.apply(
                "(elem) => elem.innerText || elem.textContent || ''",
                return_by_value=True,
            )
        )

    @property
    def tag_name(self):
        return self._driver._run(
            self._el.apply(
                "(elem) => (elem.tagName || '').toLowerCase()",
                return_by_value=True,
            )
        )

    def get_attribute(self, name):
        return self._driver._run(
            self._el.apply(
                f"(elem) => elem.getAttribute({json.dumps(name)})",
                return_by_value=True,
            )
        )

    def is_displayed(self):
        js = (
            "(elem) => { const s = window.getComputedStyle(elem);"
            " const r = elem.getBoundingClientRect();"
            " return s.display !== 'none' && s.visibility !== 'hidden'"
            " && r.width > 0 && r.height > 0; }"
        )
        return bool(self._driver._run(self._el.apply(js, return_by_value=True)))

    def is_enabled(self):
        return bool(
            self._driver._run(
                self._el.apply("(elem) => !elem.disabled", return_by_value=True)
            )
        )

    # -- Actions -----------------------------------------------------------

    def click(self):
        self._driver._run(self._el.click())

    def send_keys(self, text):
        self._driver._run(self._el.send_keys(text))

    def clear(self):
        self._driver._run(self._el.clear_input())

    def scroll_into_view(self):
        self._driver._run(self._el.scroll_into_view())

    def apply_js(self, js_function):
        return self._driver._run(self._el.apply(js_function, return_by_value=True))


class NodriverSwitchTo:
    """Selenium-like ``driver.switch_to`` for window/tab switching."""

    def __init__(self, driver):
        self._driver = driver

    def window(self, handle):
        self._driver._switch_to_window(handle)

    def default_content(self):
        pass


class NodriverDriver:
    """Synchronous, Selenium-like wrapper around a nodriver browser/tab."""

    def __init__(
        self,
        *,
        browser_executable_path=None,
        user_data_dir=None,
        headless=False,
        browser_args=None,
        mobile=False,
        mobile_user_agent=None,
        page_load_timeout=None,
    ):
        self.browser_executable_path = browser_executable_path
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.browser_args = list(browser_args or [])
        self.mobile = bool(mobile)
        self.mobile_user_agent = mobile_user_agent
        self._page_load_timeout = page_load_timeout
        self._call_timeout = 45
        self._browser = None
        self._tab = None
        self._loop = None
        self._loop_thread = None
        self._queue = queue.Queue()
        self._stopped = False
        self._last_url = ""
        self._current_handle = None
        self._handle_map = {}
        self.switch_to = NodriverSwitchTo(self)

    # -- Lifecycle ---------------------------------------------------------

    def start(self):
        """Launch the browser (lazy nodriver import) and attach to a tab."""
        try:
            import nodriver as uc  # type: ignore[import-not-found]
        except ImportError as exc:
            raise WebDriverException(
                "nodriver is not installed. Run `pip install -r requirements.txt`."
            ) from exc

        self._start_loop()
        try:
            self._browser = self._run(
                uc.start(
                    headless=self.headless,
                    user_data_dir=self.user_data_dir,
                    browser_executable_path=self.browser_executable_path,
                    browser_args=self.browser_args,
                ),
                timeout=120,
            )
            self._tab = self._run(self._browser.get("about:blank"), timeout=30)
        except Exception:
            self._stop_loop()
            raise
        if self.mobile:
            self._apply_mobile_emulation()

    def _attach(self, browser, tab):
        """Test hook: run the facade against pre-built fake browser/tab objects."""
        self._start_loop()
        self._browser = browser
        self._tab = tab

    def _start_loop(self):
        # One event loop, driven from a dedicated thread. Coroutines are fed
        # through a thread-safe queue instead of asyncio.run_coroutine_threadsafe:
        # the queue avoids relying on asyncio's cross-thread self-pipe wakeup,
        # which some sandboxed environments do not deliver.
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop_main,
            daemon=True,
            name="nodriver-io",
        )
        self._loop_thread.start()

    def _loop_main(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            future, coro = item
            try:
                result = self._loop.run_until_complete(coro)
            except BaseException as exc:
                try:
                    future.set_exception(exc)
                except concurrent.futures.InvalidStateError:
                    pass
            else:
                try:
                    future.set_result(result)
                except concurrent.futures.InvalidStateError:
                    pass

    def _stop_loop(self):
        try:
            self._queue.put(None)
            self._loop_thread.join(timeout=5)
        except Exception:
            pass

    def _run(self, coro, timeout=None):
        if self._stopped:
            coro.close()
            raise WebDriverException("disconnected: no browser session")
        future = concurrent.futures.Future()
        self._queue.put((future, coro))
        try:
            return future.result(timeout=timeout or self._call_timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutException(
                f"Timed out after {timeout or self._call_timeout}s waiting for the browser"
            ) from None
        except (NoSuchElementException, TimeoutException):
            raise
        except Exception as exc:
            raise WebDriverException(f"Browser error: {exc}") from exc

    # -- Navigation --------------------------------------------------------

    def get(self, url):
        if self._tab is None:
            raise WebDriverException("no browser session")
        timeout = (self._page_load_timeout or 60) + 15
        try:
            tab = self._run(self._tab.get(url), timeout=timeout)
        except TimeoutException:
            # Selenium raises TimeoutException on page-load timeout; callers
            # scrape whatever rendered.
            raise
        self._tab = tab or self._tab
        self._last_url = url

    def back(self):
        self._run(self._tab.back(), timeout=30)
        self._last_url = self.current_url

    def close(self):
        self._run(self._tab.close(), timeout=15)
        self._refresh_tabs()
        self._tab = self._handle_map.get(self._current_handle)

    def quit(self):
        if self._stopped:
            return
        try:
            result = self._browser.stop()
            if inspect.isawaitable(result):
                self._run(result, timeout=15)
        except Exception:
            pass
        self._stopped = True
        # The daemon loop thread keeps running until process exit so any
        # in-flight call from another thread can still unwind (it will fail
        # with a WebDriverException once the browser process is gone).

    @property
    def current_url(self):
        if self._tab is None:
            return self._last_url
        try:
            url = self._run(self._a_evaluate("location.href"))
            if url:
                self._last_url = url
        except WebDriverException:
            pass
        return self._last_url

    @property
    def page_source(self):
        return self._run(self._tab.get_content())

    def save_screenshot(self, path):
        self._run(self._tab.save_screenshot(str(path), format="png"))

    def set_page_load_timeout(self, seconds):
        self._page_load_timeout = float(seconds)

    # -- JavaScript / CDP --------------------------------------------------

    async def _a_evaluate(self, script):
        # nodriver's evaluate: pass return_by_value=False so containers come
        # back through deep serialization; wrap in a function when the script
        # uses top-level `return` (illegal in a raw Runtime.evaluate); surface
        # genuine JS errors as WebDriverException.
        result = await self._tab.evaluate(script, return_by_value=False)
        if _is_exception_details(result):
            wrapped = await self._tab.evaluate(
                "(function() {\n" + script + "\n})()", return_by_value=False
            )
            if _is_exception_details(wrapped):
                description = getattr(
                    getattr(wrapped, "exception", None), "description", None
                ) or str(wrapped)
                raise WebDriverException(f"Script error: {description[:200]}")
            result = wrapped
        if hasattr(result, "object_id") and not _deserialize_deep(result):
            return None
        return _deserialize_deep(result)

    def execute_script(self, script, *args):
        if self._tab is None:
            raise WebDriverException("no browser session")
        if not args:
            return self._run(self._a_evaluate(script))
        if any(isinstance(arg, NodriverElement) for arg in args):
            element = args[0]
            body = script.replace("arguments[0]", "elem")
            return element.apply_js("(elem) => {\n" + body + "\n}")
        body = script
        for index, arg in enumerate(args):
            body = body.replace(f"arguments[{index}]", json.dumps(arg))
        return self._run(self._a_evaluate(body))

    def execute_cdp_cmd(self, command, params=None):
        if self._tab is None:
            raise WebDriverException("no browser session")
        cmd = self._cdp_command(command, params or {})
        return self._run(self._tab.send(cmd))

    @staticmethod
    def _cdp_command(command, params):
        try:
            from nodriver import cdp
        except ImportError as exc:
            raise WebDriverException(
                "nodriver is not installed. Run `pip install -r requirements.txt`."
            ) from exc

        if command == "Network.clearBrowserCookies":
            return cdp.network.clear_browser_cookies()
        if command == "Network.clearBrowserCache":
            return cdp.network.clear_browser_cache()
        if command == "Emulation.setTouchEmulationEnabled":
            return cdp.emulation.set_touch_emulation_enabled(
                enabled=bool(params.get("enabled")),
                max_touch_points=params.get("maxTouchPoints"),
            )
        if command == "Emulation.setEmitTouchEventsForMouse":
            return cdp.emulation.set_emit_touch_events_for_mouse(
                enabled=bool(params.get("enabled")),
                configuration=params.get("configuration"),
            )
        if command == "Emulation.setDeviceMetricsOverride":
            return cdp.emulation.set_device_metrics_override(
                width=int(params["width"]),
                height=int(params["height"]),
                device_scale_factor=float(params.get("deviceScaleFactor", 0)),
                mobile=bool(params.get("mobile", False)),
            )
        if command == "Emulation.setUserAgentOverride":
            metadata = params.get("userAgentMetadata")
            if isinstance(metadata, dict):
                metadata = cdp.emulation.UserAgentMetadata(
                    platform=metadata.get("platform", ""),
                    platform_version=metadata.get("platformVersion", ""),
                    architecture=metadata.get("architecture", ""),
                    model=metadata.get("model", ""),
                    mobile=bool(metadata.get("mobile", False)),
                )
            return cdp.emulation.set_user_agent_override(
                user_agent=params["userAgent"],
                platform=params.get("platform"),
                user_agent_metadata=metadata,
            )
        if command == "Page.setDownloadBehavior":
            return cdp.page.set_download_behavior(
                behavior=params.get("behavior", "allow"),
                download_path=params.get("downloadPath"),
            )
        raise NotImplementedError(f"Unsupported CDP command: {command}")

    def _apply_mobile_emulation(self):
        # Same CDP overrides the old Selenium driver applied for mobile mode.
        try:
            self.execute_cdp_cmd(
                "Emulation.setTouchEmulationEnabled",
                {"enabled": True, "maxTouchPoints": 5},
            )
            self.execute_cdp_cmd(
                "Emulation.setEmitTouchEventsForMouse",
                {"enabled": True, "configuration": "mobile"},
            )
            self.execute_cdp_cmd(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 412,
                    "height": 915,
                    "deviceScaleFactor": 3,
                    "mobile": True,
                },
            )
            if self.mobile_user_agent:
                self.execute_cdp_cmd(
                    "Emulation.setUserAgentOverride",
                    {
                        "userAgent": self.mobile_user_agent,
                        "platform": "iPhone",
                        "userAgentMetadata": {
                            "platform": "iOS",
                            "platformVersion": "17.2.1",
                            "architecture": "",
                            "model": "iPhone",
                            "mobile": True,
                        },
                    },
                )
        except Exception:
            # CDP is best-effort; fall back to the UA + window-size flags.
            pass

    # -- Finding -----------------------------------------------------------

    def find_element(self, by, value):
        elements = self.find_elements(by, value)
        if not elements:
            raise NoSuchElementException(f"Unable to locate element: {value}")
        return elements[0]

    async def _a_xpath(self, xpath):
        js = (
            "(function() {\n" + _CSS_PATH_FUNCTION + "\n"
            "  const res = document.evaluate("
            + json.dumps(xpath)
            + ", document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);\n"
            "  const out = [];\n"
            "  for (let i = 0; i < res.snapshotLength; i++) {\n"
            "    const node = res.snapshotItem(i);\n"
            "    if (!node || node.nodeType !== 1) continue;\n"
            "    out.push(cssPath(node));\n"
            "  }\n"
            "  return out;\n"
            "})()"
        )
        paths = await self._a_evaluate(js) or []
        nodes = []
        for path in paths:
            nodes.extend(await self._tab.query_selector_all(path) or [])
        return nodes

    def find_elements(self, by, value):
        if self._tab is None:
            raise WebDriverException("no browser session")
        if by == By.CSS_SELECTOR:
            nodes = self._run(self._tab.query_selector_all(value))
        elif by == By.XPATH:
            nodes = self._run(self._a_xpath(value))
        elif by == By.NAME:
            nodes = self._run(self._tab.query_selector_all(f'[name="{value}"]'))
        elif by == By.ID:
            nodes = self._run(self._tab.query_selector_all(f"#{value}"))
        elif by == By.TAG_NAME:
            nodes = self._run(self._tab.query_selector_all(value))
        else:
            raise NotImplementedError(
                f"By.{by} is not supported by the nodriver backend"
            )
        return [
            NodriverElement(self, node) for node in (nodes or []) if node is not None
        ]

    # -- Tabs / windows ----------------------------------------------------

    def _refresh_tabs(self):
        if self._browser.stopped:
            self._handle_map = {}
            self._current_handle = None
            self._stopped = True
            return []
        try:
            self._run(self._browser.update_targets(), timeout=15)
        except Exception:
            # Browser may be still alive (network hiccup); clear handles
            # but don't mark stopped yet — quit() needs to clean up.
            self._handle_map = {}
            self._current_handle = None
            return []
        tabs = []
        try:
            tabs = list(self._browser.tabs or [])
        except Exception:
            self._handle_map = {}
            self._current_handle = None
            return []
        self._handle_map = {}
        for tab in tabs:
            try:
                self._handle_map[str(tab.target.target_id)] = tab
            except Exception:
                continue
        if self._current_handle not in self._handle_map:
            self._current_handle = next(iter(self._handle_map), None)
        return tabs

    @property
    def window_handles(self):
        self._refresh_tabs()
        return list(self._handle_map.keys())

    @property
    def current_window_handle(self):
        self._refresh_tabs()
        return self._current_handle

    def _switch_to_window(self, handle):
        self._refresh_tabs()
        if handle not in self._handle_map:
            raise WebDriverException(f"no such window: {handle}")
        tab = self._handle_map[handle]
        try:
            self._run(tab.activate(), timeout=15)
        except Exception:
            pass
        self._tab = tab
        self._current_handle = handle

    # -- Input helpers (used by HumanBehavior / SearchEngine) ---------------

    def mouse_move_to(self, x, y):
        self._run(self._tab.mouse_move(int(x), int(y), steps=1))

    def mouse_click(self, x, y):
        self._run(self._tab.mouse_click(int(x), int(y)))

    def mouse_down(self, x, y):
        self._dispatch_mouse("mousePressed", x, y, buttons=1)

    def mouse_move_pressed(self, x, y):
        self._dispatch_mouse("mouseMoved", x, y, buttons=1)

    def mouse_up(self, x, y):
        self._dispatch_mouse("mouseReleased", x, y, buttons=0)

    def _dispatch_mouse(self, event_type, x, y, buttons):
        try:
            from nodriver import cdp
        except ImportError as exc:
            raise WebDriverException(
                "nodriver is not installed. Run `pip install -r requirements.txt`."
            ) from exc
        self._run(
            self._tab.send(
                cdp.input_.dispatch_mouse_event(
                    type_=event_type,
                    x=int(x),
                    y=int(y),
                    button="left",
                    buttons=buttons,
                    click_count=1,
                )
            )
        )

    def mouse_drag(self, start, end, steps=10):
        self._run(
            self._tab.mouse_drag(
                (int(start[0]), int(start[1])),
                (int(end[0]), int(end[1])),
                steps=int(steps),
            )
        )

    def send_keys_to_active(self, text):
        try:
            from nodriver import cdp
        except ImportError as exc:
            raise WebDriverException(
                "nodriver is not installed. Run `pip install -r requirements.txt`."
            ) from exc

        self._run(self._tab.send(cdp.input_.insert_text(text=text)))

    def press_enter(self):
        self._dispatch_key("Enter", "Enter", 13, text="\r")

    def press_ctrl_l(self):
        self._dispatch_key("l", "KeyL", 76, modifiers=2)

    def _dispatch_key(self, key, code, vk, modifiers=0, text=None):
        try:
            from nodriver import cdp
        except ImportError as exc:
            raise WebDriverException(
                "nodriver is not installed. Run `pip install -r requirements.txt`."
            ) from exc

        # Full trusted sequence: rawKeyDown -> char -> keyUp. A bare keyDown
        # alone does not reliably trigger form submission in Chromium.
        self._run(
            self._tab.send(
                cdp.input_.dispatch_key_event(
                    type_="rawKeyDown",
                    key=key,
                    code=code,
                    windows_virtual_key_code=vk,
                    modifiers=modifiers,
                )
            )
        )
        if text is not None:
            self._run(
                self._tab.send(
                    cdp.input_.dispatch_key_event(
                        type_="char",
                        text=text,
                        key=key,
                        code=code,
                        windows_virtual_key_code=vk,
                        modifiers=modifiers,
                    )
                )
            )
        self._run(
            self._tab.send(
                cdp.input_.dispatch_key_event(
                    type_="keyUp",
                    key=key,
                    code=code,
                    windows_virtual_key_code=vk,
                    modifiers=modifiers,
                )
            )
        )

    def set_download_path(self, path):
        self._run(self._tab.set_download_path(str(path)))
