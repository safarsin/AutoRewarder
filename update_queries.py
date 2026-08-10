"""Refresh AutoRewarder search queries from Google Trends."""

import argparse
import csv
import json
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_QUERIES_FILE = Path("assets/queries.json")
DEFAULT_BASE_FILE = Path("assets/queries.base.json")
DEFAULT_GEO = "US"
DEFAULT_HOURS = 168
DEFAULT_BROWSER = "edge"
DEFAULT_TIMEOUT = 45
MAX_QUERY_WORDS = 10
MAX_TREND_TOPIC_QUERIES = 3
TRENDS_URL = "https://trends.google.com/trending?geo={geo}&hours={hours}"
BREAKDOWN_KEYS = {
    "trend breakdown",
    "trend_breakdown",
    "trendbreakdown",
    "breakdown",
    "related queries",
    "related_queries",
}
QUERY_KEYS = {
    "entitynames",
    "entity_names",
    "title",
    "query",
    "search_term",
    "search term",
}


@dataclass(frozen=True)
class UpdateResult:
    total_count: int
    trend_count: int
    added_count: int
    created_base: bool


def normalize_query(query):
    return " ".join(str(query).strip().split())


def is_clean_query(query):
    if not query or not all(32 <= ord(character) <= 126 for character in query):
        return False
    if not re.search(r"[A-Za-z]", query):
        return False
    if len(query) < 3:
        return False
    if len(query.split()) > MAX_QUERY_WORDS:
        return False
    if re.search(r"[A-Za-z]\.[A-Za-z]", query):
        return False
    return True


def trend_topic_key(query):
    words = re.findall(r"[A-Za-z0-9+]+", query.casefold())
    if "worldcup" in words or ("world" in words and "cup" in words):
        return "world cup"
    return " ".join(words[:2]) if words else query.casefold()


def limit_trend_topic_repetition(queries, max_per_topic=MAX_TREND_TOPIC_QUERIES):
    counts = {}
    output = []
    for query in queries:
        key = trend_topic_key(query)
        if counts.get(key, 0) >= max_per_topic:
            continue
        counts[key] = counts.get(key, 0) + 1
        output.append(query)
    return output


def dedupe_queries(queries):
    seen = set()
    output = []
    for raw_query in queries:
        query = normalize_query(raw_query)
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        output.append(query)
    return output


def split_breakdown_value(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        pieces = []
        for item in value:
            pieces.extend(split_breakdown_value(item))
        return pieces
    return [piece.strip() for piece in str(value).split(",")]


def extract_queries_from_rows(rows):
    raw_queries = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            normalized_key = str(key).strip().casefold().replace(" ", "_")
            readable_key = str(key).strip().casefold()
            if normalized_key in BREAKDOWN_KEYS or readable_key in BREAKDOWN_KEYS:
                raw_queries.extend(split_breakdown_value(value))
            elif normalized_key in QUERY_KEYS or readable_key in QUERY_KEYS:
                raw_queries.extend(split_breakdown_value(value))

    clean_queries = [normalize_query(query) for query in raw_queries]
    clean_queries = [query for query in clean_queries if is_clean_query(query)]
    return dedupe_queries(clean_queries)


def parse_trends_csv(csv_text):
    rows = []
    reader = csv.DictReader(csv_text.lstrip("\ufeff").splitlines())
    for row in reader:
        cleaned = {}
        for key, value in row.items():
            if key is None:
                continue
            cleaned[str(key).strip()] = "" if value is None else str(value).strip()
        if cleaned:
            rows.append(cleaned)
    return rows


def dataframe_to_rows(data):
    if hasattr(data, "to_dict"):
        return data.to_dict("records")
    if isinstance(data, list):
        return data
    if isinstance(data, tuple):
        return list(data)
    raise ValueError(f"Unsupported trends result type: {type(data).__name__}")


def build_trends_driver(browser, download_dir, headless=True, timeout=DEFAULT_TIMEOUT):
    if browser == "edge":
        from src.emulator.driver import _edge_executable_path

        browser_executable_path = _edge_executable_path()
    elif browser == "chrome":
        browser_executable_path = None
    else:
        raise ValueError("browser must be edge or chrome")

    browser_args = [
        "--window-size=1600,1000",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
    ]
    if headless:
        browser_args.append("--headless=new")
        browser_args.append("--disable-gpu")

    from src.emulator.nodriver_backend import NodriverDriver

    driver = NodriverDriver(
        browser_executable_path=browser_executable_path,
        user_data_dir=None,
        headless=headless,
        browser_args=browser_args,
        page_load_timeout=timeout,
    )
    driver.start()
    try:
        driver.set_download_path(download_dir)
    except Exception:
        pass
    return driver


def wait_for_document_ready(driver, timeout):
    from src.emulator.compat import WebDriverWait

    WebDriverWait(driver, timeout).until(
        lambda active_driver: active_driver.execute_script("return document.readyState")
        == "complete"
    )


def click_first_matching(driver, xpaths, timeout):
    from src.emulator.compat import By, TimeoutException, WebDriverWait

    last_error = None
    for xpath in xpaths:
        try:
            elements = WebDriverWait(driver, timeout).until(
                lambda active_driver: [
                    element
                    for element in active_driver.find_elements(By.XPATH, xpath)
                    if element.is_displayed() and element.is_enabled()
                ]
            )
            element = elements[0]
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", element
            )
            driver.execute_script("arguments[0].click();", element)
            return
        except TimeoutException as exc:
            last_error = exc
    if last_error:
        raise last_error


