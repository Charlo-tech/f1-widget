"""
F1 Widget - Main transparent overlay window.

Tuned for:
  - Windows (DWM compositing, taskbar-aware positioning, WS_EX_TOOLWINDOW)
  - Top-right corner default placement (respects taskbar)
  - Collapsed state: next-race countdown + last race winner card
  - Expanded state: full podium + race result standings (scrollable)
"""

import sys
import ctypes
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from track_window import RaceSimWindow

# ── Team colors ──────────────────────────────────────────────────────────────

TEAM_COLORS = {
    "red bull":     "#3671C6",
    "ferrari":      "#E8002D",
    "mercedes":     "#27F4D2",
    "mclaren":      "#FF8000",
    "aston martin": "#229971",
    "alpine":       "#FF87BC",
    "williams":     "#64C4FF",
    "haas":         "#B6BABD",
    " rb ":         "#6692FF",
    "sauber":       "#52E252",
}

MEDAL_COLORS = {1: "#FFD700", 2: "#C0C0C0", 3: "#CD7F32"}
POS_SUFFIX   = {1: "ST", 2: "ND", 3: "RD"}


def get_team_hex(team: str) -> str:
    low = (team or "").lower()
    for k, v in TEAM_COLORS.items():
        if k.strip() in low:
            return v.lstrip("#")
    return "555566"


def short_team(team: str) -> str:
    MAP = {
        "red bull": "RBR", "ferrari": "FER", "mercedes": "MER",
        "mclaren":  "MCL", "aston":   "AMR", "alpine":   "ALP",
        "williams": "WIL", "haas":    "HAA", "sauber":   "SAU",
    }
    low = (team or "").lower()
    for k, v in MAP.items():
        if k in low:
            return v
    return team[:3].upper() if team else "—"


# ── Helpers ───────────────────────────────────────────────────────────────────

