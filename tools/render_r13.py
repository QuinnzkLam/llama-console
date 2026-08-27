"""R13: 渲染固定窗口截图 (offscreen)."""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication

sys.path.insert(0, "src")
from llama_console_v2.main_window import MainWindow  # noqa: E402

app = QApplication(sys.argv)
win = MainWindow()
win.show()
app.processEvents()
pix = win.grab()
out = "tools/r13_fixed.png"
pix.save(out)
print(f"saved {out} size={pix.width()}x{pix.height()}")
