"""
JSON 启动参数自定义语法高亮
============================
- key (青 primary 加粗):  形如 `"temp":` / `"top-p":`
- value (绿 success):     数字 / true / false / null
- string value (绿 success): `"..."`
- json 标点 (黄 warning):   `{ } [ ] , :`
- comment (灰 text_secondary italic): `// ...`

Quinn 12:00: 解决用户在设置页 JSON 编辑器中看不清"键/值/注释"的痛点.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import (
    QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument,
)


# ============================================================
# 4 类语法元素的 QTextCharFormat 工厂
# ============================================================
class _FormatFactory:
    """从 theme 颜色构造 4 类格式 (key / value / punctuation / comment)."""

    def __init__(
        self,
        key_color: str,
        value_color: str,
        punct_color: str,
        comment_color: str,
        font_family: str = "",
    ) -> None:
        self.key_fmt = self._fmt(key_color, bold=True, italic=False)
        self.value_fmt = self._fmt(value_color, bold=False, italic=False)
        self.punct_fmt = self._fmt(punct_color, bold=False, italic=False)
        self.comment_fmt = self._fmt(comment_color, bold=False, italic=True)

    @staticmethod
    def _fmt(color_hex: str, bold: bool, italic: bool) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(QColor(color_hex))
        f.setFontItalic(italic)
        if bold:
            f.setFontWeight(QFont.Weight.DemiBold)
        return f


# ============================================================
# 高亮器
# ============================================================
class CmdlineJsonHighlighter(QSyntaxHighlighter):
    """在 QPlainTextEdit 上挂的 JSON 语法高亮器.

    模式 (基于 Python re):
      1. "//..."          -> comment_fmt (灰斜体, 直至行尾)
      2. "...":           -> key_fmt     (青色加粗)
      3. "..."            -> string value (绿色, 在 value 位置)
      4. r"-?\\d+(\\.\\d+)?"    -> number value
      5. true|false|null  -> literal value
      6. r"[{}()[\\],:]"     -> punctuation

    顺序很重要 — comment 优先, 避免行尾 `// \"key\":...` 误识别.
    """

    # 注释: // 到行尾 (注意 — 我们没法在这里用 \\E\\K 类, 纯 Python re 即可)
    _RE_COMMENT = re.compile(r"//[^\n]*")
    # key: "..." 后跟 (空白 + ":")
    _RE_KEY = re.compile(r'"([^"\\]|\\.)*"\s*(?=:)')
    # string value: 形如 "<text>"
    _RE_STRING = re.compile(r'"([^"\\]|\\.)*"')
    # 数字 / bool / null 字面量
    _RE_NUMBER = re.compile(r"\b-?\d+(\.\d+)?\b")
    _RE_LITERAL = re.compile(r"\b(true|false|null)\b")
    # 标点
    _RE_PUNCT = re.compile(r"[\{\}\[\],:]")

    def __init__(
        self,
        document: QTextDocument,
        key_color: str,
        value_color: str,
        punct_color: str,
        comment_color: str,
    ) -> None:
        super().__init__(document)
        self._ff = _FormatFactory(
            key_color=key_color,
            value_color=value_color,
            punct_color=punct_color,
            comment_color=comment_color,
        )
        self._last_doc = document

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt API)
        # 1) comment 先应用, 把行尾遮住避免其他规则误触
        for m in self._RE_COMMENT.finditer(text):
            start, end = m.span()
            self.setFormat(start, end - start, self._ff.comment_fmt)
            # comment 之后的内容不再高亮 (Qt 的 setFormat 用 OR 行为, 可以分层叠加;
            # 但视觉上 comment 后我们统一为 comment 色, 模糊了字符串/标点 — 这是设计选择:
            # JSON 配置里合法的语法段不该出现在注释后, 安全)

        # 2) key (青色): "...:":  注意我们直接高亮到 ":"前
        #    但 key 末端的引号属于 key; ":" 单独算 punctuation
        #    简化做法: 用 lookbehind/highlight 整段 key + 后补空白
        for m in self._RE_KEY.finditer(text):
            start, end = m.span()
            # 仅高亮不含 trailing 空白
            self.setFormat(start, end - start, self._ff.key_fmt)

        # 3) punctuation 单独再上色 (覆盖 key 范围内的 ":"? 不, key 正则用 (?=:) 不含 ":")
        for m in self._RE_PUNCT.finditer(text):
            start, end = m.span()
            # 仅当该字符未被 comment 渲染, 用 currentBlockState 区分
            # 简化: 全部染色 — ":" 在 key_fmt 之后独立染色即可 (overwrite)
            self.setFormat(start, end - start, self._ff.punct_fmt)

        # 4) string 值 (绿色): 是 "..." 但不在 key 范围. 因为 key 正则已经覆盖 "...""
        #    我们的 _RE_STRING 是独立正则, 会在 key 范围被重新染成 value (绿色)
        #    这破坏了视觉, 所以必须让 value 仅高亮 key 范围外的内容:
        #    用 negative lookbehind (?<!"): " 之前的 1 字符不是 "
        #    改写: 跳过在 key 范围的所有 string
        already_key_ranges = [m.span() for m in self._RE_KEY.finditer(text)]
        for m in self._RE_STRING.finditer(text):
            s, e = m.span()
            if any(ks <= s and e <= ke for ks, ke in already_key_ranges):
                continue
            self.setFormat(s, e - s, self._ff.value_fmt)

        # 5) number 字面量
        for m in self._RE_NUMBER.finditer(text):
            s, e = m.span()
            self.setFormat(s, e - s, self._ff.value_fmt)

        # 6) bool / null
        for m in self._RE_LITERAL.finditer(text):
            s, e = m.span()
            self.setFormat(s, e - s, self._ff.value_fmt)
