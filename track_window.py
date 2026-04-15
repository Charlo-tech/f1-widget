"""
RaceSimWindow — Full F1 race replay simulation window.

Layout mirrors the f1-race-replay app screenshot:
  LEFT    — selected driver telemetry panels (speed, gear, DRS, gaps)
  CENTRE  — track map with animated driver dots
  RIGHT   — live leaderboard
  BOTTOM  — lap counter, playback controls, progress bar
  TOP-LEFT — race info + weather
"""

import sys
import math
import ctypes
import threading
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QSizePolicy,
    QSlider, QApplication,
)
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSlot, QSize
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath,
    QFont, QFontMetrics, QLinearGradient,
)

# ── Team colors ───────────────────────────────────────────────────────────────
TEAM_COLORS = {
    "red bull":     "#3671C6",
    "ferrari":      "#E8002D",
    "mercedes":     "#27F4D2",
    "mclaren":      "#FF8000",
    "aston martin": "#229971",
    "alpine":       "#FF87BC",
    "williams":     "#64C4FF",
    "haas":         "#B6BABD",
    "rb f1":        "#6692FF",
    "visa":         "#6692FF",
    "sauber":       "#52E252",
    "kick":         "#52E252",
}

MEDAL = {1: "#FFD700", 2: "#C0C0C0", 3: "#CD7F32"}

def tcolor(team: str) -> QColor:
    low = (team or "").lower()
    for k, v in TEAM_COLORS.items():
        if k in low:
            return QColor(v)
    return QColor("#888899")


def tcolor_hex(team: str) -> str:
    return tcolor(team).name()


def short_team(team: str) -> str:
    M = {"red bull":"RBR","ferrari":"FER","mercedes":"MER","mclaren":"MCL",
         "aston":"AMR","alpine":"ALP","williams":"WIL","haas":"HAA","sauber":"SAU"}
    low = (team or "").lower()
    for k, v in M.items():
        if k in low: return v
    return (team or "")[:3].upper()


# ── Helpers ───────────────────────────────────────────────────────────────────

BG      = QColor(10, 10, 14)
CARD_BG = QColor(18, 18, 24)
SEP_CLR = QColor(40, 40, 55)
TXT     = QColor(220, 220, 230)
DIM     = QColor(120, 120, 140)
RED     = QColor(232, 0, 45)
TEAL    = QColor(39, 244, 210)


def hline() -> QFrame:
    f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1); f.setStyleSheet(f"background:{SEP_CLR.name()};border:none;")
    return f

def vline() -> QFrame:
    f = QFrame(); f.setFrameShape(QFrame.Shape.VLine)
    f.setFixedWidth(1); f.setStyleSheet(f"background:{SEP_CLR.name()};border:none;")
    return f

def lbl(text="", color="#DCDCE6", size=11, bold=False, align=Qt.AlignmentFlag.AlignLeft) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color:{color};font-size:{size}px;font-weight:{'700' if bold else '400'};background:transparent;")
    l.setAlignment(align)
    return l


# ── Track Canvas ─────────────────────────────────────────────────────────────

def _ellipse_circuit(steps=300) -> list[tuple[float,float]]:
    """Stylised fallback F1 circuit silhouette."""
    pts = []
    for i in range(steps):
        t = 2*math.pi*i/steps
        x = (0.36*math.cos(t) + 0.055*math.cos(3*t) + 0.03*math.cos(5*t))
        y = (0.28*math.sin(t) - 0.045*math.sin(2*t) + 0.025*math.sin(4*t))
        pts.append((x+0.5, y+0.5))
    return pts


class TrackCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(500, 420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        self._pts: list[tuple[float,float]] = _ellipse_circuit()
        self._cum: list[float] = []
        self._total: float = 1.0
        self._build_cum()

        self._drivers:  list[dict] = []
        self._selected: set[str]   = set()
        self._race_name = ""
        self._using_real = False

        # DRS zones: list of (start_prog, end_prog)
        self._drs_zones: list[tuple[float,float]] = []
        self._show_drs = True

    def _build_cum(self):
        pts = self._pts; cum = [0.0]
        for i in range(1, len(pts)):
            dx = pts[i][0]-pts[i-1][0]; dy = pts[i][1]-pts[i-1][1]
            cum.append(cum[-1]+math.hypot(dx,dy))
        self._cum = cum; self._total = cum[-1] or 1.0

    def set_track(self, xs, ys):
        if not xs: return
        mn_x,mx_x = min(xs),max(xs); mn_y,mx_y = min(ys),max(ys)
        r = max(mx_x-mn_x, mx_y-mn_y, 1); pad = 0.10
        self._pts = [(pad+(1-2*pad)*(x-mn_x)/r, pad+(1-2*pad)*(y-mn_y)/r)
                     for x,y in zip(xs,ys)]
        self._build_cum(); self._using_real = True; self.update()

    def set_drivers(self, drivers):
        self._drivers = drivers; self.update()

    def set_selected(self, abbrs: set): self._selected = abbrs; self.update()

    def set_drs_zones(self, zones): self._drs_zones = zones

    def set_race_name(self, name): self._race_name = name

    def _pt_at(self, prog: float) -> QPointF:
        target = (prog % 1.0)*self._total
        cum = self._cum; pts = self._pts
        lo,hi = 0, len(cum)-2
        while lo < hi:
            mid=(lo+hi)//2
            if cum[mid+1] < target: lo=mid+1
            else: hi=mid
        sl = cum[lo+1]-cum[lo]; t = (target-cum[lo])/sl if sl else 0
        x0,y0=pts[lo]; x1,y1=pts[(lo+1)%len(pts)]
        w,h = self.width(),self.height()
        return QPointF((x0+t*(x1-x0))*w, (y0+t*(y1-y0))*h)

    def _track_path(self) -> QPainterPath:
        path = QPainterPath(); w,h = self.width(),self.height()
        p0 = self._pts[0]; path.moveTo(p0[0]*w, p0[1]*h)
        for x,y in self._pts[1:]: path.lineTo(x*w, y*h)
        path.closeSubpath(); return path

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w,h = self.width(), self.height()

        # Background
        p.fillRect(0,0,w,h, BG)

        path = self._track_path()

        # DRS zones (bright green overlay on track)
        if self._show_drs and self._drs_zones:
            drs_pen = QPen(QColor("#00FF00"), 6)
            drs_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            for (s, e) in self._drs_zones:
                dz = QPainterPath(); first = True
                steps = 30
                for i in range(steps+1):
                    prog = s + (e-s)*i/steps
                    pt = self._pt_at(prog)
                    if first: dz.moveTo(pt); first = False
                    else: dz.lineTo(pt)
                p.strokePath(dz, drs_pen)

        # Track shadow
        p.strokePath(path, QPen(QColor(232,0,45,18), 24))
        # Track surface
        surf = QPen(QColor(45,45,58), 16)
        surf.setCapStyle(Qt.PenCapStyle.RoundCap)
        surf.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.strokePath(path, surf)
        # White edge lines
        p.strokePath(path, QPen(QColor(90,90,110), 18))
        p.strokePath(path, QPen(QColor(45,45,58), 14))
        # Centre dash
        dash_pen = QPen(QColor(255,255,255,30), 1, Qt.PenStyle.DashLine)
        p.strokePath(path, dash_pen)

        # Start/finish line
        sf  = self._pt_at(0.0)
        sf2 = self._pt_at(0.006)
        ang = math.atan2(sf2.y()-sf.y(), sf2.x()-sf.x()) + math.pi/2
        dx,dy = math.cos(ang)*12, math.sin(ang)*12
        sf_pen = QPen(QColor(255,255,255,220), 3)
        p.setPen(sf_pen)
        p.drawLine(int(sf.x()-dx),int(sf.y()-dy),int(sf.x()+dx),int(sf.y()+dy))

        # Driver dots — sort so leaders render on top
        sorted_d = sorted(self._drivers, key=lambda d: d.get("pos",20), reverse=True)
        for d in sorted_d:
            pt     = self._pt_at(d["progress"])
            color  = d["color"]
            pos    = d.get("pos", 20)
            sel    = d["abbr"] in self._selected
            radius = 7.0 if pos <= 3 else (6.0 if sel else 5.0)

            # Glow for selected or podium
            if sel or pos <= 3:
                glow = QColor(color); glow.setAlpha(55 if sel else 40)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(glow)
                p.drawEllipse(pt, radius+5, radius+5)

            p.setPen(QPen(QColor(0,0,0,120), 1))
            p.setBrush(QBrush(color))
            p.drawEllipse(pt, radius, radius)

            # Abbreviation
            lc = QColor(255,255,255, 230 if (sel or pos<=3) else 160)
            p.setPen(lc)
            f = QFont("Consolas", 7 if pos<=3 else 6)
            f.setBold(pos<=3 or sel)
            p.setFont(f)
            p.drawText(QRectF(pt.x()+radius+2, pt.y()-7, 34,14),
                       Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,
                       d["abbr"])

        # Race name watermark
        if self._race_name:
            p.setPen(QColor(255,255,255,22))
            p.setFont(QFont("Arial",9))
            p.drawText(QRectF(10,h-22,w-20,18),
                       Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,
                       self._race_name)

        # Badge
        badge_c = TEAL if self._using_real else RED
        badge_t = "TELEMETRY" if self._using_real else "SIMULATION"
        p.setPen(Qt.PenStyle.NoPen)
        bc = QColor(badge_c); bc.setAlpha(190)
        p.setBrush(bc)
        p.drawRoundedRect(10,10,88,16,4,4)
        p.setPen(QColor(255,255,255,230))
        bf = QFont("Arial",7); bf.setBold(True); p.setFont(bf)
        p.drawText(QRectF(10,10,88,16), Qt.AlignmentFlag.AlignCenter, badge_t)

        p.end()

    # Signal emitted when selection changes — connected by RaceSimWindow
    selection_changed = None   # set to a callable after construction

    def mousePressEvent(self, e):
        """Click a driver dot to select/deselect."""
        click = QPointF(e.position())
        for d in self._drivers:
            pt = self._pt_at(d["progress"])
            if math.hypot(click.x()-pt.x(), click.y()-pt.y()) < 12:
                abbr = d["abbr"]
                if abbr in self._selected:
                    self._selected.discard(abbr)
                else:
                    if not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                        self._selected.clear()
                    self._selected.add(abbr)
                self.update()
                # Notify parent via callback (avoids fragile parent chain)
                if callable(self.selection_changed):
                    self.selection_changed(self._selected)
                break


# ── Telemetry panel ───────────────────────────────────────────────────────────

class TelemetryPanel(QWidget):
    """Shows speed, gear, DRS, gap ahead/behind for one driver."""
    def __init__(self):
        super().__init__()
        self.setFixedWidth(210)
        self.setStyleSheet(f"background:{CARD_BG.name()};border-radius:6px;")
        vl = QVBoxLayout(self); vl.setContentsMargins(10,8,10,8); vl.setSpacing(4)

        self.header = QLabel("Driver: —")
        self.header.setStyleSheet(
            "background:#888;color:white;font-weight:800;font-size:12px;"
            "border-radius:4px;padding:2px 6px;")
        vl.addWidget(self.header)

        self.speed_lbl  = lbl("Speed: —", size=11)
        self.gear_lbl   = lbl("Gear: —", size=11)
        self.drs_lbl    = lbl("DRS: —", size=11)
        self.ahead_lbl  = lbl("Ahead: N/A", size=10, color=DIM.name())
        self.behind_lbl = lbl("Behind: N/A", size=10, color=DIM.name())

        for w in [self.speed_lbl, self.gear_lbl, self.drs_lbl,
                  self.ahead_lbl, self.behind_lbl]:
            vl.addWidget(w)

        # THR / BRK bars
        bars = QHBoxLayout(); bars.setSpacing(6)
        self.thr_bar = self._bar(QColor("#22C55E"))
        self.brk_bar = self._bar(QColor("#EF4444"))
        bars.addStretch()
        bars.addWidget(self._bar_col("THR", self.thr_bar))
        bars.addWidget(self._bar_col("BRK", self.brk_bar))
        vl.addLayout(bars)

    def _bar_col(self, label, bar):
        w = QWidget(); w.setStyleSheet("background:transparent;")
        vl = QVBoxLayout(w); vl.setContentsMargins(0,0,0,0); vl.setSpacing(2)
        vl.addWidget(bar, 1)
        l = QLabel(label); l.setStyleSheet(f"color:{DIM.name()};font-size:8px;background:transparent;")
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vl.addWidget(l)
        return w

    def _bar(self, color: QColor) -> QWidget:
        bar = QWidget()
        bar.setFixedWidth(18)
        bar.setMinimumHeight(40)
        bar.setMaximumHeight(60)
        bar.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:1,x2:0,y2:0,
              stop:0 {color.name()}, stop:1 {color.lighter(130).name()});
            border-radius:3px;
        """)
        return bar

    def update_driver(self, d: dict, drivers: list[dict]):
        abbr  = d.get("abbr","?")
        team  = d.get("team","")
        color = tcolor_hex(team)
        pos   = d.get("pos",20)
        speed = d.get("speed", int(250 + 50*math.sin(d.get("progress",0)*47)))
        gear  = d.get("gear",  int(5 + 3*math.sin(d.get("progress",0)*31)) % 8 + 1)
        drs   = "ON" if d.get("drs", False) else "OFF"

        self.header.setText(f"Driver: {abbr}")
        self.header.setStyleSheet(
            f"background:{color};color:white;font-weight:800;font-size:12px;"
            f"border-radius:4px;padding:2px 6px;")
        self.speed_lbl.setText(f"Speed: {speed} km/h")
        self.gear_lbl.setText(f"Gear: {gear}")
        drs_color = "#22C55E" if drs=="ON" else DIM.name()
        self.drs_lbl.setStyleSheet(f"color:{drs_color};font-size:11px;background:transparent;")
        self.drs_lbl.setText(f"DRS: {drs}")

        # Gaps
        sorted_d = sorted(drivers, key=lambda x: x.get("progress",0), reverse=True)
        idx = next((i for i,x in enumerate(sorted_d) if x["abbr"]==abbr), -1)
        if idx > 0:
            ahead = sorted_d[idx-1]
            gap   = abs(ahead["progress"]-d["progress"])*300
            self.ahead_lbl.setText(f"Ahead ({ahead['abbr']}): +{gap:.2f}s")
        else:
            self.ahead_lbl.setText("Ahead: Leader")
        if idx < len(sorted_d)-1:
            behind = sorted_d[idx+1]
            gap    = abs(d["progress"]-behind["progress"])*300
            self.behind_lbl.setText(f"Behind ({behind['abbr']}): -{gap:.2f}s")
        else:
            self.behind_lbl.setText("Behind: —")

        # Animate bars based on speed
        thr = max(0, min(60, int((speed-80)/2.2)))
        brk = max(0, min(60, int((300-speed)/3.5)))
        self.thr_bar.setMinimumHeight(thr); self.thr_bar.setMaximumHeight(thr+1)
        self.brk_bar.setMinimumHeight(brk); self.brk_bar.setMaximumHeight(brk+1)


# ── Leaderboard ───────────────────────────────────────────────────────────────

class Leaderboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedWidth(180)
        self.setStyleSheet("background:transparent;")
        vl = QVBoxLayout(self); vl.setContentsMargins(0,0,0,0); vl.setSpacing(2)

        title = QLabel("Leaderboard")
        title.setStyleSheet(
            "color:white;font-size:14px;font-weight:800;background:transparent;padding:4px 0;")
        vl.addWidget(title)

        self._rows: list[QLabel] = []
        for _ in range(20):
            row = QLabel("—")
            row.setStyleSheet(
                "color:rgba(200,200,210,0.7);font-size:11px;"
                "font-family:Consolas;background:transparent;padding:1px 4px;")
            row.setFixedHeight(20)
            vl.addWidget(row)
            self._rows.append(row)
        vl.addStretch()

    def update_standings(self, drivers: list[dict], selected: set[str]):
        sorted_d = sorted(drivers, key=lambda d: d.get("progress",0), reverse=True)
        for i, row in enumerate(self._rows):
            if i < len(sorted_d):
                d    = sorted_d[i]
                abbr = d["abbr"]
                pos  = i+1
                out  = d.get("status","") in ("Retired","DNF","OUT","out")
                col  = tcolor_hex(d.get("team",""))
                sel  = abbr in selected
                bg   = "rgba(255,255,255,0.10)" if sel else ("rgba(255,255,255,0.04)" if i%2==0 else "transparent")
                txt  = f"{pos:2d}. {abbr}"
                out_txt = "  OUT" if out else ""
                row.setText(txt + out_txt)
                row.setStyleSheet(f"""
                    color:{col}; font-size:11px; font-family:Consolas;
                    background:{bg}; padding:1px 4px; border-radius:3px;
                    font-weight:{'800' if sel or pos<=3 else '500'};
                """)
                row.setToolTip(d.get("team",""))
            else:
                row.setText(""); row.setStyleSheet("background:transparent;")


# ── Progress Bar ──────────────────────────────────────────────────────────────

class ProgressBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(28)
        self._progress = 0.0
        self._drivers: list[dict] = []
        self._total_laps = 50

    def set_state(self, progress, drivers, total_laps):
        self._progress = progress
        self._drivers  = drivers
        self._total_laps = max(total_laps, 1)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w,h = self.width(), self.height()

        # Track background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(30,30,42))
        p.drawRoundedRect(0, h//2-6, w, 12, 6, 6)

        # Progress fill (green)
        fill_w = int(w * self._progress)
        p.setBrush(QColor("#22C55E"))
        p.drawRoundedRect(0, h//2-6, fill_w, 12, 6, 6)

        # Driver dots on bar
        for d in self._drivers:
            bar_x = int(d.get("progress",0) * w)
            color  = d["color"]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(bar_x-4, h//2-4, 8, 8)

        # Lap markers
        p.setPen(QPen(QColor(255,255,255,40), 1))
        for i in range(1, self._total_laps):
            x = int(w * i / self._total_laps)
            p.drawLine(x, h//2-7, x, h//2+7)

        p.end()


# ── Race Info Bar ─────────────────────────────────────────────────────────────

class RaceInfoBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(80)
        self.setStyleSheet("background:transparent;")
        vl = QVBoxLayout(self); vl.setContentsMargins(0,0,0,0); vl.setSpacing(2)

        self.lap_lbl  = QLabel("Lap: —/—")
        self.lap_lbl.setStyleSheet("color:white;font-size:16px;font-weight:800;background:transparent;")
        self.time_lbl = QLabel("Race Time: —")
        self.time_lbl.setStyleSheet("color:rgba(200,200,210,0.8);font-size:12px;background:transparent;")

        vl.addWidget(self.lap_lbl)
        vl.addWidget(self.time_lbl)

        # Weather row
        self.weather_lbl = QLabel("Track: —  Air: —  💧 —  🌬 —")
        self.weather_lbl.setStyleSheet("color:rgba(180,180,200,0.65);font-size:10px;background:transparent;")
        vl.addWidget(self.weather_lbl)

    def update(self, lap, total_laps, elapsed_secs, speed_mult, weather=None):
        self.lap_lbl.setText(f"Lap: {lap}/{total_laps}")
        h,rem = divmod(int(elapsed_secs),3600); m,s = divmod(rem,60)
        self.time_lbl.setText(f"Race Time: {h:02d}:{m:02d}:{s:02d} (x{speed_mult:.1f})")
        if weather:
            self.weather_lbl.setText(
                f"Track: {weather.get('track_temp','—')}°C  "
                f"Air: {weather.get('air_temp','—')}°C  "
                f"💧 {weather.get('humidity','—')}%  "
                f"🌬 {weather.get('wind','—')} km/h  "
                f"Rain: {'YES' if weather.get('raining') else 'DRY'}"
            )


# ── Main Race Simulation Window ───────────────────────────────────────────────

class RaceSimWindow(QWidget):
    W = 860
    H = 580

    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self._drag_pos    = None
        self._drivers:    list[dict] = []
        self._selected:   set[str]   = set()
        self._race_name   = ""
        self._total_laps  = 50
        self._current_lap = 1
        self._elapsed     = 0.0
        self._speed_mult  = 1.0
        self._playing     = False
        self._progress    = 0.0   # 0..1 overall race progress
        self._weather     = {}
        self._year        = None
        self._round       = None

        self._build_window()
        self._build_ui()

        # Animation timer — 33ms ≈ 30fps
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._step)
        self._anim.start(33)

        # Elapsed time counter (1s ticks)
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start(1000)

        # Load data
        self.data_manager.data_updated.connect(self._on_data)
        current = self.data_manager.get_current_data()
        if current and not current.get("error"):
            self._on_data(current)

    # ── Window ───────────────────────────────────────────────────────────────

    def _build_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.W, self.H)

        if sys.platform == "win32":
            try:
                hwnd  = int(self.winId())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
                ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x00000080)
            except Exception:
                pass

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # ── Outer card ──
        self.card = QWidget(); self.card.setObjectName("card")
        self.card.setStyleSheet(f"""
            QWidget#card {{
                background: {BG.name()};
                border-radius: 12px;
                border: 1px solid rgba(255,255,255,0.07);
            }}
        """)
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(12,10,12,10); cl.setSpacing(8)

        # ── Title bar ──
        cl.addWidget(self._make_titlebar())
        cl.addWidget(hline())

        # ── Main body: left | track | right ──
        body = QHBoxLayout(); body.setSpacing(10)

        # Left: race info + telemetry panels
        left = QVBoxLayout(); left.setSpacing(8); left.setContentsMargins(0,0,0,0)
        self.info_bar = RaceInfoBar()
        left.addWidget(self.info_bar)
        left.addWidget(hline())

        # Weather label (shown under info bar)
        weather_header = lbl("Weather", bold=True, size=11, color="#DCDCE6")
        left.addWidget(weather_header)

        self._telem_panels: list[TelemetryPanel] = []
        self._telem_container = QWidget(); self._telem_container.setStyleSheet("background:transparent;")
        tl = QVBoxLayout(self._telem_container); tl.setContentsMargins(0,0,0,0); tl.setSpacing(6)
        tl.addStretch()
        left.addWidget(self._telem_container, 1)

        # Controls legend at bottom-left
        legend = QLabel(
            "[SPACE] Pause/Resume    [←/→] ±10%    [↑/↓] Speed    [R] Restart"
        )
        legend.setStyleSheet("color:rgba(150,150,170,0.6);font-size:9px;background:transparent;")
        legend.setWordWrap(True)
        left.addWidget(legend)

        left_w = QWidget(); left_w.setStyleSheet("background:transparent;")
        left_w.setFixedWidth(220)
        left_w.setLayout(left)
        body.addWidget(left_w)

        body.addWidget(vline())

        # Centre: track
        centre = QVBoxLayout(); centre.setSpacing(6)
        self.canvas = TrackCanvas()
        self.canvas.selection_changed = self._on_canvas_selection
        centre.addWidget(self.canvas, 1)

        # Playback controls
        ctrl = self._make_controls()
        centre.addWidget(ctrl)

        # Progress bar
        self.prog_bar = ProgressBar()
        centre.addWidget(self.prog_bar)

        # Lap tick labels
        lap_row = QHBoxLayout()
        for i in [1,10,20,30,40,50]:
            l2 = QLabel(str(i))
            l2.setStyleSheet("color:rgba(150,150,170,0.5);font-size:8px;background:transparent;")
            lap_row.addStretch(); lap_row.addWidget(l2)
        lap_row.addStretch()
        centre.addLayout(lap_row)

        body.addLayout(centre, 1)
        body.addWidget(vline())

        # Right: leaderboard
        self.leaderboard = Leaderboard()
        body.addWidget(self.leaderboard)

        cl.addLayout(body, 1)
        root.addWidget(self.card)

    def _make_titlebar(self) -> QWidget:
        w  = QWidget(); w.setStyleSheet("background:transparent;")
        w.setFixedHeight(32); w.setCursor(Qt.CursorShape.SizeAllCursor)
        hl = QHBoxLayout(w); hl.setContentsMargins(0,0,0,0); hl.setSpacing(8)

        badge = QLabel("F1"); badge.setFixedWidth(26)
        badge.setStyleSheet(
            "background:#E8002D;color:white;font-weight:900;font-size:11px;"
            "border-radius:3px;padding:2px 5px;letter-spacing:1px;")
        hl.addWidget(badge)

        self.title_lbl = QLabel("Race Simulation")
        self.title_lbl.setStyleSheet(
            "color:rgba(255,255,255,0.88);font-size:13px;font-weight:700;background:transparent;")
        hl.addWidget(self.title_lbl)
        hl.addStretch()

        # Race selector button
        sel_btn = QPushButton("📋  Select Race")
        sel_btn.setFixedHeight(24)
        sel_btn.setStyleSheet("""
            QPushButton {
                background:rgba(255,255,255,0.07);border:none;border-radius:5px;
                color:rgba(255,255,255,0.7);font-size:10px;padding:0 10px;
            }
            QPushButton:hover { background:rgba(255,255,255,0.14);color:white; }
        """)
        sel_btn.clicked.connect(self._open_race_selector)
        hl.addWidget(sel_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22,22)
        close_btn.setStyleSheet("""
            QPushButton { background:rgba(255,255,255,0.06);border:none;border-radius:11px;
                color:rgba(255,255,255,0.5);font-size:11px; }
            QPushButton:hover { background:rgba(232,0,45,0.55);color:white; }
        """)
        close_btn.clicked.connect(self.hide)
        hl.addWidget(close_btn)
        return w

    def _make_controls(self) -> QWidget:
        w  = QWidget(); w.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(w); hl.setContentsMargins(0,0,0,0); hl.setSpacing(8)
        hl.addStretch()

        btn_style = """
            QPushButton { background:rgba(255,255,255,0.09);border:none;border-radius:18px;
                color:white;font-size:14px; }
            QPushButton:hover { background:rgba(255,255,255,0.18); }
            QPushButton:pressed { background:rgba(232,0,45,0.4); }
        """

        rw = QPushButton("⏮"); rw.setFixedSize(36,36); rw.setStyleSheet(btn_style)
        rw.clicked.connect(self._rewind); hl.addWidget(rw)

        self.play_btn = QPushButton("▶"); self.play_btn.setFixedSize(36,36)
        self.play_btn.setStyleSheet(btn_style)
        self.play_btn.clicked.connect(self.toggle_play); hl.addWidget(self.play_btn)

        fw = QPushButton("⏭"); fw.setFixedSize(36,36); fw.setStyleSheet(btn_style)
        fw.clicked.connect(self._fastforward); hl.addWidget(fw)

        hl.addSpacing(16)

        self.speed_lbl = QLabel(f"{self._speed_mult:.1f}x")
        self.speed_lbl.setFixedWidth(36)
        self.speed_lbl.setStyleSheet("color:white;font-size:12px;font-weight:700;background:transparent;")
        self.speed_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        slower = QPushButton("−"); slower.setFixedSize(28,28); slower.setStyleSheet(btn_style)
        slower.clicked.connect(self._slower); hl.addWidget(slower)
        hl.addWidget(self.speed_lbl)
        faster = QPushButton("+"); faster.setFixedSize(28,28); faster.setStyleSheet(btn_style)
        faster.clicked.connect(self._faster); hl.addWidget(faster)

        hl.addStretch()
        return w

    # ── Playback controls ─────────────────────────────────────────────────────

    def toggle_play(self):
        self._playing = not self._playing
        self.play_btn.setText("⏸" if self._playing else "▶")

    def _rewind(self):
        for d in self._drivers:
            d["progress"] = max(0.0, d["progress"] - 0.05)
        self._progress = max(0.0, self._progress - 0.05)

    def _fastforward(self):
        for d in self._drivers:
            d["progress"] = min(0.999, d["progress"] + 0.05)
        self._progress = min(0.999, self._progress + 0.05)

    SPEEDS = [0.5, 1.0, 2.0, 4.0, 8.0]

    def _faster(self):
        idx = min(len(self.SPEEDS)-1,
                  next((i for i,s in enumerate(self.SPEEDS) if s>=self._speed_mult),0)+1)
        self._speed_mult = self.SPEEDS[idx]; self.speed_lbl.setText(f"{self._speed_mult:.1f}x")

    def _slower(self):
        idx = max(0, next((i for i,s in enumerate(self.SPEEDS) if s>=self._speed_mult),1)-1)
        self._speed_mult = self.SPEEDS[idx]; self.speed_lbl.setText(f"{self._speed_mult:.1f}x")

    def keyPressEvent(self, e):
        k = e.key()
        if   k == Qt.Key.Key_Space:  self.toggle_play()
        elif k == Qt.Key.Key_Left:   self._rewind()
        elif k == Qt.Key.Key_Right:  self._fastforward()
        elif k == Qt.Key.Key_Up:     self._faster()
        elif k == Qt.Key.Key_Down:   self._slower()
        elif k == Qt.Key.Key_R:
            for d in self._drivers: d["progress"] = (d["pos"]-1)/max(len(self._drivers),1)*0.02
            self._progress = 0.0

    # ── Animation step ────────────────────────────────────────────────────────

    def _step(self):
        if not self._playing or not self._drivers:
            return
        base_speed = 0.00035 * self._speed_mult
        for d in self._drivers:
            d["progress"] = (d["progress"] + base_speed * d["speed_factor"]) % 1.0
            # Simulate speed/gear/DRS variation
            prog = d["progress"]
            d["speed"] = int(160 + 140*abs(math.sin(prog*47+d["pos"])))
            d["gear"]  = max(1, min(8, int(3 + 5*abs(math.sin(prog*31)))))
            d["drs"]   = (math.sin(prog*23) > 0.65)

        self._progress = self._drivers[0]["progress"] if self._drivers else 0.0
        lap_frac = self._progress * self._total_laps
        self._current_lap = max(1, min(self._total_laps, int(lap_frac)+1))

        self.canvas.set_drivers(self._drivers)
        self.canvas.set_selected(self._selected)
        self.leaderboard.update_standings(self._drivers, self._selected)
        self.prog_bar.set_state(self._progress, self._drivers, self._total_laps)
        self._update_telem_panels()
        self.info_bar.update(self._current_lap, self._total_laps,
                             self._elapsed, self._speed_mult, self._weather)

    def _tick_clock(self):
        if self._playing:
            self._elapsed += self._speed_mult

    # ── Telemetry panels ──────────────────────────────────────────────────────

    def _on_canvas_selection(self, selected: set):
        """Called by TrackCanvas when user clicks a driver dot."""
        self._selected = selected
        self._rebuild_telem_panels()
        self.leaderboard.update_standings(self._drivers, self._selected)

    def _sync_selection(self):
        self._selected = self.canvas._selected
        self._rebuild_telem_panels()
        self.leaderboard.update_standings(self._drivers, self._selected)

    def _rebuild_telem_panels(self):
        layout = self._telem_container.layout()
        # Clear
        while layout.count():
            item = layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        sel = [d for d in self._drivers if d["abbr"] in self._selected][:3]
        self._telem_panels = []
        for d in sel:
            panel = TelemetryPanel()
            panel.update_driver(d, self._drivers)
            self._telem_panels.append(panel)
            layout.addWidget(panel)
        layout.addStretch()

    def _update_telem_panels(self):
        sel = [d for d in self._drivers if d["abbr"] in self._selected]
        for i, panel in enumerate(self._telem_panels):
            if i < len(sel):
                panel.update_driver(sel[i], self._drivers)

    # ── Data loading ──────────────────────────────────────────────────────────

    @pyqtSlot(dict)
    def _on_data(self, data: dict):
        last    = data.get("last_race") or {}
        drivers = last.get("drivers") or []
        if not drivers: return
        self._load_race(last, drivers)

    def _load_race(self, last: dict, drivers: list[dict]):
        self._race_name  = last.get("name","")
        self._year       = last.get("year")
        self._round      = last.get("round")
        self._total_laps = 50  # default; updated when telemetry loads

        n = len(drivers)
        self._drivers = []
        for d in drivers:
            pos = d.get("position",20) or 20
            prog = (n - pos) / n * 0.02   # stagger starting positions
            speed_factor = 1.0 - 0.3*(pos-1)/max(n-1,1)
            self._drivers.append({
                "abbr":         d.get("abbreviation","?"),
                "team":         d.get("team",""),
                "color":        tcolor(d.get("team","")),
                "pos":          pos,
                "progress":     prog,
                "speed_factor": speed_factor,
                "speed":        250,
                "gear":         5,
                "drs":          False,
                "status":       d.get("status",""),
            })

        self.title_lbl.setText(f"Race Simulation  ·  {self._race_name}")
        self.canvas.set_race_name(self._race_name)
        self.canvas.set_drivers(self._drivers)
        self.leaderboard.update_standings(self._drivers, self._selected)
        self._playing = True
        self.play_btn.setText("⏸")

        # Auto-select P1 and P2
        if self._drivers:
            self._selected = {self._drivers[0]["abbr"]}
            if len(self._drivers) > 1:
                self._selected.add(self._drivers[1]["abbr"])
            self._rebuild_telem_panels()

        # Load real track in background
        threading.Thread(
            target=self._load_track_bg,
            args=(self._year, self._round),
            daemon=True
        ).start()

    def _load_track_bg(self, year, round_num):
        if not year or not round_num: return
        try:
            import fastf1
            from pathlib import Path
            cache = Path.home()/".f1widget"/"data_cache"/"fastf1"
            cache.mkdir(parents=True, exist_ok=True)
            fastf1.Cache.enable_cache(str(cache))

            session = fastf1.get_session(int(year), int(round_num), "R")
            session.load(telemetry=True, weather=True, messages=False, laps=True)

            # Track outline
            fast_lap = session.laps.pick_fastest()
            tel = fast_lap.get_telemetry()
            xs = tel["X"].tolist(); ys = tel["Y"].tolist()

            # Weather
            try:
                wdf = session.weather_data
                w   = wdf.iloc[len(wdf)//2]
                weather = {
                    "track_temp": round(float(w.get("TrackTemp",0)),1),
                    "air_temp":   round(float(w.get("AirTemp",0)),1),
                    "humidity":   round(float(w.get("Humidity",0))),
                    "wind":       round(float(w.get("WindSpeed",0)),1),
                    "raining":    bool(w.get("Rainfall",False)),
                }
                self._weather = weather
            except Exception:
                pass

            # Total laps
            try:
                self._total_laps = int(session.laps["LapNumber"].max())
            except Exception:
                pass

            # Apply on main thread
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.canvas.set_track(xs, ys))

        except Exception as ex:
            print(f"[RaceSim] Track load failed: {ex}")

    # ── Race selector ─────────────────────────────────────────────────────────

    def _open_race_selector(self):
        sel = RaceSelectorDialog(self.data_manager, self)
        sel.race_selected.connect(self._on_race_selected)
        sel.show()
        # Position it centred on this window
        sg = self.frameGeometry()
        sel.move(sg.left() + (sg.width()-sel.width())//2,
                 sg.top()  + (sg.height()-sel.height())//2)

    @pyqtSlot(dict)
    def _on_race_selected(self, race: dict):
        """Load a different race chosen from the selector."""
        threading.Thread(
            target=self._fetch_and_load_race,
            args=(race["year"], race["round"], race["name"]),
            daemon=True
        ).start()

    def _fetch_and_load_race(self, year, round_num, name):
        try:
            import fastf1
            from pathlib import Path
            cache = Path.home()/".f1widget"/"data_cache"/"fastf1"
            cache.mkdir(parents=True, exist_ok=True)
            fastf1.Cache.enable_cache(str(cache))

            session = fastf1.get_session(int(year), int(round_num), "R")
            session.load(telemetry=False, weather=False, messages=False)
            results = session.results

            drivers = []
            for _, row in results.iterrows():
                drivers.append({
                    "position":     int(row.get("Position",0)) if row.get("Position") else 0,
                    "abbreviation": str(row.get("Abbreviation","")),
                    "full_name":    str(row.get("FullName","")),
                    "team":         str(row.get("TeamName","")),
                    "team_color":   str(row.get("TeamColor","FFFFFF")),
                    "status":       str(row.get("Status","")),
                    "points":       float(row.get("Points",0.0)),
                })
            drivers.sort(key=lambda d: d["position"] if d["position"]>0 else 999)

            last = {
                "year": year, "round": round_num, "name": name,
                "drivers": drivers,
            }
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._load_race(last, drivers))

        except Exception as ex:
            print(f"[RaceSim] Race fetch failed: {ex}")

    # ── Positioning ───────────────────────────────────────────────────────────

    def snap_to(self, main_widget: QWidget):
        """Position the simulation window to the left of the main widget.
        If it doesn't fit to the left, try below, then just centre on screen."""
        mg     = main_widget.frameGeometry()
        screen = self.screen().availableGeometry()
        gap    = 12

        # Preferred: to the left of widget
        x = mg.left() - self.W - gap
        y = mg.top()

        # If it goes off screen left, place below the widget instead
        if x < screen.left():
            x = mg.left()
            y = mg.bottom() + gap

        # Clamp to screen bounds
        x = max(screen.left(), min(x, screen.right()  - self.W))
        y = max(screen.top(),  min(y, screen.bottom() - self.H))
        self.move(x, y)

    # ── Drag ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def paintEvent(self, e): pass


