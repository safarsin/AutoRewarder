import os
import json
from datetime import datetime


class HistoryManager:
    """
    Manages the history of search queries for a single account.
    Each instance is bound to a specific history.json file path.
    """

    def __init__(self, history_file, logger=None):
        """
        Args:
            history_file (str): Absolute path to this account's history.json.
            logger (callable, optional): Logging function.
        """

        self.history_file = history_file
        self._logger = logger

    def _log(self, message):
        if self._logger:
            self._logger(message)

    def get_history(self):
        """
        Retrieve the search history from the JSON file.
        Returns an empty list if the file is missing or unreadable.
        """

        if (
            not os.path.exists(self.history_file)
            or os.path.getsize(self.history_file) == 0
        ):
            return []

        try:
            with open(self.history_file, "r", encoding="utf-8") as file:
                history = json.load(file)

                if not isinstance(history, list):
                    raise ValueError("History data must be a list")

                return history
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            self._log(
                "[ERROR] History file was unreadable or damaged. Starting with a fresh one."
            )

            backup_path = self.history_file + ".backup"

            if os.path.exists(backup_path):
                os.remove(backup_path)

            os.replace(self.history_file, backup_path)

            with open(self.history_file, "w", encoding="utf-8") as file:
                json.dump([], file, indent=4)

            return []

    def save_history(self, history_list):
        """
        Save the search history to a JSON file atomically via a temp file.
        """

        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)

        temp_file = self.history_file + ".tmp"

        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(history_list, file, indent=4)

        os.replace(temp_file, self.history_file)

    def add_to_history(self, query_text, status):
        """
        Append a search record with the current date, time, query, and status.
        """

        now = datetime.now()
        current_date = now.strftime("%m-%d-%Y")
        current_time = now.strftime("%H:%M:%S")

        new_record = {
            "date": current_date,
            "time": current_time,
            "query": query_text,
            "status": status,
        }

        history_list = self.get_history()
        history_list.append(new_record)
        self.save_history(history_list)
