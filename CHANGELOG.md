# llama-console v2 — Changelog

## v0.1.1 (2026-08-25)

**Laptop portable fix** — Quinn 15:10 RDP 测试

### Fix
- **A) Add 3 missing files**: `__init__.py` (85B), `__main__.py` (124B), `app.py` (2384B)
- **B) Add 9 missing modules**: `backend/main_window.py`, `pages/__init__.py`, `widgets/__init__.py`, `widgets/buttons.py`, `widgets/key_value.py`, `widgets/page_chrome.py`, `widgets/progress_bar.py`, `widgets/stat_block.py`, `widgets/status_pill.py`
- **C) Add root `llama_cpp.py`** (10744B) — 核弹机 root level 嘅 llama_cpp.py (冇喺 backend/)

### 旧 zip (v0.1.0) 漏咗 12 个 .py → __main__ 入唔到

**根本原因：** 我 iMac 源 `draft/src/llama_console_v2/` 系旧版 (10 .py)，但核弹机部署嘅系新版 (22 .py)。新版本冇 commit 返 iMac git。

### 验证
- iMac zip 旧 32KB → 新 56KB (+12 个 .py)
- 核弹机 22 .py 100% 一致
- `python -m llama_console_v2` 应该 work (因为 `__main__.py` + `app.py` 而家齐)
