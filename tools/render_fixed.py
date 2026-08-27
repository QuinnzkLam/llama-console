"""渲染固定窗口 1440x960 截图 (tools/fixed_1440x960.png) 供人工查看."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication

from llama_console_v2.main_window import MainWindow


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    fid = QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    fams = QFontDatabase.applicationFontFamilies(fid)
    app.setFont(QFont(fams[0] if fams else "Microsoft YaHei", 10))

    win = MainWindow()
    win.show()
    QApplication.processEvents()
    QTimer.singleShot(700, QApplication.instance().quit)
    QApplication.instance().exec()
    out = os.path.join(os.path.dirname(__file__), "fixed_1440x960.png")
    win.grab().save(out, "PNG")
    print(f"saved -> {out}")
    win.close()


if __name__ == "__main__":
    main()
