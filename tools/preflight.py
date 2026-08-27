"""v2 startup pre-flight diagnostic (pure ASCII file; prints Chinese safely via Python).

Called by start_v2.bat before launching the GUI. Python writes to the Windows
console using the wide-char API (WriteConsoleW), so Chinese renders correctly
regardless of the .bat file encoding or the active code page.
"""
from __future__ import annotations

import sys

from llama_console_v2.backend.llama_cpp import diagnose_llama_server_exe


def main() -> int:
    print("=" * 52)
    print(" llama-console v2 - startup pre-flight diagnostic")
    print("=" * 52)

    try:
        r = diagnose_llama_server_exe()
    except Exception as e:  # never let pre-flight crash the launcher
        print("[preflight] diagnostic error:", e)
        return 0

    if r.get("ok"):
        print("[OK] llama-server.exe is valid and ready.")
        return 0

    print("[DIAG] llama-server.exe check FAILED:")
    print("  reason:", r.get("reason", ""))
    for c in r.get("candidates", []):
        size = c.get("size", 0)
        print(
            "  candidate: {path}  exists={exists}  valid={valid}  ({size} B)".format(
                path=c.get("path", ""),
                exists=c.get("exists", False),
                valid=c.get("valid", False),
                size=size,
            )
        )
    if r.get("error"):
        print(r["error"])

    print()
    print("  >> GUI will still start, but the sidebar 'Start' button will")
    print("     fail until a real llama-server.exe is placed at one of the")
    print("     candidate paths listed above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
