#!/usr/bin/env python3
"""
F1 Desktop Widget - Main Entry Point
Transparent, always-on-desktop F1 race data overlay with system tray control.
"""

import sys
import os
import signal
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PyQt6.QtCore import Qt, QTimer

from widget import F1Widget
from data_manager import DataManager
from settings import Settings
from autostart import AutostartManager


def create_f1_icon():
    """Create a simple F1-themed icon programmatically."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Red background circle
    painter.setBrush(QColor("#E8002D"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, 32, 32)

    # White "F1" text
    painter.setPen(QColor("white"))
    font = QFont("Arial", 10, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "F1")
    painter.end()

    return QIcon(pixmap)


def main():
    # Allow Ctrl+C to work in terminal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("F1 Desktop Widget")

    # Load settings
    settings = Settings()

    # Initialize data manager (handles FastF1 data + auto-updates)
    data_manager = DataManager(settings)

    # Create main widget
    widget = F1Widget(settings, data_manager)

    # Create system tray
    if QSystemTrayIcon.isSystemTrayAvailable():
        icon = create_f1_icon()
        tray = QSystemTrayIcon(icon, app)
        tray.setToolTip("F1 Desktop Widget")

        menu = QMenu()

        show_action = menu.addAction("Show / Hide Widget")
        show_action.triggered.connect(widget.toggle_visibility)

        menu.addSeparator()

        refresh_action = menu.addAction("🔄  Force Refresh Data")
        refresh_action.triggered.connect(data_manager.force_refresh)

        menu.addSeparator()

        # Autostart toggle
        autostart_mgr = AutostartManager()
        autostart_action = menu.addAction(
            "✅  Launch at startup" if autostart_mgr.is_enabled()
            else "☐  Launch at startup"
        )

        def toggle_autostart():
            if autostart_mgr.is_enabled():
                autostart_mgr.disable()
                autostart_action.setText("☐  Launch at startup")
            else:
                autostart_mgr.enable()
                autostart_action.setText("✅  Launch at startup")

        autostart_action.triggered.connect(toggle_autostart)

        menu.addSeparator()

        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(app.quit)

        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: widget.toggle_visibility()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        tray.show()

    # Start data manager background tasks
    data_manager.start()

    # Show widget
    widget.show()

    # Ctrl+C friendly timer
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
