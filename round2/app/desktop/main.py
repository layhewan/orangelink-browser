from __future__ import annotations

import sys

from app.desktop.window import create_main_window


def run_desktop_gui() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("缺少 PySide6，无法启动桌面界面。")
        return 2

    app = QApplication.instance() or QApplication(sys.argv)
    window = create_main_window()
    window.show()
    return int(app.exec())
