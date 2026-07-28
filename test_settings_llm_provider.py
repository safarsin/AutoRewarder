import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


def load_llm_module(root):
    sys.modules["src"] = types.ModuleType("src")
    sys.modules["src.search"] = types.ModuleType("src.search")

    locale = types.ModuleType("src.search.locale")
    locale.language_name = lambda loc: "English"
    sys.modules["src.search.locale"] = locale

    requests = types.ModuleType("requests")

    class RequestException(Exception):
        pass

    requests.RequestException = RequestException
    requests.post = None
    sys.modules["requests"] = requests

    spec = importlib.util.spec_from_file_location(
        "src.search.llm", root / "src" / "search" / "llm.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["src.search.llm"] = module
    spec.loader.exec_module(module)
    return module


def load_settings_module(settings_path):
    root = Path(__file__).resolve().parent
    load_llm_module(root)

    accounts = types.ModuleType("src.accounts")
    sys.modules["src.accounts"] = accounts

    config = types.ModuleType("src.config")
    config.APP_DIR = str(settings_path.parent)
    config.GLOBAL_SETTINGS_PATH = str(settings_path)
    sys.modules["src.config"] = config

    spec = importlib.util.spec_from_file_location(
        "src.accounts.settings", root / "src" / "accounts" / "settings.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["src.accounts.settings"] = module
    spec.loader.exec_module(module)
    return module


class SettingsLlmProviderTests(unittest.TestCase):
    def test_legacy_9router_loads_as_openrouter(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                '{"llm_provider": "9router", "llm_api_key": "key"}',
                encoding="utf-8",
            )

            settings_module = load_settings_module(settings_path)
            manager = settings_module.GlobalSettingsManager()

            cfg = manager.get_llm_config()

        self.assertEqual(cfg["llm_provider"], "openrouter")
        self.assertEqual(cfg["llm_api_key"], "key")

    def test_legacy_9router_saves_as_openrouter(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"

            settings_module = load_settings_module(settings_path)
            manager = settings_module.GlobalSettingsManager()

            manager.set_llm_config(True, "9router", "", "key", "auto")
            cfg = manager.get_llm_config()

        self.assertEqual(cfg["llm_provider"], "openrouter")


if __name__ == "__main__":
    unittest.main()
