import os
import json
from datetime import datetime

from .config import HISTORY_FILE_PATH, SETTINGS_FILE_PATH


class HistoryManager:
    """
    Manages the history of search queries.
    Date, time, query text, and status of each search are stored in a JSON file.
    """

    def __init__(self, logger=None):
        """
        Initialize the HistoryManager with file paths and an optional logger.

        Args:
            logger (callable, optional): A logging function to log messages. Defaults to None.
        """

        self.history_file = HISTORY_FILE_PATH
        self.settings_file = SETTINGS_FILE_PATH
        self._logger = logger

    def _log(self, message):
        """
        Log a message using the provided logger, if available.

        Args:
            message (str): The message to log.
        """

        if self._logger:
            self._logger(message)

    def get_history(self):
        """
        Retrieve the search history from the JSON file.

        Returns:
            list: A list of search records.
            Each record is a dictionary containing date, time, query, and status.
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

            # Keep the damaged history file as backup and start with a clean one.
            backup_path = self.history_file + ".backup"

            if os.path.exists(backup_path):
                os.remove(backup_path)

            os.replace(self.history_file, backup_path)

            with open(self.history_file, "w", encoding="utf-8") as file:
                json.dump([], file, indent=4)

            return []

    def save_history(self, history_list):
        """
        Save the search history to a JSON file. Uses a temporary file to avoid data loss.

        Args:
            history_list (list): A list of search records to be saved.
            Each record is a dictionary containing date, time, query, and status.
        """

        temp_file = self.history_file + ".tmp"

        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(history_list, file, indent=4)

        # Replace the original file with the updated one
        os.replace(temp_file, self.history_file)

    def add_to_history(self, query_text, status):
        """
        Add a search query to the history JSON file with the current date, time, query text, and status.

        Args:
            query_text (str): The text of the search query.
            status (str): The status of the search (e.g., "success", "failure"(error)).
        """

        now = datetime.now()
        current_date = now.strftime("%m-%d-%Y")
        current_time = now.strftime("%H:%M:%S")

        # Create a new record with date, time, query, and status
        new_record = {
            "date": current_date,
            "time": current_time,
            "query": query_text,
            "status": status,
        }

        history_list = self.get_history()

        history_list.append(new_record)

        self.save_history(history_list)
