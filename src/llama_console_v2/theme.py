"""
主题模块 - 从 HTML 设计图提取的精确配色 token
Source: llama-server 控制台 v4.html + 设置.html

v2 排版 + 字号重设计（2026-08-25 14:08 Quinn 反馈）：
- FONT_SIZE 微调（+1pt）保信息清晰
- 增 FORM min_window 到 1480×900（防 squeezed）
- 增 CARD_PADDING / ROW_HEIGHT token
"""

# ============================================================
# 配色（来自设计图 --brand-* CSS variables）
# ============================================================
COLORS = {
    # 高亮黑白主题 (2026-08-27 Quinn): 黑底白字, 深色高对比, 取代原深蓝/浅色主题
    "bg":                "#0a0a0a",   # 近纯黑底
    "card":              "#161616",   # 微抬升卡片
    "card_hover":        "#262626",   # 悬停深灰
    "input":             "#1f1f1f",   # 输入框深灰
    "surface_3":         "#2a2a2a",   # 三级表面中灰
    "border":            "#333333",   # 边框深灰
    "overlay":           "#000000",
    "text_primary":      "#ffffff",   # 纯白主文字
    "text_secondary":    "#d4d4d8",   # 次级浅灰
    "text_muted":        "#8b8b8b",   # 弱信息中灰
    "text_on_primary":   "#0a0a0a",   # 白按钮上的黑字
    "primary":           "#ffffff",   # 白作主强调 (替代深蓝)
    "primary_hover":     "#e5e5e5",   # 白悬停
    "success":           "#16a34a",   # 鲜明绿 (状态)
    "warning":           "#d97706",   # 鲜明琥珀 (状态)
    "danger":            "#dc2626",   # 鲜明红 (状态)
    "info":              "#d4d4d8",   # 中性浅灰 (去蓝)
    "ring":              "#ffffff",   # 白焦点环
}

RADIUS = {
    "xs":  2, "sm":  4, "md":  6, "lg":  8, "xl": 12, "full": 9999,
}

SPACE = {
    "1":  4, "2":  8, "3": 12, "4": 16, "5": 20, "6": 24, "7": 32, "8": 48,
}

FONT_FAMILY = '"Inter", "Noto Sans CJK SC", "Microsoft YaHei", "Segoe UI", sans-serif'
FONT_FAMILY_MONO = '"JetBrains Mono", "Cascadia Code", Consolas, "Courier New", monospace'

# 字号基准 — v2 排版重设计 (Quinn 14:40 反馈: 排版 + 字号 让信息完整)
# 这是设计稿基线（FONT_SCALE=1.0 时的值）。实际取值会乘以 FONT_SCALE 自动缩放。
BASE_FONT_SIZE = {
    "xs":   11,   # 14→11: 副信息/标签
    "sm":   13,   # 16→13: 数据值/按钮
    "base": 14,
    "md":   14,   # 17.5*1: error banner body (Quinn 11:56 fix FONT_SIZE["md"] missing)   # 17→14: 副数据
    "lg":   15,   # 20→15: 卡片模型名/子卡标题（Quinn 16:08 反馈：标题过粗）
    "xl":   17,   # 24→17: 卡片父标题（Quinn 16:08 反馈：2xl 过粗，降到 xl+bold）
    "2xl":  20,   # 28→20: 大段标题（保留备用）
    "3xl":  24,   # 34→24: 大数字
    "4xl":  32,
    "5xl":  44,
}

# 字体自动缩放：FONT_SIZE[key] = round(BASE_FONT_SIZE[key] * FONT_SCALE)
FONT_SCALE = 1.0
# 设计稿参考尺寸（在此尺寸下 FONT_SCALE=1.0）
FONT_REF_W, FONT_REF_H = 1680, 1040
# Quinn 16:11: 0.65→0.55, 窄窗口 (~600px) 下进一步缩字号,
#   给 _ElideLabel 单行省略更多余量, 减少相邻行的视觉挤压感.
FONT_SCALE_MIN, FONT_SCALE_MAX = 0.55, 1.25


class _ScaledFontSize:
    """dict-like，按下标返回 BASE_FONT_SIZE[key] * FONT_SCALE（四舍五入整数）。"""

    def __getitem__(self, key: str) -> int:
        if key not in BASE_FONT_SIZE:
            raise KeyError(f"unknown font size: {key}")
        return int(round(BASE_FONT_SIZE[key] * FONT_SCALE))

    def get(self, key: str, default=None):
        if key not in BASE_FONT_SIZE:
            return default
        return int(round(BASE_FONT_SIZE[key] * FONT_SCALE))


