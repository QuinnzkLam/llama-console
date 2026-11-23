"""NLM.exe entry point.

This module is the PyInstaller bootloader target. Imports must be absolute
(package-level) so they resolve under both:
  - PyInstaller --onefile (sys.path[0] = _MEIPASS, no __package__)
  - `python -m llama_console_v2` (sys.path contains parent of package)
"""
import sys

# LHM 子进程入口: 必须喺 import app (PySide6 / GUI) 之前分流
if "--lhm-worker" in sys.argv:
    from llama_console_v2.backend import lhm_worker
    lhm_worker.run()
    sys.exit(0)

from llama_console_v2.app import main

if __name__ == "__main__":
    sys.exit(main())
