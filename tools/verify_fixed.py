"""验证: 固定窗口 1440x900 下
- 1) 窗口 min==max==(1440,900) (setFixedSize 生效, 不可调节)
- 2) 控制台页 QScrollArea 不滚动
- 3) 控制台页 6 卡标题完整 (gotH==fontH)
- 4) 设置页内容自然高度 <= 900 (否则固定窗口会裁切, 需兜底)
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QFontDatabase, QFont, QFontMetrics
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

from llama_console_v2.main_window import MainWindow
from llama_console_v2 import theme as t
from llama_console_v2.widgets.elide_label import ElideLabel
from llama_console_v2.widgets.card import Card


def setup_cjk(app):
    fid = QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    fams = QFontDatabase.applicationFontFamilies(fid)
    app.setFont(QFont(fams[0] if fams else "Microsoft YaHei", 10))


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)
    app = QApplication.instance() or QApplication(sys.argv)
    setup_cjk(app)

    win = MainWindow()
    win.show()  # 模拟真实启动 (offscreen 下 show 才应用固定 geometry, 视口高度才正确)
    QApplication.processEvents()
    QTimer.singleShot(400, QApplication.instance().quit)
    QApplication.instance().exec()

    # 1) 固定尺寸
    mn = win.minimumSize()
    mx = win.maximumSize()
    fixed_ok = (mn == mx == QSize(1440, 960))
    print(f"[1] fixed size: min={mn.width()}x{mn.height()} max={mx.width()}x{mx.height()} "
          f"-> {'OK ✅' if fixed_ok else 'XX ❌'}")

    # 2) 控制台页不滚动
    scroll = win.findChild(QScrollArea, "ConsoleScroll")
    vsb = scroll.verticalScrollBar() if scroll else None
    no_vscroll = (vsb is None or vsb.maximum() <= 0)
    print(f"[2] console no vScroll: {no_vscroll} (max={vsb.maximum() if vsb else '?'}) "
          f"-> {'OK ✅' if no_vscroll else 'XX ❌'}")

    # 3) 标题完整
    cards = win.findChildren(Card)
    title_ok = True
    for c in cards:
        lbl = c.findChild(ElideLabel)
        if lbl is None:
            continue
        fm = QFontMetrics(lbl.font())
        ratio = lbl.height() / fm.height() if fm.height() else 1.0
        if ratio < 0.9:
            title_ok = False
            print(f"    XX title {lbl._full_text!r} ratio={ratio:.2f}")
    print(f"[3] console 6 titles intact: {'OK ✅' if title_ok else 'XX ❌'}")

    # 4) 设置页内容自然高度 (解锁临时放大测)
    win.setMinimumSize(0, 0)
    win.setMaximumSize(16777215, 16777215)
    win.resize(2400, 1400)
    win.show()
    win._switch_to(1)
    QApplication.processEvents()
    QTimer.singleShot(300, QApplication.instance().quit)
    QApplication.instance().exec()
    page = win._settings_page
    natural_h = page.layout().sizeHint().height() if page.layout() else -1
    fits = natural_h <= 900
    print(f"[4] settings natural height={natural_h} vs 900 -> "
          f"{'FITS ✅' if fits else 'OVERFLOW ❌ (需 QScrollArea 兜底)'}")

    win.close()
    all_ok = fixed_ok and no_vscroll and title_ok and fits
    print("\n" + ("ALL FIXED-WINDOW CHECKS PASSED ✅" if all_ok else "FIXED-WINDOW CHECKS FAILED ❌"))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