def wait_for_csv_download(download_dir, existing_files, timeout):
    deadline = time.time() + timeout
    download_dir = Path(download_dir)
    while time.time() < deadline:
        partials = list(download_dir.glob("*.crdownload"))
        csv_files = [
            path
            for path in download_dir.glob("*.csv")
            if path.name not in existing_files and path.stat().st_size > 0
        ]
        if csv_files and not partials:
            return max(csv_files, key=lambda path: path.stat().st_mtime)
        time.sleep(0.5)
    raise RuntimeError("CSV download timed out")


def download_trends_csv_via_browser(
    geo=DEFAULT_GEO,
    hours=DEFAULT_HOURS,
    browser=DEFAULT_BROWSER,
    headless=True,
    timeout=DEFAULT_TIMEOUT,
):
    try:
        import nodriver  # type: ignore[import-not-found]  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "nodriver is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    from src.emulator.compat import TimeoutException

    with tempfile.TemporaryDirectory(prefix="trends-download-") as temp_dir:
        download_dir = Path(temp_dir)
        driver = build_trends_driver(
            browser, download_dir, headless=headless, timeout=timeout
        )
        try:
            driver.get(TRENDS_URL.format(geo=geo, hours=hours))
            wait_for_document_ready(driver, timeout)
            existing_files = {path.name for path in download_dir.iterdir()}

            export_xpaths = [
                "//*[self::button or @role='button' or self::a]"
                "[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'export')]",
                "//*[self::button or @role='button' or self::a]"
                "[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'download')]",
                "//*[self::button or @role='button' or self::a]"
                "[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'export')]",
                "//*[self::button or @role='button' or self::a]"
                "[.//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'file_download')]]",
            ]
            click_first_matching(driver, export_xpaths, min(timeout, 20))

            csv_xpaths = [
                "//*[self::button or @role='menuitem' or @role='option' or self::a]"
                "[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'csv')]",
                "//*[self::button or @role='menuitem' or @role='option' or self::a]"
                "[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz'), 'csv')]",
            ]
            try:
                click_first_matching(driver, csv_xpaths, 5)
            except TimeoutException:
                pass

            csv_path = wait_for_csv_download(download_dir, existing_files, timeout)
            return csv_path.read_text(encoding="utf-8-sig")
        finally:
            driver.quit()


def fetch_trend_rows(
    geo=DEFAULT_GEO,
    hours=DEFAULT_HOURS,
    browser=DEFAULT_BROWSER,
    headless=True,
    timeout=DEFAULT_TIMEOUT,
    browser_csv_downloader=None,
):
    if browser_csv_downloader is None:
        browser_csv_downloader = download_trends_csv_via_browser
    try:
        csv_text = browser_csv_downloader(
            geo=geo,
            hours=hours,
            browser=browser,
            headless=headless,
            timeout=timeout,
        )
    except Exception as exc:
        raise RuntimeError(f"browser CSV download failed: {exc}") from exc

    rows = parse_trends_csv(csv_text)
    if not rows:
        raise RuntimeError("browser CSV download returned no rows")
    return rows


def read_queries_file(path):
    with Path(path).open("r", encoding="utf-8") as file:
        data = json.load(file)
    queries = data.get("queries")
    if not isinstance(queries, list):
        raise ValueError(f"{path} must contain a top-level queries list")
    return [normalize_query(query) for query in queries if normalize_query(query)]


def atomic_write_queries(path, queries):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"queries": list(queries)}
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as temp_file:
        json.dump(payload, temp_file, indent=4)
        temp_file.write("\n")
        temp_path = Path(temp_file.name)
    temp_path.replace(path)


