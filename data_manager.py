"""
Data Manager - Fetches F1 race data via FastF1 and schedules auto-updates.

Auto-update logic:
  - F1 races are typically on Sundays.
  - FastF1 data is usually available 24-48h later (Mon/Tue).
  - We check on Monday and Tuesday mornings and retry every 6h until data appears.
  - Once data is fetched for a round, we don't re-fetch unless forced.
"""

import os
import json
import threading
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".f1widget" / "data_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

STATUS_FILE = CACHE_DIR / "status.json"


class DataManager(QObject):
    """
    Manages F1 data fetching in a background thread.
    Emits signals when data is ready or updated.
    """

    data_updated = pyqtSignal(dict)
    status_changed = pyqtSignal(str)   # "loading" | "ready" | "error" | "offline"

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self._current_data = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Periodic refresh timer (runs on Qt main thread, triggers background fetch)
        self._check_timer = QTimer()
        self._check_timer.timeout.connect(self._maybe_fetch)

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self):
        """Start background fetch + schedule periodic checks."""
        # Initial fetch in background
        t = threading.Thread(target=self._fetch_all, daemon=True)
        t.start()

        # Check every 6 hours whether new race data is available
        interval_ms = 6 * 60 * 60 * 1000
        self._check_timer.start(interval_ms)

    def stop(self):
        self._stop_event.set()
        self._check_timer.stop()

    def force_refresh(self):
        """Triggered from system tray 'Force Refresh' action."""
        self.status_changed.emit("loading")
        t = threading.Thread(target=self._fetch_all, args=(True,), daemon=True)
        t.start()

    def get_current_data(self):
        with self._lock:
            return self._current_data.copy()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _maybe_fetch(self):
        """Called every 6h — only fetch if it's likely new data is available."""
        now = datetime.now()
        if now.weekday() in self.settings.get("update_check_days", [0, 1]):
            if not self._has_latest_round_cached():
                t = threading.Thread(target=self._fetch_all, daemon=True)
                t.start()

    def _has_latest_round_cached(self):
        """Check if we already have data for the most recent completed round."""
        if not STATUS_FILE.exists():
            return False
        try:
            with open(STATUS_FILE) as f:
                status = json.load(f)
            cached_round = status.get("last_fetched_round")
            cached_year = status.get("last_fetched_year")
            current_year = datetime.now().year
            return cached_year == current_year and cached_round is not None
        except Exception:
            return False

    def _fetch_all(self, force=False):
        """Main data fetch routine — runs in a background thread."""
        try:
            import fastf1
            fastf1_cache = CACHE_DIR / "fastf1"
            fastf1_cache.mkdir(parents=True, exist_ok=True)
            fastf1.Cache.enable_cache(str(fastf1_cache))

            self.status_changed.emit("loading")
            logger.info("[DataManager] Starting data fetch...")

            current_year = datetime.now().year

            # Get the event schedule to find the latest completed race
            schedule = fastf1.get_event_schedule(current_year, include_testing=False)
            now = datetime.now()

            # Find the most recently completed race
            completed = schedule[schedule["EventDate"] < str(now.date())]
            if completed.empty:
                # Try previous year if we're before first race
                schedule = fastf1.get_event_schedule(current_year - 1, include_testing=False)
                completed = schedule
                current_year -= 1

            if completed.empty:
                self.status_changed.emit("error")
                return

            latest_event = completed.iloc[-1]
            round_num = int(latest_event["RoundNumber"])
            year = current_year

            # Check status file to see if we already have this round (unless forced)
            if not force and STATUS_FILE.exists():
                try:
                    with open(STATUS_FILE) as f:
                        status = json.load(f)
                    if (status.get("last_fetched_year") == year and
                            status.get("last_fetched_round") == round_num):
                        logger.info("[DataManager] Data already cached for this round.")
                        # Just reload from cache
                        cached = self._load_from_cache(year, round_num)
                        if cached:
                            with self._lock:
                                self._current_data = cached
                            self.data_updated.emit(cached)
                            self.status_changed.emit("ready")
                            return
                except Exception:
                    pass

            # Fetch race session data
            logger.info(f"[DataManager] Fetching {year} Round {round_num}: {latest_event['EventName']}")
            session = fastf1.get_session(year, round_num, "R")
            session.load(telemetry=False, weather=False, messages=False)

            results = session.results

            # Build a clean summary dict
            drivers = []
            for _, row in results.iterrows():
                driver = {
                    "position": int(row.get("Position", 0)) if row.get("Position") else 0,
                    "driver_number": str(row.get("DriverNumber", "")),
                    "abbreviation": str(row.get("Abbreviation", "")),
                    "full_name": str(row.get("FullName", "")),
                    "team": str(row.get("TeamName", "")),
                    "team_color": str(row.get("TeamColor", "FFFFFF")),
                    "status": str(row.get("Status", "")),
                    "points": float(row.get("Points", 0.0)),
                    "grid_position": int(row.get("GridPosition", 0)) if row.get("GridPosition") else 0,
                    "time": str(row.get("Time", "")),
                }
                drivers.append(driver)

            drivers.sort(key=lambda d: d["position"] if d["position"] > 0 else 999)

            # Find next race
            upcoming = schedule[schedule["EventDate"] > str(now.date())]
            next_race = None
            if not upcoming.empty:
                nxt = upcoming.iloc[0]
                next_race = {
                    "name": str(nxt["EventName"]),
                    "date": str(nxt["EventDate"]),
                    "location": str(nxt.get("Location", "")),
                    "country": str(nxt.get("Country", "")),
                    "round": int(nxt["RoundNumber"]),
                }

            data = {
                "last_race": {
                    "year": year,
                    "round": round_num,
                    "name": str(latest_event["EventName"]),
                    "location": str(latest_event.get("Location", "")),
                    "country": str(latest_event.get("Country", "")),
                    "date": str(latest_event["EventDate"]),
                    "drivers": drivers,
                },
                "next_race": next_race,
                "fetched_at": datetime.now().isoformat(),
            }

            # Save to cache
            self._save_to_cache(data, year, round_num)

            with self._lock:
                self._current_data = data

            self.data_updated.emit(data)
            self.status_changed.emit("ready")
            logger.info("[DataManager] Data fetch complete.")

        except ImportError:
            # FastF1 not installed — emit error and show install hint
            logger.error("[DataManager] FastF1 not installed.")
            error_data = {
                "error": "FastF1 not installed",
                "hint": "Run: pip install fastf1",
                "last_race": None,
                "next_race": None,
            }
            with self._lock:
                self._current_data = error_data
            self.data_updated.emit(error_data)
            self.status_changed.emit("error")

        except Exception as e:
            logger.error(f"[DataManager] Fetch failed: {e}")
            # Try loading from cache as fallback
            cached = self._load_latest_from_cache()
            if cached:
                with self._lock:
                    self._current_data = cached
                self.data_updated.emit(cached)
                self.status_changed.emit("ready")
            else:
                self.status_changed.emit("error")

    def _save_to_cache(self, data, year, round_num):
        cache_file = CACHE_DIR / f"race_{year}_r{round_num}.json"
        with open(cache_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

        with open(STATUS_FILE, "w") as f:
            json.dump({
                "last_fetched_year": year,
                "last_fetched_round": round_num,
                "fetched_at": datetime.now().isoformat(),
            }, f)

    def _load_from_cache(self, year, round_num):
        cache_file = CACHE_DIR / f"race_{year}_r{round_num}.json"
        if cache_file.exists():
            with open(cache_file) as f:
                return json.load(f)
        return None

    def _load_latest_from_cache(self):
        """Load the most recent cache file available."""
        files = sorted(CACHE_DIR.glob("race_*.json"), key=os.path.getmtime, reverse=True)
        if files:
            with open(files[0]) as f:
                return json.load(f)
        return None
