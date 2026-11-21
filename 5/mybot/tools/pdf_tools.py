"""PDF 解析工具模块：提取文本与表格，并还原「列内缩进层级」的树形表格为 Markdown。"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult

# 单个工具返回内容的最大字符数
MAX_OUTPUT_CHARS = 40_000
# 默认返回的最大字符数
DEFAULT_MAX_CHARS = 20_000
# 单次最多解析的页数（防止一次调用输出爆炸）
MAX_PAGES_PER_CALL = 30
# 单个表格最多渲染的行数与列数
MAX_TABLE_ROWS = 200
MAX_TABLE_COLS = 30
# 判定「有缩进」的最小前导偏移（pt）
INDENT_EPSILON = 1.5
# 同一层级的聚类容差（pt）：相邻偏移差小于此值视为同一层
INDENT_CLUSTER_TOLERANCE = 3.0
# 单元格内层级用全角空格表示，避免 Markdown 渲染时被折叠
INDENT_UNIT = "\u3000"

# 单元格文本超过该长度即认为「不是数据表格单元格，而是一整段散文」
MAX_PROSE_CELL_CHARS = 200

# 表格检测策略：先用框线（lines），某页检不出表格时再用文字对齐（text）兜底
_LINES_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
_TEXT_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text"}

# pdfminer 的已知无害噪音：字体描述符缺少 FontBBox 时打的 WARNING。
# Web/HTML 导出的 PDF 常把同一字体重复嵌入成多个字体对象，导致该警告刷屏；
# pdfminer 内部会用 (0,0,0,0) 兜底继续解析，且普通 TrueType 字体并不依赖
# FontBBox（只有 Type3 字体会用它推导 ascent/descent），故对解析结果无影响。
_PDFMINER_NOISE_MARKER = "Could not get FontBBox from font descriptor"
_pdfminer_noise_filter_installed = False


class _PdfminerNoiseFilter(logging.Filter):
    """只丢弃 pdfminer 中「FontBBox 缺失」这一条已知无害的警告，其余照常输出。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """返回 False 表示丢弃该日志记录。

        参数:
            record: 日志记录。

        返回:
            True 表示放行，False 表示丢弃。
        """
        try:
            message = record.getMessage()
        except Exception:
            return True
        return _PDFMINER_NOISE_MARKER not in message


def _silence_pdfminer_noise() -> None:
    """为 pdfminer 的字体日志器装上去噪过滤器（进程内只装一次）。

    注意：Python 的日志过滤只在「产生该记录的那个 logger」上生效——记录向上
    传播到父 logger 时不会再经过父 logger 的 filters。因此过滤器必须挂在真正
    打日志的 ``pdfminer.pdffont`` 上，挂到父级 ``pdfminer`` 是无效的。
    """
    global _pdfminer_noise_filter_installed
    if _pdfminer_noise_filter_installed:
        return
    logging.getLogger("pdfminer.pdffont").addFilter(_PdfminerNoiseFilter())
    _pdfminer_noise_filter_installed = True