def ensure_base_file(queries_path, base_path):
    queries_path = Path(queries_path)
    base_path = Path(base_path)
    if base_path.exists():
        return False
    base_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(queries_path, base_path)
    return True


def update_queries_file(queries_path, base_path, trend_queries, mode="combine"):
    if mode not in {"combine", "replace"}:
        raise ValueError("mode must be combine or replace")

    normalized_trends = []
    for query in trend_queries:
        normalized_query = normalize_query(query)
        if is_clean_query(normalized_query):
            normalized_trends.append(normalized_query)
    trend_queries = dedupe_queries(normalized_trends)
    trend_queries = limit_trend_topic_repetition(trend_queries)
    if not trend_queries:
        raise ValueError("No clean trend queries found")

    created_base = ensure_base_file(queries_path, base_path)
    if mode == "replace":
        output = trend_queries
        added_count = len(trend_queries)
    else:
        current_queries = read_queries_file(queries_path)
        base_queries = read_queries_file(base_path)
        existing_keys = {
            query.casefold() for query in [*current_queries, *base_queries]
        }
        new_trends = [
            query for query in trend_queries if query.casefold() not in existing_keys
        ]
        output = [*new_trends, *current_queries, *base_queries]
        added_count = sum(
            1 for query in trend_queries if query.casefold() not in existing_keys
        )

    output = dedupe_queries(output)
    atomic_write_queries(queries_path, output)
    return UpdateResult(
        total_count=len(output),
        trend_count=len(trend_queries),
        added_count=added_count,
        created_base=created_base,
    )


def reset_queries_file(queries_path, base_path):
    base_queries = read_queries_file(base_path)
    atomic_write_queries(queries_path, base_queries)
    return len(base_queries)


def print_status(queries_path, base_path):
    current_count = len(read_queries_file(queries_path))
    if Path(base_path).exists():
        base_count = len(read_queries_file(base_path))
        print(f"Current queries: {current_count}")
        print(f"Base queries: {base_count}")
        return 0
    print(f"Current queries: {current_count}")
    print(f"Base queries: missing ({base_path})")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Refresh assets/queries.json from Google Trends."
    )
    subparsers = parser.add_subparsers(dest="command")

    update_parser = subparsers.add_parser(
        "update", help="Fetch trends and update queries.json."
    )
    update_parser.add_argument(
        "--mode", choices=("combine", "replace"), default="combine"
    )
    update_parser.add_argument(
        "--queries-file", type=Path, default=DEFAULT_QUERIES_FILE
    )
    update_parser.add_argument("--base-file", type=Path, default=DEFAULT_BASE_FILE)
    update_parser.add_argument("--geo", default=DEFAULT_GEO)
    update_parser.add_argument("--hours", type=int, default=DEFAULT_HOURS)
    update_parser.add_argument(
        "--browser", choices=("edge", "chrome"), default=DEFAULT_BROWSER
    )
    update_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    update_parser.add_argument(
        "--show-browser", action="store_true", help="Run browser visibly."
    )

    reset_parser = subparsers.add_parser(
        "reset", help="Restore queries.json from base file."
    )
    reset_parser.add_argument("--queries-file", type=Path, default=DEFAULT_QUERIES_FILE)
    reset_parser.add_argument("--base-file", type=Path, default=DEFAULT_BASE_FILE)

    status_parser = subparsers.add_parser(
        "status", help="Show current/base query counts."
    )
    status_parser.add_argument(
        "--queries-file", type=Path, default=DEFAULT_QUERIES_FILE
    )
    status_parser.add_argument("--base-file", type=Path, default=DEFAULT_BASE_FILE)
    return parser


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    else:
        argv = list(argv)
    if not argv or argv[0].startswith("-"):
        argv = ["update", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command

    try:
        if command == "update":
            rows = fetch_trend_rows(
                geo=args.geo,
                hours=args.hours,
                browser=args.browser,
                headless=not args.show_browser,
                timeout=args.timeout,
            )
            trend_queries = extract_queries_from_rows(rows)
            result = update_queries_file(
                args.queries_file, args.base_file, trend_queries, mode=args.mode
            )
            if result.created_base:
                print(f"Created base file: {args.base_file}")
            print(
                f"Updated {args.queries_file}: {result.total_count} queries "
                f"({result.trend_count} trends, {result.added_count} new)."
            )
            return 0
        if command == "reset":
            count = reset_queries_file(args.queries_file, args.base_file)
            print(
                f"Restored {args.queries_file} from {args.base_file}: "
                f"{count} queries."
            )
            return 0
        if command == "status":
            return print_status(args.queries_file, args.base_file)
        parser.error(f"unknown command: {command}")
        return 2
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
