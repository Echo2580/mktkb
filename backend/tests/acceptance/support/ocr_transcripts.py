"""扫描件/图片的受控 OCR 转录表（只转录 fixture 的真实绘制事实，不内置验收答案）。

事实来源（只读，未修改）：``tools/build_demo_corpus.py`` 第 466～518 行的绘制调用——
D07 每页、D08 每页、D09 文本行、D10 规则表格的表头与两行数据都是该生成器写入图片的原文；
页脚 ``模拟数据／第 N 页／仅用于解析验证`` 与 ``MARK``／``BUSINESS_DATE`` 常量同样来自该文件（第 45～46、174 行）。
本模块的字符串是这些**页面内容**的受控转录，不是 ``questions.json`` 的 ``expected_values``；
``verify_fixture_shapes()`` 用真实文件核对页数/像素，使转录表无法在有界检查下静默漂移。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
FIXTURES = ROOT / "fixtures" / "acceptance"
NORMAL = FIXTURES / "normal"

MARK = "模拟数据"
BUSINESS_DATE = "2026-10-27"

D07_PATH = NORMAL / "D07_活动申请扫描件.pdf"
D08_PATH = NORMAL / "D08_仓库安全须知扫描件.pdf"
D09_PATH = NORMAL / "D09_物料领用通知.png"
D10_PATH = NORMAL / "D10_盘点通知.jpg"

# 每份文件的期望形状，用于把转录表钉在真实文件上
EXPECTED_SHAPES: dict[str, dict] = {
    "D07": {"pages": 8, "kind": "pdf-scan"},
    "D08": {"pages": 2, "kind": "pdf-scan"},
    "D09": {"size": (1200, 700), "kind": "png"},
    "D10": {"size": (1240, 620), "kind": "jpg"},
}


def _scan_footer(page: int) -> str:
    return f"{MARK}／第 {page} 页／仅用于解析验证"


# D07：8 页纯图像扫描件；第 3 页为活动申请表正文，其余页为附件示例说明
D07_PAGES: dict[int, list[str]] = {
    3: [
        "活动申请表",
        "申请部门：市场部",
        "活动名称：秋季门店联合推广",
        "活动日期：2026-11-05",
        "预算：人民币 8,000 元（模拟）",
        "物料清单：宣传海报、易拉宝、促销贴纸",
        _scan_footer(3),
    ],
}
for _page in (1, 2, 4, 5, 6, 7, 8):
    D07_PAGES[_page] = [
        f"活动申请表（第 {_page} 页）",
        "申请部门：市场部",
        f"附件说明：本页为扫描页示例 {_page}，内容为模拟文字。",
        "审批意见：按流程复核。",
        _scan_footer(_page),
    ]

# D08：2 页扫描件
D08_PAGES: dict[int, list[str]] = {
    1: ["仓库安全须知（第 1 页）", "进入仓库须佩戴工牌，禁止吸烟。", "物料摆放不得超高、倾斜。", _scan_footer(1)],
    2: [
        "仓库安全须知（第 2 页）",
        "物料通道保持畅通，不得堆放杂物。",
        "发现异常须向仓库负责人报告。",
        _scan_footer(2),
    ],
}

# D09：单张文本图片（非规则表格，OCR 模式为 text）
D09_TEXT: list[str] = [
    "物料领用通知",
    "领取活动物料前，请填写领用登记表并由负责人确认。",
    "登记表由市场部行政留存。",
    f"{MARK}／链路验证样张",
]

# D10：规则表格图片；实测产品判定为 text 模式（`looks_like_rule_table` 对该图返回 False），
# 因此这里同时给出"读取顺序的逐行文本"（text 模式实际使用）与结构化表格（若将来判为 table 模式）。
D10_TABLE_HEADER: tuple[str, ...] = ("门店", "物品", "盘点时间", "盘点地点")
D10_TABLE_ROWS: tuple[tuple[str, ...], ...] = (
    ("城东店", "宣传海报", "2026-10-30 16:00", "城东店物料区"),
    ("城西店", "宣传海报", "2026-10-31 15:30", "城西店二层仓库"),
)
D10_TEXT: list[str] = [
    "盘点通知（规则表格）",
    f"{MARK}｜业务更新 {BUSINESS_DATE}",
    " ".join(D10_TABLE_HEADER),
    " ".join(D10_TABLE_ROWS[0]),
    " ".join(D10_TABLE_ROWS[1]),
    "门店/物品/时间/地点逐行对应，供串行检查使用",
]

# 需要受控 OCR 的文件 → 绑定说明；process 步骤据此绑定，未绑定的页会立即失败而非"自动补答案"
OCR_BINDINGS: dict[str, dict] = {
    "D07": {"kind": "pdf-scan", "pages": D07_PAGES},
    "D08": {"kind": "pdf-scan", "pages": D08_PAGES},
    "D09": {"kind": "image-text", "pages": {1: D09_TEXT}},
    "D10": {"kind": "image-table", "pages": {1: D10_TEXT}, "table": (D10_TABLE_HEADER, D10_TABLE_ROWS)},
}


def file_path(file_id: str) -> Path:
    return {"D07": D07_PATH, "D08": D08_PATH, "D09": D09_PATH, "D10": D10_PATH}[file_id]


def verify_fixture_shapes() -> dict:
    """用真实文件核对转录表覆盖的页数/像素，返回实测形状供证据记录。"""
    import pdfplumber
    from PIL import Image

    observed: dict[str, dict] = {}
    for file_id in ("D07", "D08"):
        path = file_path(file_id)
        with pdfplumber.open(path) as pdf:
            pages = len(pdf.pages)
        expected = EXPECTED_SHAPES[file_id]["pages"]
        assert pages == expected, f"{file_id} 实际页数 {pages} 与转录表假设 {expected} 不一致"
        transcript = OCR_BINDINGS[file_id]["pages"]
        assert sorted(transcript) == list(range(1, pages + 1)), f"{file_id} 转录页号未覆盖全部 {pages} 页"
        observed[file_id] = {"pages": pages, "transcript_pages": len(transcript)}

    for file_id in ("D09", "D10"):
        path = file_path(file_id)
        with Image.open(path) as image:
            size = image.size
            fmt = image.format
        expected = EXPECTED_SHAPES[file_id]["size"]
        assert size == expected, f"{file_id} 实际像素 {size} 与转录表假设 {expected} 不一致"
        observed[file_id] = {"size": list(size), "format": fmt}

    observed["D10"]["table_rows"] = len(D10_TABLE_ROWS)
    observed["D10"]["table_columns"] = len(D10_TABLE_HEADER)
    return observed