# ── Race Selector Dialog ──────────────────────────────────────────────────────

from PyQt6.QtCore import pyqtSignal

class RaceSelectorDialog(QWidget):
    race_selected = pyqtSignal(dict)

    def __init__(self, data_manager, parent=None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.data_manager = data_manager
        self._drag_pos = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 520)
        self._build_ui()
        self._load_schedule()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)

        card = QWidget(); card.setObjectName("sd")
        card.setStyleSheet(f"""
            QWidget#sd {{
                background:{CARD_BG.name()};
                border-radius:12px;
                border:1px solid rgba(255,255,255,0.10);
            }}
        """)
        vl = QVBoxLayout(card); vl.setContentsMargins(16,14,16,16); vl.setSpacing(10)

        # Title bar
        bar = QHBoxLayout()
        badge = QLabel("F1"); badge.setFixedWidth(24)
        badge.setStyleSheet(
            "background:#E8002D;color:white;font-weight:900;font-size:11px;"
            "border-radius:3px;padding:1px 4px;")
        bar.addWidget(badge)
        title = QLabel("Select a Race"); 
        title.setStyleSheet("color:white;font-size:13px;font-weight:700;background:transparent;")
        bar.addWidget(title); bar.addStretch()
        close = QPushButton("✕"); close.setFixedSize(20,20)
        close.setStyleSheet("""
            QPushButton { background:rgba(255,255,255,0.06);border:none;border-radius:10px;
                color:rgba(255,255,255,0.5);font-size:10px; }
            QPushButton:hover { background:rgba(232,0,45,0.55);color:white; }
        """)
        close.clicked.connect(self.close)
        bar.addWidget(close)
        vl.addLayout(bar)
        vl.addWidget(hline())

        # Status
        self.status_lbl = QLabel("Loading schedule…")
        self.status_lbl.setStyleSheet("color:rgba(180,180,200,0.6);font-size:10px;background:transparent;")
        vl.addWidget(self.status_lbl)

        # Scrollable race list
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background:transparent;border:none; }}
            QScrollBar:vertical {{ background:rgba(255,255,255,0.04);width:4px;border-radius:2px; }}
            QScrollBar::handle:vertical {{ background:rgba(255,255,255,0.18);border-radius:2px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """)
        self.list_w = QWidget(); self.list_w.setStyleSheet("background:transparent;")
        self.list_vl = QVBoxLayout(self.list_w)
        self.list_vl.setContentsMargins(0,0,4,0); self.list_vl.setSpacing(3)
        scroll.setWidget(self.list_w)
        vl.addWidget(scroll, 1)

        root.addWidget(card)
        card.setCursor(Qt.CursorShape.SizeAllCursor)

    def _load_schedule(self):
        threading.Thread(target=self._fetch_schedule, daemon=True).start()

    def _fetch_schedule(self):
        try:
            import fastf1
            from pathlib import Path
            cache = Path.home()/".f1widget"/"data_cache"/"fastf1"
            cache.mkdir(parents=True, exist_ok=True)
            fastf1.Cache.enable_cache(str(cache))

            current_year = datetime.now().year
            races = []
            for year in [current_year, current_year-1]:
                try:
                    sched = fastf1.get_event_schedule(year, include_testing=False)
                    past  = sched[sched["EventDate"] < str(datetime.now().date())]
                    for _, ev in past.iterrows():
                        races.append({
                            "year":     year,
                            "round":    int(ev["RoundNumber"]),
                            "name":     str(ev["EventName"]),
                            "location": str(ev.get("Location","")),
                            "country":  str(ev.get("Country","")),
                            "date":     str(ev["EventDate"])[:10],
                        })
                except Exception:
                    pass

            races.sort(key=lambda r: (r["year"], r["round"]), reverse=True)
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._populate(races))

        except Exception as ex:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.status_lbl.setText(f"⚠ {ex}"))

    def _populate(self, races):
        self.status_lbl.setText(f"{len(races)} races available — click to load")
        for r in races:
            btn = QPushButton(f"  {r['year']}  R{r['round']:02d}  {r['name']}  ·  {r['date']}")
            btn.setFixedHeight(32)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:rgba(255,255,255,0.04);border:none;border-radius:5px;
                    color:rgba(220,220,230,0.85);font-size:10px;text-align:left;padding:0 8px;
                }}
                QPushButton:hover {{ background:rgba(232,0,45,0.20);color:white; }}
                QPushButton:pressed {{ background:rgba(232,0,45,0.35); }}
            """)
            race = r  # capture
            btn.clicked.connect(lambda _, rc=race: self._select(rc))
            self.list_vl.addWidget(btn)
        self.list_vl.addStretch()

    def _select(self, race):
        self.race_selected.emit(race)
        self.close()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def paintEvent(self, e): pass
