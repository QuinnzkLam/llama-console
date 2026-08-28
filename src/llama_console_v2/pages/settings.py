"""
Settings 页 v2 - 重构 (Quinn 17:30 反馈):
- 原来 4 张卡 (模型选择 / 启动参数 / 版本 / 构建状态) → 重构为 2 张:
  1) 「运行环境」大卡: 含 模型选择 / llama-server 版本 / 构建状态 三段(用 QFrame section 分隔)
  2) 「启动参数」卡: 启动参数文本 + 按钮 (高度够, 按钮不被输入框覆盖)

v3 (Quinn 17:30):
- 启动参数卡: QPlainTextEdit min_h 240 + stretch=1, 按钮行位于底部永远可见
- 运行环境卡: 横向 3 sections (模型选择 / 版本 / 构建) 用横向 HBox 排列

v4 (Quinn 11:35):
- 启动参数改 JSON 格式: 每项有 name/key/description/default, 编辑器带中文注释
- 后端用 JSON dict 启动, 启动参数 " -- " 前缀, 后端在 start() 展平为 cmdline
- 提供「恢复默认」按钮 (走 schema 默认值)

v5 (Quinn 12:00):
- key 简写不带 "--" (用户写 "temp" 而非 "--temp"), 后端启动自动加回 "--".
- 启动参数编辑器 4 颜色语法高亮: key=primary(青加粗), value=success(绿), 标点=warning(黄), comment=secondary(灰斜体).
- 修复窗口挤压: cmdline_edit 改 Preferred/Preferred + min 200/max 420, 按钮 SizePolicy Fixed 40px 永不被压.
"""
import json
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget,
)
from PySide6.QtGui import QFont

from llama_console_v2 import theme as t
from llama_console_v2.widgets.card import Card
from llama_console_v2.widgets.buttons import PrimaryButton, OutlineButton
from llama_console_v2.widgets.json_highlighter import CmdlineJsonHighlighter
from llama_console_v2.widgets.page_chrome import PageHeader
from llama_console_v2.backend import llama_cpp as backend_llama


# ============================================================
# 排版工具 (与 console.py 一致)
# ============================================================
def _font(point_size: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setPointSize(point_size)
    f.setBold(bold)
    return f


def _label(text: str, kind: str = "body", bold: bool = False, color: str = "text_primary",
           word_wrap: bool = False) -> QLabel:
    """Quinn 17:30: 默认 word_wrap, 与 console.py 行为一致."""
    lbl = QLabel(text)
    size_map = {
        "title":  t.FONT_SIZE["lg"],
        "subtitle": t.FONT_SIZE["xs"],
        "value": t.FONT_SIZE["base"],
        "muted": t.FONT_SIZE["xs"],
        "info":  t.FONT_SIZE["xs"],
    }
    lbl.setFont(_font(size_map.get(kind, t.FONT_SIZE["base"]), bold))
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        f"color: {t.color(color)}; background: transparent; border: none;"
    )
    return lbl


# ============================================================
# Section 分隔组件 (运行环境卡内部用)
# ============================================================
def _vline(width: int = 1) -> QFrame:
    """垂直分隔线（运行环境卡 sections 之间用）"""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setStyleSheet(f"color: {t.color('border')}; background: transparent;")
    line.setFixedWidth(t.scaled(width))
    return line


def _build_section(
    title: str,
    content: QWidget | None = None,
) -> QWidget:
    """运行环境卡内部 section: 标题 + 内容, 整段为一个 widget."""
    wrapper = QWidget()
    wrapper.setStyleSheet("background: transparent; border: none;")
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(t.scaled(t.space("2")))

    title_lbl = _label(title, "muted", bold=True, color="text_secondary")
    title_lbl.setStyleSheet(
        f"color: {t.color('text_secondary')}; background: transparent;"
        f" border: none; padding-bottom: {t.scaled(2)}px;"
        f" letter-spacing: 0.5px;"
    )
    layout.addWidget(title_lbl)
    if content is not None:
        layout.addWidget(content)
    return wrapper