class Sep(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet("background: rgba(255,255,255,0.07); border: none;")


def mlabel(text="", size=9, alpha=0.4, bold=False, spacing=2) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        color: rgba(255,255,255,{alpha});
        font-size: {size}px;
        font-weight: {'700' if bold else '500'};
        letter-spacing: {spacing}px;
        background: transparent;
    """)
    return lbl


# ── Main Widget ───────────────────────────────────────────────────────────────

class F1Widget(QWidget):
    """
    Two-state widget:
      Collapsed  → header + countdown + winner card        (~185 px)
      Expanded   → header + countdown + podium + standings (~590 px)
    """

    W           = 320
    COLLAPSED_H = 185
    EXPANDED_H  = 590

    def __init__(self, settings, data_manager):
        super().__init__()
        self.settings     = settings
        self.data_manager = data_manager
        self._drag_pos    = None
        self._collapsed   = settings.get("collapsed", False)
        self._data        = {}

        self._build_window()
        self._build_ui()
        self._apply_state(animate=False)
        self._place_top_right()

        # Race simulation window (hidden by default)
        self._track_win = RaceSimWindow(data_manager)

        self.data_manager.data_updated.connect(self._on_data)
        self.data_manager.status_changed.connect(self._on_status)

        # 1-second countdown tick
        t = QTimer(self); t.timeout.connect(self._tick_countdown); t.start(1000)

        # Pulsing dot
        self._pulse = True
        p = QTimer(self); p.timeout.connect(self._tick_pulse); p.start(900)

    # ── Window chrome ─────────────────────────────────────────────────────────

    def _build_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnBottomHint |
            Qt.WindowType.Tool |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFixedWidth(self.W)

        # Windows: remove from Alt+Tab via WS_EX_TOOLWINDOW
        if sys.platform == "win32":
            try:
                GWL_EXSTYLE      = -20
                WS_EX_TOOLWINDOW = 0x00000080
                hwnd  = int(self.winId())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW
                )
            except Exception:
                pass

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(0)

        self.card = QWidget()
        self.card.setObjectName("card")
        self.card.setStyleSheet("""
            QWidget#card {
                background: rgba(8, 8, 12, 0.91);
                border-radius: 13px;
                border: 1px solid rgba(255,255,255,0.075);
            }
        """)
        vl = QVBoxLayout(self.card)
        vl.setContentsMargins(14, 12, 14, 14)
        vl.setSpacing(0)

        # Always-visible header
        vl.addWidget(self._make_header())
        vl.addSpacing(10)

        # ── Always visible: countdown ──
        self.sec_countdown = self._make_countdown()
        vl.addWidget(self.sec_countdown)
        vl.addSpacing(8)

        # ── Always visible: winner card ──
        self.sec_winner = self._make_winner()
        vl.addWidget(self.sec_winner)

        # ── Expanded only ──
        self.sep1 = Sep()
        self.sec_podium = self._make_podium()
        self.sep2 = Sep()
        self.sec_standings = self._make_standings()

        for w in [self.sep1, self.sec_podium, self.sep2, self.sec_standings]:
            vl.addSpacing(8)
            vl.addWidget(w)

        # Status notice
        vl.addSpacing(4)
        self.status_lbl = mlabel("Fetching race data…", size=10, alpha=0.32)
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vl.addWidget(self.status_lbl)

        root.addWidget(self.card)

        self._expanded_only = [self.sep1, self.sec_podium, self.sep2, self.sec_standings]

    # ── Section builders ─────────────────────────────────────────────────────

    def _make_header(self) -> QWidget:
        w  = QWidget(); w.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(8)

        badge = QLabel("F1")
        badge.setStyleSheet("""
            background: #E8002D; color: white; font-weight: 900;
            font-size: 12px; border-radius: 4px;
            padding: 2px 6px; letter-spacing: 1.5px;
        """)
        badge.setFixedWidth(28)
        hl.addWidget(badge)

        title = QLabel("Race Centre")
        title.setStyleSheet("""
            color: rgba(255,255,255,0.88); font-size: 13px;
            font-weight: 700; letter-spacing: 0.4px; background: transparent;
        """)
        hl.addWidget(title); hl.addStretch()

        self.dot = QLabel("●")
        self.dot.setStyleSheet("color: #27F4D2; font-size: 9px; background: transparent;")
        hl.addWidget(self.dot)

        # Track simulation toggle button
        self.track_btn = QPushButton("⬡")
        self.track_btn.setFixedSize(22, 22)
        self.track_btn.setToolTip("Show / Hide Track Simulation")
        self.track_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.06); border: none;
                border-radius: 11px; color: rgba(255,255,255,0.45); font-size: 12px;
            }
            QPushButton:hover { background: rgba(39,244,210,0.18); color: #27F4D2; }
            QPushButton:checked { background: rgba(39,244,210,0.22); color: #27F4D2; }
        """)
        self.track_btn.setCheckable(True)
        self.track_btn.clicked.connect(self.toggle_track_window)
        hl.addWidget(self.track_btn)

        self.toggle_btn = QPushButton("▼" if not self._collapsed else "▲")
        self.toggle_btn.setFixedSize(22, 22)
        self.toggle_btn.setToolTip("Expand / Collapse")
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.06); border: none;
                border-radius: 11px; color: rgba(255,255,255,0.55); font-size: 10px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.13); color: white; }
        """)
        self.toggle_btn.clicked.connect(self.toggle_collapse)
        hl.addWidget(self.toggle_btn)
        w.setCursor(Qt.CursorShape.SizeAllCursor)
        return w

    def _make_countdown(self) -> QWidget:
        w  = QWidget(); w.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(w); vl.setContentsMargins(0, 0, 0, 0); vl.setSpacing(2)

        vl.addWidget(mlabel("NEXT RACE", bold=True, spacing=2))

        self.next_race_name = QLabel("—")
        self.next_race_name.setStyleSheet("""
            color: rgba(255,255,255,0.78); font-size: 12px;
            font-weight: 600; background: transparent;
        """)
        self.next_race_name.setWordWrap(True)
        vl.addWidget(self.next_race_name)

        self.countdown_lbl = QLabel("—")
        self.countdown_lbl.setStyleSheet("""
            color: #E8002D; font-size: 27px;
            font-weight: 900; letter-spacing: 1px; background: transparent;
        """)
        vl.addWidget(self.countdown_lbl)
        return w

    def _make_winner(self) -> QWidget:
        """Compact 'last race winner' card — visible in collapsed state."""
        w = QWidget(); w.setObjectName("wc")
        w.setStyleSheet("""
            QWidget#wc {
                background: rgba(255,255,255,0.04);
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.06);
            }
        """)
        vl = QVBoxLayout(w); vl.setContentsMargins(10, 8, 10, 8); vl.setSpacing(4)

        top = QHBoxLayout(); top.setSpacing(6)
        top.addWidget(mlabel("LAST RACE WINNER", bold=True, spacing=2))
        top.addStretch()
        self.last_race_loc = mlabel("—", size=9, alpha=0.28)
        top.addWidget(self.last_race_loc)
        vl.addLayout(top)

        row = QHBoxLayout(); row.setSpacing(8)
        trophy = QLabel("🏆"); trophy.setStyleSheet("font-size: 18px; background: transparent;")
        trophy.setFixedWidth(26); row.addWidget(trophy)

        self.winner_stripe = QLabel()
        self.winner_stripe.setFixedSize(3, 22)
        self.winner_stripe.setStyleSheet("background: #E8002D; border-radius: 1px;")
        row.addWidget(self.winner_stripe)

        col = QVBoxLayout(); col.setSpacing(1)
        self.winner_name = QLabel("—")
        self.winner_name.setStyleSheet("""
            color: rgba(255,255,255,0.95); font-size: 15px;
            font-weight: 800; background: transparent;
        """)
        col.addWidget(self.winner_name)
        self.winner_team = mlabel("—", size=10, alpha=0.42)
        col.addWidget(self.winner_team)
        row.addLayout(col, 1)
        vl.addLayout(row)
        return w

    def _make_podium(self) -> QWidget:
        w  = QWidget(); w.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(w); vl.setContentsMargins(0, 0, 0, 0); vl.setSpacing(5)
        vl.addWidget(mlabel("PODIUM", bold=True, spacing=2))
        self._podium_rows = []
        for _ in range(3):
            row = self._driver_row(podium=True)
            self._podium_rows.append(row)
            vl.addWidget(row["w"])
        return w

    def _make_standings(self) -> QWidget:
        w  = QWidget(); w.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(w); vl.setContentsMargins(0, 0, 0, 0); vl.setSpacing(5)
        vl.addWidget(mlabel("RACE RESULT", bold=True, spacing=2))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(205)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: rgba(255,255,255,0.03); width: 3px; border-radius: 1px; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.18); border-radius: 1px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._st_inner = QWidget(); self._st_inner.setStyleSheet("background: transparent;")
        self._st_vl    = QVBoxLayout(self._st_inner)
        self._st_vl.setContentsMargins(0, 0, 4, 0); self._st_vl.setSpacing(2)
        scroll.setWidget(self._st_inner)
        vl.addWidget(scroll)
        return w

    def _driver_row(self, podium=False) -> dict:
        rw = QWidget(); rw.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(rw); hl.setContentsMargins(0, 1, 0, 1); hl.setSpacing(7)

        pos = QLabel("—")
        pos.setFixedWidth(22)
        pos.setStyleSheet(f"""
            color: rgba(255,255,255,0.6); font-size: {'13px' if podium else '11px'};
            font-weight: {'800' if podium else '600'}; background: transparent;
        """)
        hl.addWidget(pos)

        stripe = QLabel(); stripe.setFixedSize(3, 18 if podium else 13)
        stripe.setStyleSheet("background: #555566; border-radius: 1px;")
        hl.addWidget(stripe)

        name = QLabel("—")
        name.setStyleSheet(f"""
            color: rgba(255,255,255,{'0.88' if podium else '0.68'}); 
            font-size: {'13px' if podium else '11px'};
            font-weight: {'700' if podium else '500'}; background: transparent;
        """)
        hl.addWidget(name, 1)

        team = QLabel(""); team.setStyleSheet("color: rgba(255,255,255,0.27); font-size: 10px; background: transparent;")
        hl.addWidget(team)

        pts = QLabel(""); pts.setStyleSheet("color: rgba(255,255,255,0.42); font-size: 10px; background: transparent;")
        hl.addWidget(pts)

        return {"w": rw, "pos": pos, "stripe": stripe, "name": name, "team": team, "pts": pts}

    # ── Collapse ──────────────────────────────────────────────────────────────

    def _apply_state(self, animate=True):
        show = not self._collapsed
        for w in self._expanded_only:
            w.setVisible(show)
        self.toggle_btn.setText("▲" if self._collapsed else "▼")
        self.setFixedHeight(self.COLLAPSED_H if self._collapsed else self.EXPANDED_H)

    def toggle_collapse(self):
        self._collapsed = not self._collapsed
        self._apply_state()
        self.settings.set("collapsed", self._collapsed)

    # ── Positioning ───────────────────────────────────────────────────────────

    def _place_top_right(self):
        cx = self.settings.get("custom_x")
        cy = self.settings.get("custom_y")
        if cx is not None and cy is not None:
            self.move(int(cx), int(cy)); return

        screen = self.screen().availableGeometry()   # respects Windows taskbar
        margin = self.settings.get("margin", 18)
        self.move(screen.right() - self.W - margin, screen.top() + margin)

    # ── Data slots ────────────────────────────────────────────────────────────

    @pyqtSlot(dict)
    def _on_data(self, data: dict):
        self._data = data
        if data.get("error"):
            self.status_lbl.setText(f"⚠  {data.get('hint', data['error'])}")
            self.status_lbl.show(); return
        self.status_lbl.hide()
        self._render(data)

    @pyqtSlot(str)
    def _on_status(self, s: str):
        msgs = {"loading": "Updating…", "error": "⚠  Using cached data"}
        if s in msgs:
            self.status_lbl.setText(msgs[s]); self.status_lbl.show()
        elif s == "ready":
            self.status_lbl.hide()

    def _render(self, data: dict):
        last    = data.get("last_race") or {}
        drivers = last.get("drivers") or []

        # Winner
        if drivers:
            d = drivers[0]
            hx = get_team_hex(d.get("team", ""))
            self.winner_name.setText(d.get("abbreviation") or d.get("full_name") or "—")
            self.winner_team.setText(f"{d.get('team', '—')}  ·  {last.get('name', '')}")
            self.winner_stripe.setStyleSheet(f"background: #{hx}; border-radius: 1px;")
        self.last_race_loc.setText(last.get("location") or "—")

        # Podium
        for i, row in enumerate(self._podium_rows):
            if i < len(drivers):
                d   = drivers[i]
                pos = d.get("position", i + 1)
                suf = POS_SUFFIX.get(pos, "TH")
                mc  = MEDAL_COLORS.get(pos, "rgba(255,255,255,0.6)")
                row["pos"].setText(f"{pos}{suf}")
                row["pos"].setStyleSheet(
                    f"color: {mc}; font-size: 13px; font-weight: 800; background: transparent;"
                )
                row["name"].setText(d.get("abbreviation") or "—")
                row["team"].setText(short_team(d.get("team", "")))
                row["pts"].setText(f"{int(d.get('points', 0))}pt")
                hx = get_team_hex(d.get("team", ""))
                row["stripe"].setStyleSheet(f"background: #{hx}; border-radius: 1px;")

        # Full standings
        while self._st_vl.count():
            item = self._st_vl.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        for d in drivers:
            row = self._driver_row(podium=False)
            row["pos"].setText(str(d.get("position", "—")))
            row["name"].setText(d.get("abbreviation") or "—")
            row["team"].setText(short_team(d.get("team", "")))
            row["pts"].setText(f"{int(d.get('points', 0))}pt")
            hx = get_team_hex(d.get("team", ""))
            row["stripe"].setStyleSheet(f"background: #{hx}; border-radius: 1px;")
            self._st_vl.addWidget(row["w"])

        self._tick_countdown()

    def _tick_countdown(self):
        nxt = self._data.get("next_race")
        if not nxt:
            self.countdown_lbl.setText("—"); return
        try:
            self.next_race_name.setText(
                f"{nxt.get('name', '?')}  ·  {nxt.get('location', '')}"
            )
            raw = str(nxt["date"]).replace(" 00:00:00", "").split("T")[0]
            race_dt = datetime.fromisoformat(raw)
            delta   = race_dt - datetime.now()
            if delta.total_seconds() < 0:
                self.countdown_lbl.setText("Race week! 🏁"); return
            d = delta.days; h, rem = divmod(delta.seconds, 3600); m, s = divmod(rem, 60)
            self.countdown_lbl.setText(
                f"{d}d  {h:02d}h  {m:02d}m" if d > 0 else f"{h:02d}:{m:02d}:{s:02d}"
            )
        except Exception:
            pass

    def _tick_pulse(self):
        self._pulse = not self._pulse
        c = "#27F4D2" if self._pulse else "rgba(39,244,210,0.22)"
        self.dot.setStyleSheet(f"color: {c}; font-size: 9px; background: transparent;")

    # ── Visibility / Drag ─────────────────────────────────────────────────────

    def toggle_track_window(self):
        """Show or hide the track simulation window, snapping it beside this widget."""
        if self._track_win.isVisible():
            self._track_win.hide()
            self.track_btn.setChecked(False)
        else:
            self._track_win.snap_to(self)
            self._track_win.show()
            self.track_btn.setChecked(True)

    def toggle_visibility(self):
        self.hide() if self.isVisible() else (self.show(), self.raise_())

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            p = e.globalPosition().toPoint() - self._drag_pos
            self.move(p)
            self.settings.set("custom_x", p.x())
            self.settings.set("custom_y", p.y())

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def paintEvent(self, e):
        pass
