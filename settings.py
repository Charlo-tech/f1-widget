"""
Settings Manager - Persists user preferences to ~/.f1widget/config.json
"""

import json
import os
from pathlib import Path


DEFAULT_SETTINGS = {
    "position": "top-right",      # bottom-right | bottom-left | top-right | top-left
    "opacity": 0.92,
    "collapsed": False,           # False = expanded on first launch; user can collapse
    "custom_x": None,             # If user dragged to custom position
    "custom_y": None,
    "margin": 20,                 # px from screen edge
    "update_interval_hours": 36,  # How often to check for new race data
    "update_check_days": [0, 1],  # 0=Monday, 1=Tuesday (days after Sunday race)
    "autostart": False,
    "theme": "dark",              # dark | carbon
    "show_countdown": True,
    "show_standings": True,
    "show_mini_track": True,
    "max_drivers_shown": 10,
}


class Settings:
    def __init__(self):
        self.config_dir = Path.home() / ".f1widget"
        self.config_file = self.config_dir / "config.json"
        self._data = DEFAULT_SETTINGS.copy()
        self._load()

    def _load(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    saved = json.load(f)
                    self._data.update(saved)
            except Exception:
                pass  # Use defaults if config is corrupt

    def save(self):
        try:
            with open(self.config_file, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            print(f"[Settings] Failed to save: {e}")

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self.save()

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self.set(key, value)
