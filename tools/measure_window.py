"""测量: 在各候选窗口尺寸下, 控制台页 body 的 QScrollArea 是否出现纵向滚动条.
目的: 找出"最小的不滚动尺寸"作为固定窗口默认尺寸.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication, QScrollArea

from llama_console_v2.main_window import MainWindow
from llama_console_v2 import theme as t


def setup_cjk(app):
    fid = QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    fams = QFontDatabase.applicationFontFamilies(fid)
    app.setFont(QFont(fams[0] if fams else "Microsoft YaHei", 10))


def measure(w, h):
    win = MainWindow()
    t.set_font_scale(t.compute_font_scale(w, h))
    win.resize(w, h)
    win.show()
    QApplication.processEvents()
    QTimer.singleShot(500, QApplication.instance().quit)
    QApplication.instance().exec()
    scroll = win.findChild(QScrollArea, "ConsoleScroll")
    vsb = scroll.verticalScrollBar() if scroll else None
    hsb = scroll.horizontalScrollBar() if scroll else None
    scrollable_v = (vsb is not None and vsb.maximum() > 0)
    scrollable_h = (hsb is not None and hsb.maximum() > 0)
    content_h = scroll.widget().height() if scroll and scroll.widget() else -1
    scale = t.get_font_scale()
    win.close()
    return scrollable_v, scrollable_h, content_h, scale


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)
    app = QApplication.instance() or QApplication(sys.argv)
    setup_cjk(app)

    cands = [
        (1280, 800), (1280, 900), (1366, 768), (1366, 850),
        (1440, 900), (1536, 864), (1600, 960), (1680, 1040),
    ]
    print(f"{'size':12} {'scale':6} {'vScroll':8} {'hScroll':8} {'contentH':9}")
    for w, h in cands:
        sv, sh, ch, sc = measure(w, h)
        flag = "NO-SCROLL ✅" if not sv and not sh else "SCROLL ❌"
        print(f"{w}x{h:<6} {sc:<6.2f} {str(sv):8} {str(sh):8} {ch:<9} {flag}")


if __name__ == "__main__":
    main()