class PdfParseTool(Tool):
    """PDF 解析工具：把 PDF 的文字与表格提取成 Markdown。"""

    @property
    def name(self) -> str:
        return "pdf_parse"

    @property
    def description(self) -> str:
        return (
            "解析 PDF 文件，提取正文与表格文本。"
            "表格会还原为 Markdown 表格；若某一列用缩进表示层级（如组织架构、目录树、BOM 物料清单），"
            "会用全角空格前缀保留层级关系。"
            "仅支持带文本层的 PDF（能选中文字），不支持扫描件/图片型 PDF。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "PDF 文件路径"},
                "pages": {
                    "type": "string",
                    "description": (
                        f"页码范围，如 '1-3' 或 '2'；不填表示全部（最多 {MAX_PAGES_PER_CALL} 页）"
                    ),
                },
                "max_chars": {
                    "type": "integer",
                    "description": f"返回内容的最大字符数，默认 {DEFAULT_MAX_CHARS}",
                },
            },
            "required": ["path"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        """解析 PDF。

        参数:
            **kwargs: 必须包含 path（str），可选 pages（str）、max_chars（int）。

        返回:
            ToolResult，content 为 Markdown 化的正文与表格；文件不存在、
            非 PDF、页码越界或解析失败时为错误结果。
        """
        # 1) 入参校验
        raw_path = str(kwargs.get("path", "")).strip()
        if not raw_path:
            return ToolResult.error("错误：path 不能为空。")
        pdf_path = Path(raw_path).expanduser()
        if pdf_path.suffix.lower() != ".pdf":
            return ToolResult.error(f"错误：不是 PDF 文件（需要 .pdf 后缀）：{raw_path}")
        if not pdf_path.exists():
            return ToolResult.error(f"错误：文件不存在：{pdf_path}")
        if not pdf_path.is_file():
            return ToolResult.error(f"错误：路径不是文件：{pdf_path}")

        max_chars = int(kwargs.get("max_chars", DEFAULT_MAX_CHARS) or DEFAULT_MAX_CHARS)
        max_chars = max(500, min(max_chars, MAX_OUTPUT_CHARS))

        # 2) 懒加载依赖：未安装时不影响 Agent 其他功能
        _silence_pdfminer_noise()
        try:
            import pdfplumber
        except ImportError as exc:
            return ToolResult.error(
                f"错误：缺少依赖 pdfplumber（{exc}）。请运行：pip install -r requirements.txt"
            )

        # 3) 打开并解析
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                total_pages = len(pdf.pages)
                if total_pages == 0:
                    return ToolResult.error(f"错误：PDF 没有任何页面：{pdf_path}")

                try:
                    start, end = self._parse_page_range(kwargs.get("pages"), total_pages)
                except ValueError as exc:
                    return ToolResult.error(f"错误：{exc}")

                page_clipped = end - start + 1 < self._requested_count(kwargs.get("pages"), total_pages)

                chunks: list[str] = []
                extracted_anything = False
                for page_index in range(start - 1, end):
                    page = pdf.pages[page_index]
                    try:
                        body = self._extract_page(page)
                    except Exception as exc:
                        # 单页异常隔离：降级为纯文本，不影响其他页
                        try:
                            body = (page.extract_text() or "").strip()
                        except Exception:
                            body = ""
                        body = (
                            f"{body}\n（本页解析异常，已降级为纯文本：{type(exc).__name__}: {exc}）"
                        ).strip()
                    if body:
                        extracted_anything = True
                    else:
                        body = "（本页无可提取文本）"
                    chunks.append(f"--- 第 {page_index + 1} 页 ---\n\n{body}")

                if not extracted_anything:
                    return ToolResult.error(
                        "错误：未提取到任何文本，可能是扫描件（无文本层），本工具不支持。"
                    )
        except Exception as exc:
            return ToolResult.error(f"错误：无法打开或解析 PDF（{type(exc).__name__}: {exc}）")

        content = "\n\n".join(chunks)
        if page_clipped:
            content = f"（仅解析了第 {start}-{end} 页）\n\n{content}"

        total = len(content)
        if total > max_chars:
            content = (
                content[:max_chars]
                + f"\n...（内容过长，仅显示前 {max_chars} 字符，全文约 {total} 字符）"
            )
        return ToolResult(content=content)

    # ---------- 页码范围 ----------

    @staticmethod
    def _requested_count(spec: Any, total_pages: int) -> int:
        """计算用户请求的页数（未经 MAX_PAGES_PER_CALL 夹取），用于判断是否发生截断。

        参数:
            spec: pages 参数原文。
            total_pages: 文档总页数。

        返回:
            请求的页数。
        """
        text = str(spec or "").strip()
        if not text:
            return total_pages
        try:
            if "-" in text:
                left, _, right = text.partition("-")
                return max(1, int(right) - int(left) + 1)
            return 1
        except ValueError:
            return 1

    @staticmethod
    def _parse_page_range(spec: Any, total_pages: int) -> tuple[int, int]:
        """解析页码范围（1 基），并夹到单次上限。

        参数:
            spec: pages 参数原文，可为空、"2"、"1-3"。
            total_pages: 文档总页数。

        返回:
            (起始页, 结束页)，均为 1 基闭区间。

        异常:
            ValueError: 格式非法或页码越界。
        """
        text = str(spec or "").strip()
        if not text:
            start, end = 1, total_pages
        else:
            try:
                if "-" in text:
                    left, _, right = text.partition("-")
                    start, end = int(left), int(right)
                else:
                    start = end = int(text)
            except ValueError:
                raise ValueError(f"pages 格式非法：{text!r}（应为 '2' 或 '1-3'）") from None

            if start < 1 or end < start:
                raise ValueError(f"pages 范围非法：{text!r}")
            if start > total_pages:
                raise ValueError(f"起始页 {start} 超出范围，该 PDF 共 {total_pages} 页")

        end = min(end, total_pages)
        # 夹到单次解析上限
        if end - start + 1 > MAX_PAGES_PER_CALL:
            end = start + MAX_PAGES_PER_CALL - 1
        return start, end

    # ---------- 单页提取 ----------

    def _extract_page(self, page: Any) -> str:
        """提取一页的正文与表格。

        参数:
            page: pdfplumber 的 Page 对象。

        返回:
            该页的 Markdown 文本（正文 + 表格）；无内容时返回空字符串。
        """
        parts: list[str] = []

        # 先定位表格：既用于渲染，也用于把该区域从正文中排除
        candidates = page.find_tables(table_settings=_LINES_SETTINGS)
        if not candidates:
            # 无框线表格兜底：用文字对齐策略再试一次
            candidates = page.find_tables(table_settings=_TEXT_SETTINGS)

        # 剔除「版式容器」伪表格（如简历/海报的分栏边框），
        # 否则整页散文会被塞进表格单元格，并被误判出虚假的缩进层级
        tables: list[Any] = []
        for candidate in candidates:
            try:
                rows = candidate.extract()
            except Exception:
                continue
            if rows and not self._looks_like_layout_frame(rows):
                tables.append(candidate)

        # 正文：排除表格区域，避免表格内容以「拍平的纯文本」重复出现
        # （拍平的文本会丢失缩进层级，反而干扰模型理解）
        try:
            text = (self._text_excluding_tables(page, tables) or "").strip()
        except Exception:
            text = (page.extract_text() or "").strip()
        if text:
            parts.append(text)

        for table in tables:
            try:
                rendered = self._render_table(page, table)
            except Exception as exc:
                rendered = f"（本页有 1 个表格解析失败：{type(exc).__name__}: {exc}）"
            if rendered:
                parts.append(rendered)

        return "\n\n".join(parts)

    @staticmethod
    def _looks_like_layout_frame(rows: list[list[str | None]]) -> bool:
        """判断检出的「表格」是否其实只是版式容器，而非数据表格。

        简历、海报这类文档常用框线做分栏；它们会被 find_tables 误认为表格。
        两条判据（命中任一即视为版式容器）：

        1. 存在**整列全空**——数据表格不会有一列完全没有内容；
        2. 任一单元格文本超过 ``MAX_PROSE_CELL_CHARS``——说明里面是整段散文。

        参数:
            rows: table.extract() 得到的文本矩阵。

        返回:
            True 表示这更像是版式容器，应当按正文处理。
        """
        if not rows:
            return False
        n_cols = max(len(row) for row in rows)

        # 判据 1：整列全空
        for c in range(n_cols):
            values = [row[c] for row in rows if c < len(row)]
            if values and all(not (value or "").strip() for value in values):
                return True

        # 判据 2：单元格里塞了整段散文
        for row in rows:
            for cell in row:
                if cell and len(str(cell)) > MAX_PROSE_CELL_CHARS:
                    return True

        return False

    @staticmethod
    def _text_excluding_tables(page: Any, tables: list[Any]) -> str:
        """提取表格区域之外的正文文本。

        参数:
            page: pdfplumber 的 Page 对象。
            tables: 本页已检出的表格列表；为空表示整页都是正文。

        返回:
            排除表格文字后的正文。
        """
        if not tables:
            return page.extract_text() or ""

        bboxes = [table.bbox for table in tables]

        def keep(obj: dict[str, Any]) -> bool:
            """保留不在任何表格区域内的字符对象。"""
            if obj.get("object_type") != "char":
                return True
            center_x = (obj["x0"] + obj["x1"]) / 2
            center_y = (obj["top"] + obj["bottom"]) / 2
            for x0, top, x1, bottom in bboxes:
                if x0 <= center_x <= x1 and top <= center_y <= bottom:
                    return False
            return True

        return page.filter(keep).extract_text() or ""

    # ---------- 表格 → Markdown ----------

    @staticmethod
    def _render_table(page: Any, table: Any) -> str:
        """把一个 pdfplumber 表格渲染成 Markdown 表格（含缩进层级）。

        参数:
            page: pdfplumber 的 Page 对象（用于裁剪单元格取坐标）。
            table: pdfplumber 的 Table 对象。

        返回:
            Markdown 表格文本。
        """
        rows = table.extract()
        if not rows:
            return ""

        n_cols = max(len(row) for row in rows)
        if n_cols == 0:
            return ""

        clipped = False
        if len(rows) > MAX_TABLE_ROWS:
            rows = rows[:MAX_TABLE_ROWS]
            clipped = True
        if n_cols > MAX_TABLE_COLS:
            rows = [row[:MAX_TABLE_COLS] for row in rows]
            n_cols = MAX_TABLE_COLS
            clipped = True

        # 补齐每行长度，避免索引错位
        normalized = [list(row) + [None] * (n_cols - len(row)) for row in rows]

        levels = PdfParseTool._indent_levels(page, table, len(normalized), n_cols)

        lines: list[str] = []
        for r, row in enumerate(normalized):
            cells = [
                PdfParseTool._render_cell(row[c], levels[r][c], header=(r == 0))
                for c in range(n_cols)
            ]
            lines.append("| " + " | ".join(cells) + " |")
            if r == 0:
                lines.append("| " + " | ".join(["---"] * n_cols) + " |")

        rendered = "\n".join(lines)
        if clipped:
            rendered += (
                f"\n（表格过大已截断：仅显示前 {MAX_TABLE_ROWS} 行 × {MAX_TABLE_COLS} 列）"
            )
        return rendered

    @staticmethod
    def _render_cell(value: str | None, level: int, header: bool = False) -> str:
        """渲染一个单元格：合并换行、转义竖线、按层级加全角空格前缀。

        参数:
            value: 单元格原始文本（可能为 None，表示合并单元格占位）。
            level: 缩进层级（0 表示无缩进）。
            header: 是否为表头行（表头不加缩进）。

        返回:
            可直接拼进 Markdown 表格行的单元格文本。
        """
        text = "" if value is None else str(value)
        text = re.sub(r"\s*\n\s*", " ", text).strip()
        text = text.replace("|", "\\|")
        prefix = "" if header else INDENT_UNIT * level
        return prefix + text

    @staticmethod
    def _indent_levels(page: Any, table: Any, n_rows: int, n_cols: int) -> list[list[int]]:
        """推断每个单元格的缩进层级（按列独立聚类，自适应缩进步长）。

        参数:
            page: pdfplumber 的 Page 对象。
            table: pdfplumber 的 Table 对象。
            n_rows: 行数。
            n_cols: 列数。

        返回:
            与表格同形状的层级矩阵，值为 0/1/2/…。
        """
        # 1) 逐列收集每个单元格文字相对单元格左边界的「前导偏移」
        #    用 None 表示「该单元格没有可测量的文字」（合并单元格占位或空单元格），
        #    它们不参与基准值计算，否则会把整列的基准拉到 0、导致归一化失效
        offsets: list[list[float | None]] = [[None] * n_cols for _ in range(n_rows)]
        for r in range(n_rows):
            if r >= len(table.rows):
                break
            for c in range(n_cols):
                if c >= len(table.rows[r].cells):
                    break
                bbox = table.rows[r].cells[c]
                if bbox is None:  # 合并单元格占位
                    continue
                try:
                    words = page.crop(bbox).extract_words()
                except Exception:
                    words = []
                if words:
                    offsets[r][c] = min(w["x0"] for w in words) - bbox[0]

        # 2) 每列独立聚类：把明显分立的偏移值当作不同层级
        levels = [[0] * n_cols for _ in range(n_rows)]
        for c in range(n_cols):
            measured = [offsets[r][c] for r in range(n_rows) if offsets[r][c] is not None]
            if not measured:
                continue
            # 先减去该列最小偏移，抵消单元格统一内边距的影响，
            # 使「该列缩进最少的行」恒为第 0 层
            base = min(measured)

            clusters: list[float] = []
            for value in sorted(v - base for v in measured if v - base > INDENT_EPSILON):
                if clusters and value - clusters[-1] < INDENT_CLUSTER_TOLERANCE:
                    continue  # 与上一个层级同簇
                clusters.append(value)

            for r in range(n_rows):
                raw = offsets[r][c]
                if raw is None:
                    continue  # 空单元格保持第 0 层
                value = raw - base
                if value <= INDENT_EPSILON:
                    levels[r][c] = 0
                    continue
                level = 0
                for index, representative in enumerate(clusters):
                    if value >= representative - INDENT_CLUSTER_TOLERANCE:
                        level = index + 1
                levels[r][c] = level

        return levels
