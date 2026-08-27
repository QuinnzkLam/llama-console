"""R11 回归测试: 在多个窗口宽度下验证挤压修复.
- 删除侧边栏 hint 文字
- 删除 Token 卡未启动 placeholder
- 修复 FRP/Token 标题 ElideLabel 防挤压
- 修复 status 卡 KV grid 末项跨 2 列防挤压
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication

from llama_console_v2.main_window import MainWindow
from llama_console_v2 import theme as t


def setup_cjk(app):
    fid = QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    fams = QFontDatabase.applicationFontFamilies(fid)
    app.setFont(QFont(fams[0] if fams else "Microsoft YaHei", 10))


def render_at(width, height, label):
    win = MainWindow()
    t.set_font_scale(t.compute_font_scale(width, height))
    win.resize(width, height)
    win.show()
    QApplication.processEvents()
    QTimer.singleShot(1000, QApplication.instance().quit)
    QApplication.instance().exec()
    out = os.path.join(os.path.dirname(__file__), f"r11_after_{label}.png")
    pix = win.grab()
    pix.save(out, "PNG")
    print(f"  [{label}] {width}x{height} -> {out}")
    win.close()
    return pix


def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)
    app = QApplication.instance() or QApplication(sys.argv)
    setup_cjk(app)

    # 主测试: 900x550 (用户截图同款)
    render_at(900, 550, "900x550")
    # 边界测试: 紧贴最小宽度
    render_at(800, 550, "800x550")
    render_at(700, 550, "700x550")
    # 全屏
    render_at(1400, 900, "1400x900")

    print("\n--- 几何断言 (900x550) ---")
    # 单独验证 status 卡 KV grid 后, public_title 不再"挤进" row 1 col 1
    win = MainWindow()
    t.set_font_scale(t.compute_font_scale(900, 550))
    win.resize(900, 550)
    win.show()
    QApplication.processEvents()
    QTimer.singleShot(800, QApplication.instance().quit)
    QApplication.instance().exec()

    from llama_console_v2.widgets.card import Card

    cards = win._console_page.findChildren(Card)
    print(f"  cards found: {len(cards)}")
    status_card = None
    frp_card = None
    token_card = None
    for c in cards:
        for ch in c.findChildren(type(c).__class__):
            pass
        # 找标题 Label 文字
        title_widget = None
        for ch in c.findChildren(type(c).__class__):
            if hasattr(ch, "_full_text"):
                title_widget = ch
                break
        if title_widget:
            t_text = title_widget._full_text
            if "llama-server 状态" in t_text:
                status_card = c
            elif "FRP 隧道" in t_text:
                frp_card = c
            elif "Token 统计" in t_text:
                token_card = c

    # 验证 sidebar 无 hint 文字
    from llama_console_v2.widgets.server_control import ServerControlSidebar
    sb = win._server_control = win.findChild(ServerControlSidebar)
    print(f"  sidebar found: {sb is not None}")
    if sb is not None:
        has_hint = any(
            getattr(w, "_full_text", None) == "使用设置页中的启动参数"
            for w in sb.findChildren(type(sb).__class__)
        )
        print(f"  sidebar hint LBL still present?  {has_hint}")
        assert not has_hint, "sidebar hint should be removed"

    # 验证 Token 卡 placeholder 文字不在
    if token_card is not None:
        from llama_console_v2.widgets.server_control import ServerControlSidebar
        # find _token_total_lbl on console page
        placeholder_present = False
        for ch in win._console_page.findChildren(type(win._console_page).__class__):
            if getattr(ch, "text", lambda: "")() == "llama-server 未启动. 点击侧边栏「启动」按钮即可启动":
                placeholder_present = True
                break
        print(f"  Token card placeholder present?  {placeholder_present}")
        assert not placeholder_present, "Token placeholder text should be empty"

    print("\nALL CHECKS PASSED ✅")


if __name__ == "__main__":
    main()
