"""R12 回归验证: 窗口模式下卡片挤压/标题竖截修复.

断言:
- A. Card 标题行 (ElideLabel) 可见高度 >= 标题字形单行高度的 0.9 (不被竖截)
- B. status 卡 grid 与外网地址 label 之间垂直间距 > 0 (addSpacing 生效)
- C. 多尺寸 (700/900/1280/1680 × 多高度) 渲染无异常, 截图存盘供人工/多模态查看

运行: .venv/Scripts/python.exe tools/smoke_r12.py
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase, QFont, QFontMetrics
from PySide6.QtWidgets import QApplication, QLabel

from llama_console_v2.main_window import MainWindow
from llama_console_v2 import theme as t
from llama_console_v2.widgets.elide_label import ElideLabel
from llama_console_v2.widgets.card import Card


def setup_cjk(app):
    fid = QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    fams = QFontDatabase.applicationFontFamilies(fid)
    app.setFont(QFont(fams[0] if fams else "Microsoft YaHei", 10))


def _title_label(card: Card):
    return card.findChild(ElideLabel)


def check_titles(win: MainWindow):
    """返回 (ok, details)。检查每卡标题 ElideLabel 可见高度是否足够。"""
    cards = win.findChildren(Card)
    details = []
    ok = True
    for c in cards:
        lbl = _title_label(c)
        if lbl is None:
            details.append(f"[?] {c.objectName()} 未找到标题 ElideLabel")
            continue
        fm = QFontMetrics(lbl.font())
        needed = fm.height()           # 单行字形高度
        got = lbl.height()             # 实际分配高度
        ratio = got / needed if needed else 1.0
        card_ok = ratio >= 0.9
        ok = ok and card_ok
        details.append(
            f"[{'OK' if card_ok else 'XX'}] title={lbl._full_text!r:24} "
            f"fontH={needed} gotH={got} ratio={ratio:.2f}"
        )
    return ok, details


def check_status_spacing(win: MainWindow):
    """检查 status 卡 grid 与外网地址 label 之间垂直间距 > 0。"""
    page = win._console_page
    grid = page._status_grid
    # 外网地址 label: 在 body 中紧随 grid + addSpacing, 找 text=='外网地址' 的 QLabel
    public_title = None
    for w in page.findChildren(QLabel):
        if w.text() == "外网地址" and grid.parent() is not None and \
                w.parent() is grid.parent():
            public_title = w
            break
    if public_title is None or grid is None:
        return False, ["外网地址 label 或 grid 未找到"]
    gap = public_title.geometry().top() - grid.geometry().bottom()
    ok = gap > 0
    return ok, [f"[{'OK' if ok else 'XX'}] status_grid.bottom={grid.geometry().bottom()} "
                f"-> 外网地址.top={public_title.geometry().top()} gap={gap}px"]


def render_at(width, height, label, app):
    win = MainWindow()
    t.set_font_scale(t.compute_font_scale(width, height))
    win.resize(width, height)
    win.show()
    QApplication.processEvents()
    QTimer.singleShot(600, QApplication.instance().quit)
    QApplication.instance().exec()
    out = os.path.join(os.path.dirname(__file__), f"r12_{label}.png")
    win.grab().save(out, "PNG")
    # 断言
    t_ok, t_det = check_titles(win)
    s_ok, s_det = check_status_spacing(win)
    win.close()
    return t_ok, t_det, s_ok, s_det, out


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)
    app = QApplication.instance() or QApplication(sys.argv)
    setup_cjk(app)

    sizes = [
        (700, 550, "700x550"),
        (900, 600, "900x600"),
        (1280, 900, "1280x900"),   # 用户截图同款
        (1680, 1040, "1680x1040"),  # 全屏参考
    ]

    all_ok = True
    for w, h, lbl in sizes:
        print(f"\n=== {lbl} ===")
        t_ok, t_det, s_ok, s_det, out = render_at(w, h, lbl, app)
        for d in t_det:
            print("  " + d)
        for d in s_det:
            print("  " + d)
        print(f"  截图: {out}")
        size_ok = t_ok and s_ok
        all_ok = all_ok and size_ok
        print(f"  结果: {'PASS ✅' if size_ok else 'FAIL ❌'}")

    print("\n" + ("ALL R12 CHECKS PASSED ✅" if all_ok else "R12 CHECKS FAILED ❌"))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
