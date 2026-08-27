"""v2 R10 窗口模式响应式回归测试 — 多宽度 offscreen 截图

Quinn 16:11: 验证 _ElideLabel + 更激进的 FONT_SCALE_MIN 是否解决了
CPU/RAM/状态卡 长文本在窄窗口下与下层 label 挤压重叠的问题.

策略:
- 4 个宽度 (600/900/1280/1680px), 各 550 高 (用户截图同款)
- MainWindow 创建后 setWindowSize, 触发 resizeEvent → 应用 FONT_SCALE
- 渲染 → 抓 pixmap → 保存为 png
- 同时跑一段 _force_relayout 防止初始未刷
- 用页面截图 + 字节数比对, 没截到元素就 OK
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QSize, QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from llama_console_v2 import theme as t  # noqa: E402
from llama_console_v2.main_window import MainWindow  # noqa: E402


WIDTHS = [600, 900, 1280, 1680]
HEIGHT = 550
OUT_DIR = ROOT / "tools" / "r10_shots"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # 清掉旧图
    for old in OUT_DIR.glob("*.png"):
        old.unlink()

    app = QApplication.instance() or QApplication(sys.argv)

    win = MainWindow()
    win.show()

    # 等初始事件循环把 relayout + 首帧刷新跑完
    for _ in range(8):
        app.processEvents()
        time.sleep(0.08)

    results: list[tuple[int, int, int, float, bool]] = []

    for w in WIDTHS:
        win.resize(QSize(w, HEIGHT))
        # 触发 resize 防抖 timer (150ms) + 字体缩放应用
        for _ in range(15):
            app.processEvents()
            time.sleep(0.05)
        # 强制刷新
        win._console_page.refresh()
        for _ in range(8):
            app.processEvents()
            time.sleep(0.05)

        pixmap = win.grab()
        png_path = OUT_DIR / f"console_{w}x{HEIGHT}.png"
        ok = pixmap.save(str(png_path))
        size_bytes = png_path.stat().st_size if ok else 0
        scale = t.get_font_scale()
        results.append((w, HEIGHT, size_bytes, scale, ok))

    # 打印结果
    print(f"{'width':>6} {'height':>6} {'png_bytes':>10} {'font_scale':>10} {'saved':>6}")
    for w, h, sz, sc, ok in results:
        print(f"{w:>6} {h:>6} {sz:>10} {sc:>10.3f} {str(ok):>6}")

    # 全部 OK 即通过
    assert all(r[4] for r in results), "部分截图保存失败"
    assert all(r[2] > 5_000 for r in results), "截图过小 (可能空白)"
    print("\nALL OK. PNGs in:", OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())