import json
import os

from .config import APP_DIR, SETTINGS_FILE_PATH


class SettingsManager:
	def __init__(self):
		self.path = SETTINGS_FILE_PATH

	def get_settings(self):
		default_settings = {
			"first_setup_done": False,
			"hide_browser": False,
		}

		if APP_DIR and not os.path.exists(APP_DIR):
			os.makedirs(APP_DIR)

		if not os.path.exists(self.path):
			self.save_settings(default_settings)
			return default_settings

		try:
			with open(self.path, "r", encoding="utf-8") as file:
				settings = json.load(file)

				if not isinstance(settings, dict):
					raise ValueError("Settings file must contain a JSON object")

				return settings
		except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
			# Preserve the damaged file for inspection, then recreate defaults.
			backup_path = self.path + ".backup"

			if os.path.exists(backup_path):
				os.remove(backup_path)

			os.replace(self.path, backup_path)
			self.save_settings(default_settings)
			return default_settings

	def save_settings(self, settings):
		with open(self.path, "w", encoding="utf-8") as file:
			json.dump(settings, file, indent=4)

	def set_hide_browser(self, is_hide):
		settings = self.get_settings()
		settings["hide_browser"] = bool(is_hide)
		self.save_settings(settings)

	def mark_up_as_done(self):
		settings = self.get_settings()
		settings["first_setup_done"] = True
		self.save_settings(settings)
