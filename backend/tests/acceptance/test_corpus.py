r"""T01-C2 语料检查：直接读取真实文件，不循环比对生成器自己的 JSON。

运行：
    .\.venv\Scripts\python.exe -B -m pytest backend/tests/acceptance/test_corpus.py -q

覆盖：10 份正常资料的格式分布与真实内容、64 条题目编号/分组/分类、manifest 哈希与来源定位、
变体隔离与异常样本可复现失败、单文件边界计量、以及没有绝对路径泄漏。
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))  # 供边界重建入口检查使用
CORPUS = ROOT / "fixtures" / "acceptance"
MANIFEST = CORPUS / "manifest.json"
QUESTIONS = CORPUS / "questions.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def question_set() -> list[dict]:
    return json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]


def file_entry(file_id: str) -> dict:
    data = manifest()
    for entry in data["normal_files"] + data["variants"] + data["boundary"]:
        if entry["id"] == file_id:
            return entry
    raise AssertionError(f"file id not in manifest: {file_id}")


def corpus_path(entry: dict) -> Path:
    return CORPUS / entry["path"]


# --------------------------------------------------------------- 数量与身份


def test_corpus_files_exist_and_are_listed():
    assert MANIFEST.is_file(), "fixtures/acceptance/manifest.json 尚未生成"
    assert QUESTIONS.is_file(), "fixtures/acceptance/questions.json 尚未生成"
    normal_dir = CORPUS / "normal"
    files = sorted(path.name for path in normal_dir.iterdir() if path.is_file())
    assert len(files) == 10, f"normal 目录应恰有 10 份文件，实际 {len(files)}: {files}"


def test_format_distribution():
    normal = manifest()["normal_files"]
    kinds = [entry["kind"] for entry in normal]
    assert len(normal) == 10
    assert kinds.count("xlsx") == 2
    assert kinds.count("docx") == 2
    assert kinds.count("pdf-text") == 2
    assert kinds.count("pdf-scan") == 2
    assert kinds.count("png") == 1
    assert kinds.count("jpg") == 1


def test_manifest_hashes_match_real_files():
    for entry in manifest()["normal_files"]:
        path = corpus_path(entry)
        assert path.is_file(), f"缺少文件 {entry['path']}"
        assert sha256(path) == entry["sha256"], f"哈希不符 {entry['path']}"


def test_manifest_has_no_absolute_paths():
    text = MANIFEST.read_text(encoding="utf-8")
    assert ":\\" not in text and "C:/" not in text
    for entry in manifest()["normal_files"]:
        assert not Path(entry["path"]).is_absolute()


# --------------------------------------------------------------- 题目


def test_question_counts_and_ids():
    questions = question_set()
    ids = [q["id"] for q in questions]
    assert len(questions) == 64, f"应为 64 条，实际 {len(questions)}"
    assert len(set(ids)) == 64, "编号重复"
    assert sorted(ids) == sorted([f"Q{i:02d}" for i in range(1, 41)] + [f"N{i:02d}" for i in range(1, 9)] +
                                 [f"C{i:02d}" for i in range(1, 7)] + [f"U{i:02d}" for i in range(1, 11)])


def test_question_groups_and_categories():
    questions = question_set()
    groups = {key: [q for q in questions if q["group"] == key]
              for key in ("normal", "negative", "ambiguity_conflict", "mutation")}
    assert len(groups["normal"]) == 40
    assert len(groups["negative"]) == 8
    assert len(groups["ambiguity_conflict"]) == 6
    assert len(groups["mutation"]) == 10
    categories = {key: [q for q in questions if q["category"] == key] for key in ("exact", "text", "ocr")}
    assert len(categories["exact"]) == 24
    assert len(categories["text"]) == 8
    assert len(categories["ocr"]) == 8
    for question in questions:
        if question["group"] == "normal":
            assert question["category"] in {"exact", "text", "ocr"}
        else:
            assert question["category"] is None


def test_normal_questions_are_answered_from_b0_only():
    normal_sources = {entry["id"] for entry in manifest()["normal_files"]}
    for question in question_set():
        if question["group"] != "normal":
            continue
        for source in question["expected_sources"]:
            assert source["file"] in normal_sources, f"{question['id']} 引用了非正常集来源"


def test_conflict_scenarios_use_variants_not_normal():
    questions = {q["id"]: q for q in question_set()}
    for code in ("C05", "C06"):
        files = {source["file"] for source in questions[code]["expected_sources"]}
        assert "V01" in files or "V02" in files
        normal_ids = {entry["id"] for entry in manifest()["normal_files"]}
        assert files - normal_ids, f"{code} 必须包含变体来源"


# --------------------------------------------------------------- 真实文件内容


def test_d01_sheets_header_and_primary_record():
    from openpyxl import load_workbook

    path = corpus_path(file_entry("D01"))
    workbook = load_workbook(path)
    assert workbook.sheetnames == ["物品位置", "备用物料表", "旧草稿"]
    assert workbook["旧草稿"].sheet_state == "hidden", "旧草稿应为隐藏表"
    sheet = workbook["物品位置"]
    assert [sheet.cell(row=7, column=col).value for col in range(1, 6)] == ["标识", "门店", "物品", "别名", "位置"]
    assert sheet.cell(row=8, column=1).value == "P01"
    assert sheet.cell(row=8, column=2).value == "城东店"
    assert sheet.cell(row=8, column=5).value == "B区1号货架第二层"
    assert sheet.cell(row=9, column=5).value == "C区2号货架第一层"
    codes = [sheet.cell(row=row, column=1).value for row in range(8, 16)]
    assert codes == [f"P{i:02d}" for i in range(1, 9)]
    assert workbook["备用物料表"].cell(row=4, column=1).value == "城东店"
    assert workbook["备用物料表"].cell(row=4, column=3).value == "A区5号柜"
    assert workbook["旧草稿"].cell(row=3, column=3).value == "A区3号货架第二层"


def test_d02_store_phones_are_strings_with_leading_zero():
    from openpyxl import load_workbook

    sheet = load_workbook(corpus_path(file_entry("D02")))["店家信息"]
    stores = [sheet.cell(row=row, column=2).value for row in range(5, 9)]
    assert stores == ["城东店", "城西店", "城北店", "滨河店"]
    phones = [sheet.cell(row=row, column=4).value for row in range(5, 9)]
    assert all(isinstance(value, str) for value in phones)
    assert phones == ["010-00000001", "010-00000002", "010-00000003", "010-00000004"]
    assert "城南店" not in stores


def test_d03_docx_process_steps():
    from docx import Document

    text = "\n".join(p.text for p in Document(corpus_path(file_entry("D03"))).paragraphs)
    assert "填写登记表" in text
    assert "负责人确认" in text
    assert "登记实际领取数量" in text
    assert "归还日期" in text


def test_d04_docx_lead_time_and_plan_fields():
    from docx import Document

    text = "\n".join(p.text for p in Document(corpus_path(file_entry("D04"))).paragraphs)
    assert "3 个工作日" in text
    assert "3 个自然日" in text
    for field in ("目标", "时间地点", "预算", "物料清单"):
        assert field in text


def test_text_pdfs_contain_required_rules():
    import pdfplumber

    with pdfplumber.open(corpus_path(file_entry("D05"))) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "两店负责人确认" in text
    assert "数量与完好情况" in text

    with pdfplumber.open(corpus_path(file_entry("D06"))) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "当日联系资料管理员" in text
    assert "业务更新时间" in text
    assert "修改原因" in text


def test_scanned_pdfs_have_no_text_layer():
    import pdfplumber

    d07 = corpus_path(file_entry("D07"))
    with pdfplumber.open(d07) as pdf:
        assert len(pdf.pages) == 8, "D07 应为 8 页"
        for index, page in enumerate(pdf.pages, start=1):
            assert page.extract_text() in (None, ""), f"D07 第 {index} 页不应有文字层"
            assert page.images, f"D07 第 {index} 页应为图像页"

    with pdfplumber.open(corpus_path(file_entry("D08"))) as pdf:
        assert len(pdf.pages) == 2, "D08 应为 2 页"
        for page in pdf.pages:
            assert page.extract_text() in (None, "")


def test_images_are_real_rasters():
    from PIL import Image

    with Image.open(corpus_path(file_entry("D09"))) as image:
        assert image.format == "PNG"
        assert image.size[0] >= 1000 and image.size[1] >= 600
    with Image.open(corpus_path(file_entry("D10"))) as image:
        assert image.format == "JPEG"
        assert image.size[0] >= 1000


# --------------------------------------------------------------- 变体与异常


def test_variants_isolated_from_normal():
    normal_ids = {entry["id"] for entry in manifest()["normal_files"]}
    variant_ids = {entry["id"] for entry in manifest()["variants"]}
    assert normal_ids.isdisjoint(variant_ids)
    assert not any("variants" in entry["path"] for entry in manifest()["normal_files"])
    for entry in manifest()["variants"]:
        assert corpus_path(entry).is_file(), f"缺少变体文件 {entry['path']}"


def test_conflict_and_version_variants_content():
    from openpyxl import load_workbook
    import pdfplumber

    with pdfplumber.open(corpus_path(file_entry("V01"))) as pdf:
        assert "D区暂存柜" in (pdf.pages[0].extract_text() or "")
    with pdfplumber.open(corpus_path(file_entry("V02"))) as pdf:
        assert "010-00000099" in (pdf.pages[0].extract_text() or "")

    v1 = load_workbook(corpus_path(file_entry("V03")))["物品位置"]
    assert v1.cell(row=8, column=5).value == "A区3号货架第二层"
    v3 = load_workbook(corpus_path(file_entry("V04")))["物品位置"]
    assert v3.cell(row=8, column=5).value == "D区暂存柜"
    v5 = load_workbook(corpus_path(file_entry("V05")))["物品位置"]
    assert [v5.cell(row=row, column=1).value for row in range(8, 15)] == [f"P{i:02d}" for i in range(2, 9)]
    assert v5.cell(row=15, column=1).value is None
    v6 = load_workbook(corpus_path(file_entry("V06")))["店家信息"]
    assert v6.cell(row=5, column=4).value == "010-00000088"

    with pdfplumber.open(corpus_path(file_entry("V07"))) as pdf:
        assert "B区1号货架第二层" in (pdf.pages[0].extract_text() or "")


def test_anomalies_fail_as_documented():
    from docx import Document
    from openpyxl import load_workbook
    import pdfplumber

    with pytest.raises(Exception):
        Document(corpus_path(file_entry("A01")))
    with pytest.raises(Exception):
        load_workbook(corpus_path(file_entry("A02")))
    with pytest.raises(Exception) as encrypted:
        with pdfplumber.open(corpus_path(file_entry("A03"))) as pdf:
            pdf.pages[0].extract_text()
    # pdfminer 会把 PDFPasswordIncorrect 包在外层异常里，逐层取名称判断
    parts = [type(encrypted.value).__name__, str(encrypted.value)]
    for arg in getattr(encrypted.value, "args", ()):
        parts.extend([type(arg).__name__, str(arg)])
    message = " ".join(parts).lower()
    assert "password" in message or "encrypt" in message, message

    from PIL import Image

    with Image.open(corpus_path(file_entry("A05"))) as image:
        colours = image.convert("L").getcolors(maxcolors=4)
        assert colours and len(colours) == 1, "无文字样本应为纯色"


def test_mixed_pdfs_distinguish_supported_and_failed_pages():
    import pdfplumber

    with pdfplumber.open(corpus_path(file_entry("A07"))) as pdf:
        assert len(pdf.pages) == 2
        assert (pdf.pages[0].extract_text() or "").strip(), "混合 PDF 第 1 页应为文字页"
        assert pdf.pages[1].images, "混合 PDF 第 2 页应为扫描页"

    with pdfplumber.open(corpus_path(file_entry("A08"))) as pdf:
        assert len(pdf.pages) == 2
        assert (pdf.pages[0].extract_text() or "").strip()
        assert pdf.pages[1].images


# --------------------------------------------------------------- 边界计量


def test_boundary_measurements():
    entries = {entry["id"]: entry for entry in manifest()["boundary"]}
    assert entries["B01"]["measure"]["bytes"] == 20 * 1024 * 1024
    assert entries["B02"]["measure"]["bytes"] == 20 * 1024 * 1024 + 1
    assert entries["B01"]["kept"] is False and entries["B02"]["kept"] is False
    assert entries["B03"]["measure"]["pages"] == 50
    assert entries["B04"]["measure"]["pages"] == 51
    assert entries["B05"]["measure"]["data_rows"] == 5000
    assert entries["B06"]["measure"]["data_rows"] == 5001
    assert entries["B07"]["measure"]["pixels"] == 20_000_000
    assert entries["B08"]["measure"]["pixels"] == 20_000_000 + 5000

    import pdfplumber
    from openpyxl import load_workbook
    from PIL import Image

    with pdfplumber.open(corpus_path(entries["B03"])) as pdf:
        assert len(pdf.pages) == 50
    with pdfplumber.open(corpus_path(entries["B04"])) as pdf:
        assert len(pdf.pages) == 51
    assert load_workbook(corpus_path(entries["B05"]))["记录"].max_row == 5001  # 5000 数据行 + 表头
    assert load_workbook(corpus_path(entries["B06"]))["记录"].max_row == 5002
    with Image.open(corpus_path(entries["B07"])) as image:
        assert image.size == (5000, 4000)
    with Image.open(corpus_path(entries["B08"])) as image:
        assert image.size == (5000, 4001)


# --------------------------------------------------------------- 来源定位


def test_manifest_sources_point_to_real_locations():
    data = manifest()
    assert data["records"]["P01"]["位置"] == "B区1号货架第二层"
    p01 = data["sources"]["P01"]
    assert p01["file"] == "D01" and p01["sheet"] == "物品位置" and p01["row"] == 8

    from openpyxl import load_workbook

    sheet = load_workbook(corpus_path(file_entry("D01")))["物品位置"]
    assert sheet.cell(row=p01["row"], column=1).value == "P01"
    assert sheet.cell(row=p01["row"], column=5).value == data["records"]["P01"]["位置"]

    for code in ("S01", "S02", "S03", "S04"):
        source = data["sources"][code]
        assert source["file"] == "D02"
        store_sheet = load_workbook(corpus_path(file_entry("D02")))["店家信息"]
        assert store_sheet.cell(row=source["row"], column=1).value == code
        assert store_sheet.cell(row=source["row"], column=2).value == data["records"][code]["店家"]


def test_fixture_count_does_not_include_generator_artifacts():
    extras = [path.name for path in CORPUS.iterdir() if path.is_file() and path.name not in
              {"manifest.json", "questions.json", "README.md"}]
    assert extras == [], f"fixtures/acceptance 根目录出现非预期文件: {extras}"


# --------------------------------------------------------------- B0 初始化配方


def test_b0_initialization_recipe():
    data = manifest()
    recipe = data.get("b0_initialization")
    assert recipe, "manifest 缺少 B0 初始化配方"
    steps = recipe["steps"]
    assert [step["step"] for step in steps] == list(range(1, len(steps) + 1)), "步骤序号不连续"

    # D01 逻辑槽必须先发布历史 V1（V03），再发布正常 D01（业务 V2）
    slot_steps = [step for step in steps if step.get("document_slot") == "doc-positions"]
    files = [step["file"] for step in slot_steps]
    assert files.index("V03") < files.index("D01"), "历史 V1 必须先于当前 D01 发布"
    assert "V04" not in files, "V04 是 D 区新位置，不能用于建立 B0"
    versions = [step.get("business_version") for step in slot_steps if step.get("business_version")]
    assert versions == ["V1", "V2"], f"业务版本顺序应为 V1→V2，实际 {versions}"
    for step in slot_steps:
        assert step["op"] in {"import_document", "import_version", "process", "publish"}

    assertions = " ".join(recipe.get("assertions", []))
    assert "A区3号货架第二层" in assertions and "B区1号货架第二层" in assertions
    assert any("revision" in item.lower() for item in recipe.get("assertions", [])), "须说明 revision 由实际运行读取"
    assert recipe.get("forbidden"), "须写明禁止用 V04 建立 B0"

    # 正常题与依赖 B0 的场景引用同一配方
    for question in question_set():
        scenario = question["scenario"]
        if question["group"] == "normal" or scenario.get("initial_state", "").startswith("B0"):
            assert scenario.get("initialization_ref") == "b0_initialization", f"{question['id']} 未引用 B0 配方"


# --------------------------------------------------------------- U07 / U08 / U09


def _mutation(code: str) -> dict:
    return next(q for q in question_set() if q["id"] == code)


def test_u07_has_publish_and_delete_subscenarios():
    scenario = _mutation("U07")["scenario"]
    subs = scenario.get("sub_scenarios") or []
    assert {sub["variant"] for sub in subs} == {"publish", "delete"}, "U07 须分为发布与删除两个子场景"

    order = ["ask_read_revision", "pause_model_generation"]
    for sub in subs:
        events = sub["events"]
        assert events[:2] == order, f"{sub['id']} 事件须先读取 revision 并暂停"
        commit = "publish_commit_V04" if sub["variant"] == "publish" else "delete_commit_D01"
        assert commit in events
        assert events.index(commit) > events.index("pause_model_generation")
        assert events.index("knowledge_changed") > events.index(commit)
        expected = sub["expected"]
        assert expected["kind"] == "knowledge_changed"
        assert expected["sources"] == []
        assert expected["saved_old_facts"] is False
        if sub["variant"] == "publish":
            ops = [pre["op"] for pre in sub["preconditions"]]
            assert ops[:3] == ["upload_version", "process", "review_required"], "发布子场景须先把新版处理到待确认"


def test_u08_uses_two_distinct_candidates_and_one_success():
    scenario = _mutation("U08")["scenario"]
    requests = scenario["requests"]
    assert [req["file"] for req in requests] == ["V04", "V05"], "须使用两个不同的已处理候选"
    captured = {(req["captured_active_version_id"], req["captured_revision"]) for req in requests}
    assert len(captured) == 1, "两次请求必须捕获同一旧 active_version_id 与 revision"
    statuses = sorted(req["expected"]["http_status"] for req in requests)
    assert statuses == [200, 409], f"期望一个 200、一个 409，实际 {statuses}"
    conflict = next(req for req in requests if req["expected"]["http_status"] == 409)
    assert conflict["expected"]["error_code"] == "PUBLISH_CONFLICT"
    assert scenario["expected_revision_increment"] == 1
    assert "kind" not in scenario, "纯管理操作不应套用 AskResult.kind"
    assert scenario.get("idempotency", {}).get("expected_http_status") == 200
    assert scenario["idempotency"]["note"]


def test_u09_has_three_explicit_subscenarios_and_no_ambiguous_action():
    scenario = _mutation("U09")["scenario"]
    subs = {sub["variant"]: sub for sub in scenario.get("sub_scenarios", [])}
    assert set(subs) == {"delete", "cancel_pending_version", "lease_expired"}

    for sub in subs.values():
        assert sub["late_result_at"] > sub["ocr_sent_at"], "须给出 OCR 已发送与迟到返回的时点"
    delete = subs["delete"]
    assert delete["expected"]["active_access_revoked"] is True
    assert delete["expected"]["document_restored"] is False
    cancel = subs["cancel_pending_version"]
    assert cancel["expected"]["old_version_still_answerable"] is True
    assert cancel["expected"].get("kind") != "not_found", "取消新版不应一律期望 not_found"
    lease = subs["lease_expired"]
    assert lease["expected"]["stale_result_committed"] is False
    assert lease["expected"]["new_holder_may_continue"] is True

    text = json.dumps(question_set(), ensure_ascii=False)
    assert "delete_or_cancel" not in text, "不得保留未选择的 delete_or_cancel 动作"


# --------------------------------------------------------------- 边界重建入口


def test_boundary_rebuild_entry_keeps_files(tmp_path):
    import build_demo_corpus as builder

    target = tmp_path / "boundary-out"
    entries = builder.build_boundary_files(target)
    assert {entry["id"] for entry in entries} == {"B01", "B02"}
    recorded = {entry["id"]: entry for entry in manifest()["boundary"]}
    for entry in entries:
        path = target / Path(entry["path"]).name
        assert path.is_file(), f"重建入口未保留文件 {path}"
        assert entry["bytes"] == recorded[entry["id"]]["measure"]["bytes"]
        assert entry["sha256"] == recorded[entry["id"]]["sha256"], "重建文件哈希须与冻结记录一致"

    import pdfplumber
    import pypdfium2 as pdfium

    exact = target / Path(recorded["B01"]["path"]).name
    with pdfplumber.open(exact) as pdf:
        assert len(pdf.pages) == 1
        assert (pdf.pages[0].extract_text() or "").strip(), "20MB 样本须可提取文字"
    document = pdfium.PdfDocument(str(exact))
    assert len(document) == 1

    with pytest.raises(SystemExit):
        builder.build_boundary_files(target)  # 非空目录必须拒绝

