"""v2 backend/status.py - stub for console.py import compatibility.

console.py line 23: from ..backend import status as backend_status
但实际冇任何 backend_status.xxx 调用 (verified via grep).
保留 module 避免 ImportError, 真实状态查询由 llama_cpp.snapshot() 提供.
"""
from __future__ import annotations

# Intentionally empty stub. 真实 status 由 llama_cpp.snapshot() 提供.
