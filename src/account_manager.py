"""
Account management for AutoRewarder.

Each account has its own isolated Edge profile, search history, daily-set
status, and metadata. The account index lives at APP_DIR/accounts.json and the
currently-selected account is tracked in global settings.
"""

import json
import os
import shutil
import uuid
from datetime import datetime

from .config import (
    ACCOUNTS_DIR,
    ACCOUNTS_INDEX_PATH,
    APP_DIR,
    LEGACY_EDGE_PROFILE_PATH,
    LEGACY_HISTORY_FILE_PATH,
    LEGACY_STATUS_FILE_PATH,
    account_dir,
    account_meta_path,
)


def _new_account_id():
    return uuid.uuid4().hex[:12]


class AccountManager:
    """
    CRUD + current-account tracking for accounts.

    Account index schema (accounts.json):
        [{"id": "<hex12>", "label": "Default", "created_at": "<ISO>"}]

    Per-account first_setup_done lives in meta.json (via AccountMetaManager).
    """

    def __init__(self, global_settings, logger=None):
        self._global = global_settings
        self._logger = logger
        os.makedirs(ACCOUNTS_DIR, exist_ok=True)

    def _log(self, msg):
        if self._logger:
            self._logger(msg)

    # ---- Index I/O ----------------------------------------------------

    def _read_index(self):
        if not os.path.exists(ACCOUNTS_INDEX_PATH):
            return []
        try:
            with open(ACCOUNTS_INDEX_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return []

    def _write_index(self, accounts):
        os.makedirs(APP_DIR, exist_ok=True)
        tmp = ACCOUNTS_INDEX_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=4)
        os.replace(tmp, ACCOUNTS_INDEX_PATH)

    # ---- Queries ------------------------------------------------------

    def list(self):
        current = self.current_id()
        accounts = self._read_index()
        result = []
        for acc in accounts:
            aid = acc.get("id")
            if not aid:
                continue
            result.append(
                {
                    "id": aid,
                    "label": acc.get("label") or "Account",
                    "first_setup_done": self._is_first_setup_done(aid),
                    "is_current": aid == current,
                    "created_at": acc.get("created_at"),
                }
            )
        return result

    def get(self, account_id):
        for acc in self._read_index():
            if acc.get("id") == account_id:
                return {
                    "id": account_id,
                    "label": acc.get("label") or "Account",
                    "first_setup_done": self._is_first_setup_done(account_id),
                    "is_current": account_id == self.current_id(),
                    "created_at": acc.get("created_at"),
                }
        return None

    def current_id(self):
        return self._global.get_current_account_id()

    def get_current(self):
        aid = self.current_id()
        return self.get(aid) if aid else None

    def exists(self, account_id):
        return any(acc.get("id") == account_id for acc in self._read_index())

    def _is_first_setup_done(self, account_id):
        meta_path = account_meta_path(account_id)
        if not os.path.exists(meta_path):
            return False
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return bool(isinstance(data, dict) and data.get("first_setup_done"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return False

    # ---- Mutations ----------------------------------------------------

    def create(self, label):
        """Create a new account directory and index entry. Does NOT select it."""
        label = (label or "").strip() or "Account"
        aid = _new_account_id()
        # Vanishingly unlikely collision, but defensive.
        while self.exists(aid):
            aid = _new_account_id()

        os.makedirs(account_dir(aid), exist_ok=True)

        accounts = self._read_index()
        accounts.append(
            {
                "id": aid,
                "label": label,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        self._write_index(accounts)
        self._log(f"Created account '{label}' ({aid})")
        return {"id": aid, "label": label, "first_setup_done": False}

    def select(self, account_id):
        if account_id is not None and not self.exists(account_id):
            raise ValueError(f"Account not found: {account_id}")
        self._global.set_current_account_id(account_id)

    def rename(self, account_id, new_label):
        new_label = (new_label or "").strip()
        if not new_label:
            raise ValueError("Label must not be empty")
        accounts = self._read_index()
        found = False
        for acc in accounts:
            if acc.get("id") == account_id:
                acc["label"] = new_label
                found = True
                break
        if not found:
            raise ValueError(f"Account not found: {account_id}")
        self._write_index(accounts)
        self._log(f"Renamed account {account_id} to '{new_label}'")

    def delete(self, account_id):
        """Remove the account directory and index entry. Returns the next account_id
        that should become current (first remaining) or None."""
        if not self.exists(account_id):
            raise ValueError(f"Account not found: {account_id}")

        accounts = [acc for acc in self._read_index() if acc.get("id") != account_id]
        self._write_index(accounts)

        target_dir = account_dir(account_id)
        if os.path.exists(target_dir):
            try:
                shutil.rmtree(target_dir)
            except OSError as e:
                self._log(f"[WARNING] Could not fully remove {target_dir}: {e}")

        self._log(f"Deleted account {account_id}")

        if self.current_id() == account_id:
            next_id = accounts[0]["id"] if accounts else None
            self._global.set_current_account_id(next_id)
            return next_id
        return self.current_id()

    # ---- Migration ----------------------------------------------------

    def migrate_legacy(self):
        """
        One-shot migration: if no accounts.json exists and the old single-profile
        files are present at APP_DIR root, move them into a new 'Default' account.

        Returns the new account id (if migration occurred), or None.
        """
        if os.path.exists(ACCOUNTS_INDEX_PATH):
            return None

        has_legacy = any(
            os.path.exists(p)
            for p in (
                LEGACY_EDGE_PROFILE_PATH,
                LEGACY_HISTORY_FILE_PATH,
                LEGACY_STATUS_FILE_PATH,
            )
        )

        if not has_legacy:
            # Fresh install: create an empty index and stop.
            self._write_index([])
            return None

        aid = _new_account_id()
        target = account_dir(aid)

        try:
            os.makedirs(target, exist_ok=True)

            if os.path.exists(LEGACY_EDGE_PROFILE_PATH):
                shutil.move(
                    LEGACY_EDGE_PROFILE_PATH, os.path.join(target, "EdgeProfile")
                )
            if os.path.exists(LEGACY_HISTORY_FILE_PATH):
                shutil.move(
                    LEGACY_HISTORY_FILE_PATH, os.path.join(target, "history.json")
                )
            if os.path.exists(LEGACY_STATUS_FILE_PATH):
                shutil.move(
                    LEGACY_STATUS_FILE_PATH, os.path.join(target, "status.json")
                )

            # Lift legacy "first_setup_done" into the new per-account meta.json.
            legacy_settings_path = os.path.join(APP_DIR, "settings.json")
            legacy_first_setup_done = False
            legacy_settings = None
            if os.path.exists(legacy_settings_path):
                try:
                    with open(legacy_settings_path, "r", encoding="utf-8") as f:
                        legacy_settings = json.load(f)
                    if isinstance(legacy_settings, dict):
                        legacy_first_setup_done = bool(
                            legacy_settings.get("first_setup_done")
                        )
                except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                    legacy_settings = None

            # Write per-account meta.json.
            meta_path = account_meta_path(aid)
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"first_setup_done": legacy_first_setup_done}, f, indent=4
                )

            # Strip the legacy key from global settings and persist
            # (preserve hide_browser which still lives at the global layer).
            if isinstance(legacy_settings, dict):
                hide_browser = bool(legacy_settings.get("hide_browser", False))
                self._global.set_hide_browser(hide_browser)
                stripped = {**self._global.get_settings()}
                stripped.pop("first_setup_done", None)
                self._global.save_settings(stripped)

            self._write_index(
                [
                    {
                        "id": aid,
                        "label": "Default",
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                    }
                ]
            )
            self._global.set_current_account_id(aid)

            self._log("Migrated legacy single-account files into 'Default' account.")
            return aid

        except OSError as e:
            self._log(f"[ERROR] Legacy migration failed: {e}")
            # Best-effort rollback: remove the partially-created account dir.
            try:
                if os.path.exists(target):
                    shutil.rmtree(target)
            except OSError:
                pass
            # Do not write accounts.json on failure so migration can retry next launch.
            return None