# 对外仍用 t.FONT_SIZE["lg"] 访问，所有调用点无需改动
FONT_SIZE = _ScaledFontSize()


def set_font_scale(scale: float) -> None:
    """设置全局字体缩放系数（窗口尺寸变化时调用）。"""
    global FONT_SCALE
    FONT_SCALE = max(0.4, float(scale))


def get_font_scale() -> float:
    return FONT_SCALE


def compute_font_scale(width: int, height: int) -> float:
    """根据窗口尺寸相对设计稿参考尺寸计算缩放系数，并夹在 [MIN, MAX]。"""
    if width <= 0 or height <= 0:
        return 1.0
    s = min(width / FONT_REF_W, height / FONT_REF_H)
    return max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, s))


# ============================================================
# 几何缩放 (Quinn 2026-08-25 15:30 反馈：1/4 窗口下卡片文字重叠)
# ============================================================
# 设计原则：所有最小/固定高度、列宽、间距、边距都按 FONT_SCALE 同步缩放，
# 让「盒子」和「文字」一起变小，永不重叠溢出。基准值为设计稿 (FONT_SCALE=1.0) 像素。
_SCALE_REGISTRY: list[tuple] = []   # (weakref(widget), base_min_h, base_max_h, base_fixed_h, base_fixed_w)


def scaled(px: int | float | None, floor: int = 6) -> int:
    """把设计稿像素值按当前 FONT_SCALE 缩放，并保底 floor 像素。"""
    if px is None:
        return 0
    return max(floor, int(round(float(px) * FONT_SCALE)))


def register_scaled_geometry(
    widget,
    base_min_h: int | None = None,
    base_max_h: int | None = None,
    base_fixed_h: int | None = None,
    base_fixed_w: int | None = None,
    base_max_w: int | None = None,
    base_min_w: int | None = None,
) -> None:
    """注册 widget 的基准几何值（缩放前），供 FONT_SCALE 变化时重算。"""
    import weakref
    try:
        ref = weakref.ref(widget)
    except TypeError:
        return
    _SCALE_REGISTRY.append((ref, base_min_h, base_max_h, base_fixed_h, base_fixed_w, base_max_w, base_min_w))
    # 立即应用一次
    _apply_one(ref, base_min_h, base_max_h, base_fixed_h, base_fixed_w, base_max_w, base_min_w)


def _apply_one(ref, base_min_h, base_max_h, base_fixed_h, base_fixed_w, base_max_w, base_min_w) -> None:
    w = ref()
    if w is None:
        return
    try:
        if base_min_h is not None and base_min_h > 0:
            w.setMinimumHeight(scaled(base_min_h))
        if base_max_h is not None and 0 < base_max_h < 16_777_215:
            w.setMaximumHeight(scaled(base_max_h))
        if base_fixed_h is not None and base_fixed_h > 0:
            w.setFixedHeight(scaled(base_fixed_h))
        if base_fixed_w is not None and base_fixed_w > 0:
            w.setFixedWidth(scaled(base_fixed_w))
        if base_max_w is not None and 0 < base_max_w < 16_777_215:
            w.setMaximumWidth(scaled(base_max_w))
        if base_min_w is not None and base_min_w > 0:
            w.setMinimumWidth(scaled(base_min_w))
    except RuntimeError:
        pass


def rescale_all_geometries() -> None:
    """FONT_SCALE 变化后，重算所有已注册 widget 的几何尺寸。"""
    alive: list[tuple] = []
    for entry in _SCALE_REGISTRY:
        ref, bmh, bMh, bfh, bfw, bmw, bmW = entry
        if ref is None:
            continue
        w = ref()
        if w is None:
            continue
        _apply_one(ref, bmh, bMh, bfh, bfw, bmw, bmW)
        alive.append(entry)
    _SCALE_REGISTRY[:] = alive


def clear_scale_registry() -> None:
    """测试/重建场景下清空注册表。"""
    _SCALE_REGISTRY.clear()


