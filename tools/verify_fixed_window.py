"""R13: 验证固定窗口 (基于屏幕比例) 在 2560x1440 下不超出、不滚动、标题完整.

offscreen 无真实屏幕 -> primaryScreen() 返回 None -> 走 fallback 2560x1440,
等效模拟用户 2560x1440 环境 (无 DPI 缩放时).
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QScrollArea, QLabel
from PySide6.QtCore import QSize
from PySide6.QtGui import QFontMetrics

sys.path.insert(0, "src")
from llama_console_v2.main_window import MainWindow  # noqa: E402


def check_titles(page):
    bad = []
    # 仅检查标签类 (含 Card 标题的 ElideLabel); 排除 QProgressBar 的内部文本
    for w in page.findChildren(QLabel):
        txt = w.text()
        if not isinstance(txt, str) or not txt.strip():
            continue
        ps = w.font().pointSize()
        if ps <= 0:
            continue
        got_h = w.height()
        fm = QFontMetrics(w.font())
        font_h = fm.height()
        if got_h < font_h * 0.95:
            bad.append((w.__class__.__name__, txt[:20], got_h, font_h))
    return bad


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    app.processEvents()

    size = win.size()
    mn = win.minimumSize()
    mx = win.maximumSize()
    print(f"[1] window size = {size.width()}x{size.height()}")
    print(f"    min = {mn.width()}x{mn.height()}  max = {mx.width()}x{mx.height()}")
    fixed_ok = (mn == mx == size)
    print(f"    fixed (min==max==size): {fixed_ok}")

    # 模拟用户屏幕 2560x1440
    screen = QSize(2560, 1440)
    fits = (size.width() <= screen.width()) and (size.height() <= screen.height())
    print(f"[2] fits 2560x1440 screen: {fits}  (occupies "
          f"{size.width()/screen.width()*100:.0f}% x {size.height()/screen.height()*100:.0f}%)")

    # 控制台页不滚动
    page = win._console_page
    sas = page.findChildren(QScrollArea)
    vmax = 0
    for sa in sas:
        vmax = max(vmax, sa.verticalScrollBar().maximum())
    print(f"[3] console QScrollArea vScroll max = {vmax} (0 => no scroll): {vmax == 0}")

    # 标题完整性
    bad = check_titles(page)
    print(f"[4] title truncated count = {len(bad)}")
    for b in bad[:8]:
        print(f"    {b}")

    # 设置页内容自然高度
    sp = win._settings_page
    sp.hide()  # 确保未显示状态量到
    sp.adjustSize()
    nat_h = sp.height()
    print(f"[5] settings page natural height = {nat_h} <= window {size.height()}: "
          f"{nat_h <= size.height()}")

    all_ok = fixed_ok and fits and (vmax == 0) and (len(bad) == 0) and (nat_h <= size.height())
    print(f"\nRESULT: {'PASS' if all_ok else 'FAIL'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