# ============================================================
# Settings Page
# ============================================================
class SettingsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        self.setStyleSheet("background: transparent; border: none;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)

        # --- Header ---
        # Quinn 16:55: 关闭 show_online 删除右上角被挤压的状态元素(与 Console 一致)
        self._header = PageHeader("设置", show_online=False)
        outer.addWidget(self._header)

        # --- Body (Quinn 09:00 三轮反馈: 删 QScrollArea + PageFooter "设置", 全屏不滚动) ---
        body = QWidget()
        body.setObjectName("SettingsBody")
        body.setStyleSheet("background: transparent; border: none;")
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addWidget(body, 1)

        margin = QVBoxLayout(body)
        margin.setContentsMargins(
            t.scaled(t.card_pad("inner_lr")), t.scaled(t.space("3")),
            t.scaled(t.card_pad("inner_lr")), t.scaled(t.space("3"))
        )
        margin.setSpacing(t.scaled(t.card_pad("col_gap")))
        margin.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)

        # Quinn 17:30: 4 卡 -> 2 卡
        # 1) 运行环境卡 (含 3 sections)
        self._env_card = Card("运行环境", icon="⚙")
        self._build_env_card(self._env_card)
        margin.addWidget(self._env_card, 0)

        # 2) 启动参数卡 (高 -> QPlainTextEdit expanding 填充, 按钮在最下)
        self._params_card = Card("启动参数", icon="📋")
        self._build_params_card(self._params_card)
        margin.addWidget(self._params_card, 1)

        # Quinn 09:00 三轮: 删除 PageFooter("设置") —— 用户图片中"启动参数卡下方"的
        # "设置"独立一行就是它. 直接移除, 改为空 spacer.

        # 初始加载
        self._load_models()
        self._load_cmdline()
        self._load_version()
        self._load_build_status()

    # ========================================================================
    # Card 1: 运行环境 (含 模型选择 / 版本 / 构建状态 3 sections)
    # ========================================================================
    def _build_env_card(self, card: Card) -> None:
        layout = card.body_layout

        # 3 sections 横向排列 (column 在更窄窗口下用 word_wrap 支持)
        sections_row = QHBoxLayout()
        sections_row.setContentsMargins(0, 0, 0, 0)
        sections_row.setSpacing(t.scaled(t.space("5")))
        sections_row.setSizeConstraint(QHBoxLayout.SizeConstraint.SetNoConstraint)

        # --- Section 1: 模型选择 ---
        model_col = QVBoxLayout()
        model_col.setContentsMargins(0, 0, 0, 0)
        model_col.setSpacing(t.scaled(t.space("2")))

        model_title = _label("模型选择", "muted", bold=True, color="text_secondary")
        model_col.addWidget(model_title)

        self._model_combo = QComboBox()
        t.fixed_h(self._model_combo, 40)  # 44→40: 稍小更紧凑
        self._model_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._model_combo.setStyleSheet(self._combo_style())
        model_col.addWidget(self._model_combo)

        self._model_path_lbl = _label("-", "value", color="text_primary", word_wrap=True)
        self._model_path_lbl.setStyleSheet(
            f"color: {t.color('text_secondary')}; background: transparent; border: none;"
        )
        model_col.addWidget(self._model_path_lbl)

        model_col.addStretch(1)
        sec1 = QWidget()
        sec1.setStyleSheet("background: transparent; border: none;")
        sec1.setLayout(model_col)
        # Quinn 17:30: 3 sections 等分(stretch=1)
        sections_row.addWidget(sec1, 1)

        # 垂直分隔
        sections_row.addWidget(_vline(1))

        # --- Section 2: llama-server 版本 ---
        ver_col = QVBoxLayout()
        ver_col.setContentsMargins(0, 0, 0, 0)
        ver_col.setSpacing(t.scaled(t.space("2")))

        ver_title = _label("llama-server 版本", "muted", bold=True, color="text_secondary")
        ver_col.addWidget(ver_title)

        # 当前版本 (大字号)
        self._current_ver_lbl = _label("查询中...", "value", bold=True,
                                        color="text_primary")
        ver_col.addWidget(self._current_ver_lbl)

        # 最新版本 (带颜色提示)
        latest_row = QHBoxLayout()
        latest_row.setContentsMargins(0, 0, 0, 0)
        latest_row.setSpacing(t.scaled(t.space("2")))
        latest_lbl = _label("最新", "muted", color="text_secondary")
        latest_row.addWidget(latest_lbl)
        self._latest_ver_lbl = _label("-", "value", bold=True, color="info")
        latest_row.addWidget(self._latest_ver_lbl)
        latest_row.addStretch(1)
        ver_col.addLayout(latest_row)

        # 检查更新按钮
        self._check_update_btn = OutlineButton("检查更新", icon_char="🔄")
        t.min_h(self._check_update_btn, 36)
        self._check_update_btn.clicked.connect(self._on_check_update)
        ver_col.addWidget(self._check_update_btn)

        ver_col.addStretch(1)
        sec2 = QWidget()
        sec2.setStyleSheet("background: transparent; border: none;")
        sec2.setLayout(ver_col)
        sections_row.addWidget(sec2, 1)

        # 垂直分隔
        sections_row.addWidget(_vline(1))

        # --- Section 3: 构建状态 ---
        status_col = QVBoxLayout()
        status_col.setContentsMargins(0, 0, 0, 0)
        status_col.setSpacing(t.scaled(t.space("2")))

        status_title = _label("构建状态", "muted", bold=True, color="text_secondary")
        status_col.addWidget(status_title)

        # 二进制路径 (短)
        self._exe_path_lbl = _label("-", "value", color="text_primary")
        self._exe_path_lbl.setWordWrap(True)
        self._exe_path_lbl.setStyleSheet(
            f"color: {t.color('text_primary')}; background: transparent;"
            f" border: none; font-family: {t.FONT_FAMILY_MONO};"
        )
        status_col.addWidget(self._exe_path_lbl)

        # 二进制状态 + 模型目录
        self._build_state_lbl = _label("-", "muted", color="text_secondary")
        status_col.addWidget(self._build_state_lbl)
        self._model_dir_lbl = _label("-", "muted", color="text_secondary")
        self._model_dir_lbl.setWordWrap(True)
        status_col.addWidget(self._model_dir_lbl)

        status_col.addStretch(1)
        sec3 = QWidget()
        sec3.setStyleSheet("background: transparent; border: none;")
        sec3.setLayout(status_col)
        sections_row.addWidget(sec3, 1)

        layout.addLayout(sections_row)

    # ========================================================================
    # Card 2: 启动参数 (JSON + 注释 + 按钮, 按钮永远不被覆盖)
    # Quinn 12:00: key 不带 "--" 前缀 (用户简洁写), 后端 start() 自动加回.
    # 4 颜色语法高亮: key(青加粗) / value(绿) / 标点(黄) / comment(灰斜体).
    # ========================================================================
    def _build_params_card(self, card: Card) -> None:
        layout = card.body_layout

        # 描述 (提示 JSON + 注释格式 + key 简洁 + 后端自动加 --)
        desc_lbl = _label(
            "JSON 格式启动参数 (key 形如 temp, 后端 start() 自动加 -- 展平为 cmdline)",
            "muted", color="text_secondary",
        )
        layout.addWidget(desc_lbl)

        # 配置文件路径提示
        cfg_hint = _label(
            f"配置文件: {backend_llama._CMDLINE_FILE}",
            "muted", color="text_muted",
        )
        cfg_hint_font = QFont()
        cfg_hint_font.setPointSize(t.FONT_SIZE["xs"] - 1)
        cfg_hint.setFont(cfg_hint_font)
        cfg_hint.setStyleSheet(
            f"color: {t.color('text_muted')}; background: transparent; border: none;"
            f" font-family: {t.FONT_FAMILY_MONO};"
        )
        layout.addWidget(cfg_hint)

        # Quinn 12:00: 参数输入框 - Preferred/Preferred + min 200/max 360 + stretch=1
        # 让输入框在矮窗口下能被压缩到合理高度, 不会强行撑高卡牌挤压其他元素
        self._cmdline_edit = QPlainTextEdit()
        # min/max_h 给个浮动范围, 让卡牌在窗口高度变化时各 widget 各得其所
        t.min_h(self._cmdline_edit, 200, floor=140)
        # Preferred/Preferred: 输入框在 stretch=1 时优先拿空间; 但垂直高度受 max 约束
        self._cmdline_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._cmdline_edit.setMaximumHeight(t.scaled(420, floor=360))
        self._cmdline_edit.setReadOnly(False)
        self._cmdline_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._cmdline_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._cmdline_edit.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background-color: {t.color('input')};
                color: {t.color('text_primary')};
                border: 1px solid {t.color('border')};
                border-radius: {t.radius('md')}px;
                padding: {t.scaled(12)}px {t.scaled(14)}px;
                font-family: {t.FONT_FAMILY_MONO};
                font-size: {t.FONT_SIZE['sm']}pt;
                selection-background-color: {t.color('primary')};
                selection-color: {t.color('text_on_primary')};
            }}
            QPlainTextEdit:focus {{
                border-color: {t.color('primary')};
            }}
            """
        )
        # stretch=1 让输入框撑垂直空间, 但受 max 约束不会被无限制扩张
        layout.addWidget(self._cmdline_edit, 1)

        # 状态行 (保存结果提示)
        self._params_status_lbl = _label("", "muted", color="text_secondary")
        self._params_status_lbl.setWordWrap(True)
        self._params_status_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        t.min_h(self._params_status_lbl, 18, floor=16)
        layout.addWidget(self._params_status_lbl)

        # Quinn 12:00: 按钮行 fixed_h 40 + stretch=0 + SizePolicy(Minimum, Preferred):
        #   total 卡牌高度不够时按钮保证有 40px (不会被压扁), 但允许被隐藏式截断 (罕见)
        #   真正深度挤压发生在窗口高度 < 720 时, 之前测试 840×520 窗口仍有遮挡;
        #   改为按钮 VerticalPolicy=Fixed, 永远 40px, 不被挤。
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(t.scaled(t.space("3")))
        self._save_btn = PrimaryButton("保存参数", icon_char="💾")
        self._reset_btn = OutlineButton("恢复默认", icon_char="↻")
        t.fixed_h(self._save_btn, 40)
        t.fixed_h(self._reset_btn, 40)
        self._save_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._reset_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._save_btn.clicked.connect(self._on_save)
        self._reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._reset_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row, 0)  # stretch=0 固定高度不被压

        # Quinn 12:00: 语法高亮器 (4 颜色 — key/value/json 标点/comment)
        self._highlighter = CmdlineJsonHighlighter(
            self._cmdline_edit.document(),
            key_color=t.color("primary"),     # cyan, bold
            value_color=t.color("success"),    # green
            punct_color=t.color("warning"),    # yellow
            comment_color=t.color("text_secondary"),  # gray, italic
        )

    def _combo_style(self) -> str:
        return f"""
        QComboBox {{
            background-color: {t.color('input')};
            color: {t.color('text_primary')};
            border: 1px solid {t.color('border')};
            border-radius: {t.radius('md')}px;
            padding: 0 {t.scaled(14)}px;
            font-size: {t.FONT_SIZE['sm']}pt;
        }}
        QComboBox:hover {{
            border-color: {t.color('primary')};
        }}
        QComboBox:focus {{
            border-color: {t.color('primary')};
        }}
        QComboBox::drop-down {{
            border: none;
            width: {t.scaled(28)}px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: {t.scaled(4)}px solid transparent;
            border-right: {t.scaled(4)}px solid transparent;
            border-top: {t.scaled(6)}px solid {t.color('text_secondary')};
            margin-right: {t.scaled(8)}px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {t.color('card_hover')};
            color: {t.color('text_primary')};
            border: 1px solid {t.color('border')};
            border-radius: {t.radius('md')}px;
            padding: {t.scaled(4)}px;
            selection-background-color: {t.color('primary')};
            selection-color: {t.color('text_on_primary')};
            outline: 0;
        }}
        """

    # ========================================================================
    # Data loaders
    # ========================================================================
    def _load_models(self) -> None:
        try:
            models = backend_llama.list_models()
            self._model_combo.clear()
            for m in models:
                self._model_combo.addItem(m)
            if models:
                self._model_combo.setCurrentIndex(0)
                path = backend_llama.current_model_path()
                # 缩短路径: 只显最后一段目录 + 文件名
                if path:
                    from pathlib import Path
                    p = Path(path)
                    short = f"{'..' if len(str(p.parent)) > 40 else str(p.parent)}/{p.name}"
                    self._model_path_lbl.setText(short)
                else:
                    self._model_path_lbl.setText("-")
        except Exception as e:  # noqa: BLE001
            self._model_path_lbl.setText(f"加载模型失败: {e}")

    def _load_cmdline(self) -> None:
        """加载 JSON 配置 + 渲染为「带中文注释的 JSON 编辑文本」.

        Quinn 11:35: 编辑器内容格式:
            {
                "--temp": 0.6,        // 温度系数
                "--top-p": 0.95,      // Top-P
                ...
            }
        """
        try:
            data = backend_llama.load_cmdline_args_dict()
        except Exception as e:  # noqa: BLE001
            self._cmdline_edit.setPlainText(f"// 加载失败: {e}")
            return
        self._cmdline_edit.setPlainText(self._render_json_with_comments(data))

    def _render_json_with_comments(self, data: dict) -> str:
        """把 dict 渲染为「带中文注释的 JSON」, 每项 name/description."""
        schema = backend_llama.get_cmdline_schema()
        meta = {item["key"]: item for item in schema}
        lines: list[str] = ["{"]
        items: list[str] = []
        for key, val in data.items():
            comment_parts: list[str] = []
            if key in meta:
                m = meta[key]
                if m.get("name"):
                    comment_parts.append(m["name"])
                if m.get("description"):
                    comment_parts.append(m["description"])
            if isinstance(val, bool):
                val_str = "true" if val else "false"
            elif val is None:
                val_str = "null"
            elif isinstance(val, (int, float)):
                val_str = repr(val) if isinstance(val, float) else str(val)
            else:
                # str 加双引号 + 转义
                val_str = json.dumps(str(val), ensure_ascii=False)
            line = f'  {json.dumps(key, ensure_ascii=False)}: {val_str}'
            if comment_parts:
                line += f"  // {comment_parts[0]}"
                if len(comment_parts) > 1:
                    line += f" — {comment_parts[1]}"
            items.append(line)
        lines.append(",\n".join(items))
        lines.append("\n}")
        return "\n".join(lines)

    def _parse_json_with_comments(self, text: str) -> dict:
        """从「带注释的 JSON 文本」解析 dict, 跳过 // 行尾注释 + 顶部说明行.

        兼容: 单引号 (转双引号) + 末尾多余逗号 (JSON5 风格).
        """
        cleaned: list[str] = []
        for line in text.splitlines():
            # 去除 // 后注释 (但保留字符串内的 //)
            in_str = False
            in_single = False
            escape = False
            cut = len(line)
            for i, ch in enumerate(line):
                if escape:
                    escape = False
                    continue
                if ch == "\\" and (in_str or in_single):
                    escape = True
                    continue
                if ch == '"' and not in_single:
                    in_str = not in_str
                    continue
                if ch == "'" and not in_str:
                    in_single = not in_single
                    continue
                if not in_str and not in_single and ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                    cut = i
                    break
            stripped = line[:cut].rstrip()
            if stripped.strip():
                cleaned.append(stripped)
        json_text = "\n".join(cleaned)
        # 单引号 → 双引号 (JSON 标准要求双引号, 但用户手编可能用单引号)
        json_text = json_text.replace("'", '"')
        # 去掉末尾多余逗号 (,] -> ], ,} -> })
        json_text = re.sub(r",(\s*[\]}])", r"\1", json_text)
        return json.loads(json_text)

    def _load_version(self) -> None:
        try:
            v = backend_llama.get_version()
            self._current_ver_lbl.setText(v or "-")
        except Exception as e:  # noqa: BLE001
            self._current_ver_lbl.setText(f"查询失败: {e}")

    def _load_build_status(self) -> None:
        """加载 exe 路径 / 构建状态 / 模型目录."""
        from pathlib import Path
        # exe 路径
        exe = backend_llama.get_llama_server_exe()
        if exe is not None:
            self._exe_path_lbl.setText(str(exe.name))
            # 构建状态
            ver = backend_llama.get_current_version()
            if ver == "not built":
                self._build_state_lbl.setText("未构建")
            else:
                self._build_state_lbl.setText(f"已构建 · {ver}")
        else:
            self._exe_path_lbl.setText("未找到")
            self._build_state_lbl.setText("未就绪")
        # 模型目录
        models_dir = Path("D:/llama-console/models")
        if models_dir.is_dir():
            try:
                count = len([f for f in models_dir.rglob("*.gguf") if "mmproj" not in f.name.lower()])
                self._model_dir_lbl.setText(f"{models_dir} · {count} 个模型")
            except Exception:
                self._model_dir_lbl.setText(str(models_dir))
        else:
            self._model_dir_lbl.setText("目录不存在")

    # ========================================================================
    # Actions
    # ========================================================================
    def _on_save(self) -> None:
        """解析带注释 JSON → 校验 → 写 JSON 配置文件.

        Quinn 11:35: 校验失败显红色提示, 不破坏原文件.
        """
        text = self._cmdline_edit.toPlainText()
        try:
            data = self._parse_json_with_comments(text)
        except json.JSONDecodeError as e:
            self._set_params_status(f"✗ JSON 解析失败: {e.msg} (行 {e.lineno}, 列 {e.colno})", danger=True)
            return
        except Exception as e:  # noqa: BLE001
            self._set_params_status(f"✗ 解析失败: {e}", danger=True)
            return
        # 类型校验 (对照 schema)
        ok, err = backend_llama.validate_cmdline_args_dict(data)
        if not ok:
            self._set_params_status(f"✗ 校验失败: {err}", danger=True)
            return
        try:
            backend_llama.save_cmdline_args_dict(data)
        except Exception as e:  # noqa: BLE001
            self._set_params_status(f"✗ 保存失败: {e}", danger=True)
            return
        self._set_params_status(
            f"✓ 参数已保存到 {backend_llama._CMDLINE_FILE}", success=True
        )

    def _on_reset(self) -> None:
        """重置为 schema 默认, 同时刷新编辑器内容."""
        try:
            data = backend_llama.reset_cmdline_args_dict()
        except Exception as e:  # noqa: BLE001
            self._set_params_status(f"✗ 重置失败: {e}", danger=True)
            return
        self._cmdline_edit.setPlainText(self._render_json_with_comments(data))
        self._set_params_status("✓ 已重置为默认参数", success=True)

    def _set_params_status(self, text: str, success: bool = False, danger: bool = False) -> None:
        if success:
            color = "success"
        elif danger:
            color = "danger"
        else:
            color = "text_secondary"
        self._params_status_lbl.setText(text)
        self._params_status_lbl.setStyleSheet(
            f"color: {t.color(color)}; background: transparent; border: none;"
        )

    def _on_check_update(self) -> None:
        self._latest_ver_lbl.setText("检查中...")
        try:
            latest = backend_llama.check_latest_version()
            if latest:
                self._latest_ver_lbl.setText(latest)
            else:
                self._latest_ver_lbl.setText("无法查询")
        except Exception as e:  # noqa: BLE001
            self._latest_ver_lbl.setText(f"查询失败: {e}")