# 便捷包装：缩放 + 注册基准值（用于 setMinimumHeight / setMaximumHeight / setFixedHeight）
def min_h(widget, base: int, floor: int = 6) -> None:
    """setMinimumHeight (按 FONT_SCALE 缩放) 并注册基准值供后续 rescale。"""
    widget.setMinimumHeight(scaled(base, floor=floor))
    register_scaled_geometry(widget, base_min_h=base)


def min_w(widget, base: int, floor: int = 6) -> None:
    """setMinimumWidth (按 FONT_SCALE 缩放) 并注册基准值供后续 rescale。"""
    widget.setMinimumWidth(scaled(base, floor=floor))
    register_scaled_geometry(widget, base_min_w=base)


def max_h(widget, base: int, floor: int = 6) -> None:
    """setMaximumHeight (按 FONT_SCALE 缩放) 并注册基准值供后续 rescale。"""
    widget.setMaximumHeight(scaled(base, floor=floor))
    register_scaled_geometry(widget, base_max_h=base)


def fixed_h(widget, base: int, floor: int = 6) -> None:
    """setFixedHeight (按 FONT_SCALE 缩放) 并注册基准值供后续 rescale。"""
    widget.setFixedHeight(scaled(base, floor=floor))
    register_scaled_geometry(widget, base_fixed_h=base)


def fixed_w(widget, base: int, floor: int = 6) -> None:
    """setFixedWidth (按 FONT_SCALE 缩放) 并注册基准值供后续 rescale。"""
    widget.setFixedWidth(scaled(base, floor=floor))
    register_scaled_geometry(widget, base_fixed_w=base)


def max_w(widget, base: int, floor: int = 6) -> None:
    """setMaximumWidth (按 FONT_SCALE 缩放) 并注册基准值供后续 rescale。"""
    widget.setMaximumWidth(scaled(base, floor=floor))
    register_scaled_geometry(widget, base_max_w=base)


def recommended_window_size() -> tuple[int, int]:
    """主显示器 1/4 大小（半宽 × 半高），最小兜底 640×420。"""
    from PySide6.QtWidgets import QApplication
    screen = QApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        w, h = geo.width(), geo.height()
    else:
        w, h = 1280, 800
    return (max(640, w // 2), max(420, h // 2))


# Form / Window
FORM = {
    "width":   1680,
    "height":  1040,
    "sidebar_width": 220,
    "sidebar_item_height": 48,    # 44→48
    "min_window_width": 1480,     # 1440→1480
    "min_window_height": 900,     # 880→900
}

# v2 新增: 排版 token (Quinn 14:08 反馈)
ROW_HEIGHT = {
    "sm":   20,   # xs label (24→20)
    "md":   24,   # sm data (28→24)
    "lg":   28,   # lg title (32→28)
    "xl":   32,   # xl header (38→32)
}

CARD_PAD = {
    "inner":   14,  # 20→14: card body padding (Quinn 09:00 三轮: 全屏无滚动)
    "inner_lr": 20,  # 24→20
    "row_gap":  8,   # 14→8: row gap
    "col_gap": 16,   # 18→16
}

# 深色主题: 阴影在黑底不可见, 卡片层次主要靠 border 勾边; 保留极弱阴影无副作用
CARD_SHADOW = "0 1px 2px rgba(0,0,0,0.5)"

STATUS_COLORS = {
    "running":     "success",
    "loading":     "warning",
    "stopped":     "text_muted",
    "error":       "danger",
    "failed":      "danger",  # Quinn T1-D: backend start ok 但 health_reachable=False
    "online":      "success",
    "offline":     "text_muted",
    "connected":   "success",
    "disconnected":"danger",
}


def color(name: str) -> str:
    if name not in COLORS:
        raise KeyError(f"unknown color: {name}")
    return COLORS[name]


def radius(name: str) -> int:
    if name not in RADIUS:
        raise KeyError(f"unknown radius: {name}")
    return RADIUS[name]


def space(name: str) -> int:
    if name not in SPACE:
        raise KeyError(f"unknown space: {name}")
    return SPACE[name]


def row_height(name: str) -> int:
    if name not in ROW_HEIGHT:
        raise KeyError(f"unknown row_height: {name}")
    return ROW_HEIGHT[name]


def card_pad(name: str) -> int:
    if name not in CARD_PAD:
        raise KeyError(f"unknown card_pad: {name}")
    return CARD_PAD[name]


def status_color(state: str) -> str:
    return STATUS_COLORS.get(state, "text_muted")
