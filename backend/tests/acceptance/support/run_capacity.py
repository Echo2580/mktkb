"""T09-D5 容量/压力基线执行器（本机 L 层；真实 uvicorn + 真实 SQLite/worker/检索，模型/OCR 为受控替身）。

用法（cwd=仓库根，只用 .venv\\Scripts\\python.exe -B）：

    # 一次完整容量轮（自动生成/复用数据集、启动隔离服务、入库 50 份、3 用户并发问答、优雅停服）
    .venv\\Scripts\\python.exe -B backend\\tests\\acceptance\\support\\run_capacity.py ^
        --label d5-cap-01 --evidence-root docs/evidence/T09/D5

产物（证据目录由 --evidence-root 派生，不允许覆盖既有 run）：
    logs/capacity-server-<label>.jsonl / .stdout.log / .stderr.log
    actual/<label>/{run,files,requests,resources,db-counts,outbound}.json

设计约束：
- 服务端 ``Settings(_env_file=None)`` + 明确假密钥 + 注入 ``EvidenceEchoGateway`` 与容量 OCR 替身；
  进程级出站闸门（与 netguard 同口径）拦截并记账任何非回环出站。
- 数据集只在证据 tmp 下生成一次（全新内容，不写 fixtures）；每轮把文件字节复制到本轮独立输入目录。
- 每轮使用全新服务数据目录；端口启动前三重检查（netstat/connect/bind），停服后再次确认端口释放。
- 本工具不是产品代码，不修改产品源码/既有测试断言。
"""

from __future__ import annotations

import argparse
import contextvars
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import platform
import shutil
import socket
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[4]
FONT_DIR = ROOT / "docs" / "evidence" / "T01" / "C1-R1" / "derived-fonts"
FONT_REGULAR = FONT_DIR / "NotoSansSCStatic-Regular.ttf"
FONT_MEDIUM = FONT_DIR / "NotoSansSCStatic-Medium.ttf"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8299
READY_TIMEOUT_SECONDS = 180.0
SERVER_EXIT_TIMEOUT_SECONDS = 90.0
JOB_TIMEOUT_SECONDS = 300.0
ASK_TIMEOUT_SECONDS = 300.0
WORKER_IDLE_SECONDS = 0.05
SAMPLER_INTERVAL_SECONDS = 0.2

ADMIN = ("admin", "AdminPass-1")
USERS = (
    ("employee", "EmployeePass-1"),
    ("employee2", "EmployeePass-2"),
    ("employee3", "EmployeePass-3"),
)
EXTRA_ACCOUNTS = (
    ("employee2", "EmployeePass-2", "容量员工二"),
    ("employee3", "EmployeePass-3", "容量员工三"),
)

MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
}

# 每轮问答题集：4 记录型 + 2 Word 正文 + 2 文字 PDF + 2 扫描件（图片/扫描 PDF）。
QUESTION_SPECS = (
    {"id": "Q01", "category": "record", "question": "城东店的宣传海报在哪里？", "expect_kind": "answer", "expect_value": "B区1号货架第二层"},
    {"id": "Q02", "category": "record", "question": "城东店的联系电话是什么？", "expect_kind": "answer", "expect_value": "010-10000001"},
    {"id": "Q03", "category": "record", "question": "城西店的联系人是谁？", "expect_kind": "answer", "expect_value": "林白"},
    {"id": "Q04", "category": "record", "question": "城东店的展架在哪里？", "expect_kind": "answer", "expect_value": "A区2号货架底层"},
    {"id": "Q05", "category": "docx", "question": "青松文档的关键要求是什么？", "expect_kind": "answer", "expect_value": "领取物料前完成登记"},
    {"id": "Q06", "category": "docx", "question": "白桦文档的处理流程是什么？", "expect_kind": "answer", "expect_value": "先提交申请单"},
    {"id": "Q07", "category": "text_pdf", "question": "瑞香说明的注意事项是什么？", "expect_kind": "answer", "expect_value": "跨店调拨须两店复核人确认"},
    {"id": "Q08", "category": "text_pdf", "question": "木槿说明的适用范围是什么？", "expect_kind": "answer", "expect_value": "仅适用于容量测试"},
    {"id": "Q09", "category": "scan_image", "question": "扫描样张青松01 的核验编号是多少？", "expect_kind": "answer", "expect_value": "__SCAN_CODE__:扫描样张青松01"},
    {"id": "Q10", "category": "scan_pdf", "question": "扫描说明白桦01 的核验编号是多少？", "expect_kind": "answer", "expect_value": "__SCAN_CODE__:扫描说明白桦01"},
)

DOCX_WORDS = ("青松", "白桦", "梧桐", "银杏", "红枫", "云杉", "香樟", "翠竹", "紫藤", "玉兰", "海棠", "杜鹃")
TEXT_PDF_WORDS = ("瑞香", "木槿", "含笑", "山茶", "腊梅", "迎春", "连翘", "樱花", "桂花", "石榴", "枇杷", "杨梅")
SCAN_PDF_WORDS = ("白桦", "青冈", "水杉", "冷杉", "雪松", "侧柏", "刺槐", "枫杨")
SCAN_IMAGE_WORDS = ("青松", "春兰", "夏荷", "秋菊", "冬梅", "墨兰", "建兰", "蕙兰", "寒兰", "石斛")
MISC_XLSX_ROWS = (20, 30, 40, 50)


# ---------------------------------------------------------------- 基础工具


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def scan_code(stem: str) -> str:
    return "NX-" + hashlib.sha256(stem.encode("utf-8")).hexdigest()[:6].upper()


def ocr_text_for(stem: str, page: int) -> str:
    """扫描件受控转录：只由文档名与页码推导，不内置任何题目答案。"""
    return f"{stem}：扫描件核验编号 {scan_code(stem)}，核验结论为已复核；本页为第 {page} 页。"


def expected_value(spec: dict) -> str:
    value = str(spec["expect_value"])
    if value.startswith("__SCAN_CODE__:"):
        return scan_code(value.split(":", 1)[1])
    return value


def check_port_free(port: int, host: str = DEFAULT_HOST) -> dict:
    """三重端口检查：netstat 监听 + 实际 connect + bind 试探。"""
    evidence: dict = {"port": port, "netstat_listen": [], "connect_ok": False, "bind_error": None, "in_use": False}
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        for line in completed.stdout.splitlines():
            if f":{port}" in line and "LISTEN" in line.upper():
                evidence["netstat_listen"].append(line.strip())
                evidence["in_use"] = True
    except (OSError, subprocess.SubprocessError):
        evidence["netstat_error"] = "unavailable"
    try:
        with socket.create_connection((host, port), timeout=1.0):
            evidence["connect_ok"] = True
            evidence["in_use"] = True
    except OSError:
        pass
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError as exc:
        evidence["bind_error"] = f"{type(exc).__name__}: {exc}"
        evidence["in_use"] = True
    finally:
        probe.close()
    return evidence


def wait_http_ready(url: str, timeout: float, proc: subprocess.Popen | None = None) -> float:
    started = time.monotonic()
    deadline = started + timeout
    import urllib.error
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"服务进程提前退出：exit={proc.returncode}")
        try:
            with opener.open(url, timeout=2.0) as response:
                if response.status == 200:
                    return round((time.monotonic() - started) * 1000, 1)
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.2)
    raise TimeoutError(f"等待 {url} 超时（{timeout}s）")


# ---------------------------------------------------------------- 机器规格与进程资源


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wt.DWORD),
        ("dwMemoryLoad", wt.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def machine_facts(data_dir: Path) -> dict:
    payload: dict = {
        "os": platform.platform(),
        "os_release": platform.release(),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "cpu_logical": os.cpu_count(),
        "captured_at": now_iso(),
    }
    try:
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            payload["ram_total_bytes"] = int(status.ullTotalPhys)
            payload["ram_available_bytes"] = int(status.ullAvailPhys)
    except Exception as exc:  # noqa: BLE001 - 规格采集失败不影响容量结论，但必须如实记录
        payload["ram_error"] = f"{type(exc).__name__}: {exc}"
    try:
        usage = shutil.disk_usage(data_dir.anchor or "C:/")
        payload["disk_total_bytes"] = int(usage.total)
        payload["disk_free_bytes"] = int(usage.free)
    except OSError as exc:
        payload["disk_error"] = f"{type(exc).__name__}: {exc}"
    script = (
        "$cpu=Get-CimInstance Win32_Processor | Select-Object -First 1;"
        "$disk=Get-CimInstance Win32_DiskDrive | Select-Object -First 1;"
        "@{cpu_name=$cpu.Name;cpu_cores=$cpu.NumberOfCores;cpu_logical=$cpu.NumberOfLogicalProcessors;"
        "disk_model=$disk.Model;disk_media=$disk.MediaType;disk_size=$disk.Size} | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            payload["cim"] = json.loads(completed.stdout.strip())
        else:
            payload["cim_error"] = (completed.stderr or "").strip()[:300]
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        payload["cim_error"] = f"{type(exc).__name__}: {exc}"
    return payload


class ProcessSampler(threading.Thread):
    """每 200ms 采样后端进程 RSS/CPU（ctypes：psapi.GetProcessMemoryInfo + kernel32.GetProcessTimes）。"""

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010

    def __init__(self, pid: int, interval: float = SAMPLER_INTERVAL_SECONDS) -> None:
        super().__init__(name="capacity-sampler", daemon=True)
        self.pid = int(pid)
        self.interval = float(interval)
        self.stop_event = threading.Event()
        self.phase = "startup"
        self.phase_started = time.monotonic()
        self.samples: list[dict] = []
        self.error: str | None = None
        self.peak_working_set: int | None = None
        self._handle = None
        self._lock = threading.Lock()

    def _open(self) -> None:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(self.PROCESS_QUERY_INFORMATION | self.PROCESS_VM_READ, False, self.pid)
        if not handle:
            raise OSError(f"OpenProcess 失败：pid={self.pid} err={ctypes.get_last_error()}")
        self._handle = handle

    def _sample(self) -> tuple[int, int, float]:
        psapi = ctypes.windll.psapi
        kernel32 = ctypes.windll.kernel32
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        if not psapi.GetProcessMemoryInfo(self._handle, ctypes.byref(counters), counters.cb):
            raise OSError("GetProcessMemoryInfo 失败")
        creation = wt.FILETIME()
        exit_time = wt.FILETIME()
        kernel = wt.FILETIME()
        user = wt.FILETIME()
        if not kernel32.GetProcessTimes(
            self._handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)
        ):
            raise OSError("GetProcessTimes 失败")
        cpu_100ns = (kernel.dwHighDateTime << 32 | kernel.dwLowDateTime) + (
            user.dwHighDateTime << 32 | user.dwLowDateTime
        )
        return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize), round(cpu_100ns / 10_000_000, 6)

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self.phase = phase
            self.phase_started = time.monotonic()
        if self.samples:
            self.samples[-1]["phase_end_monotonic"] = round(time.monotonic(), 6)

    def run(self) -> None:
        try:
            self._open()
        except OSError as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return
        try:
            while not self.stop_event.is_set():
                moment = time.monotonic()
                try:
                    rss, peak, cpu = self._sample()
                except OSError as exc:
                    self.error = f"{type(exc).__name__}: {exc}"
                    break
                with self._lock:
                    phase = self.phase
                self.samples.append(
                    {
                        "t_monotonic": round(moment, 6),
                        "t_wall": now_iso(),
                        "phase": phase,
                        "rss_bytes": rss,
                        "cpu_seconds": cpu,
                    }
                )
                self.peak_working_set = peak if self.peak_working_set is None else max(self.peak_working_set, peak)
                self.stop_event.wait(self.interval)
        finally:
            if self._handle:
                try:
                    ctypes.windll.kernel32.CloseHandle(self._handle)
                except Exception:  # noqa: BLE001
                    pass
                self._handle = None

    def summary(self) -> dict:
        grouped: dict[str, list[dict]] = {}
        for sample in self.samples:
            grouped.setdefault(sample["phase"], []).append(sample)
        phases: dict[str, dict] = {}
        for phase, items in grouped.items():
            rss = [item["rss_bytes"] for item in items]
            cpu = [item["cpu_seconds"] for item in items]
            phases[phase] = {
                "samples": len(items),
                "rss_max_bytes": max(rss),
                "rss_mean_bytes": int(statistics.fmean(rss)),
                "cpu_seconds_delta": round(max(cpu) - min(cpu), 6),
                "first_wall": items[0]["t_wall"],
                "last_wall": items[-1]["t_wall"],
            }
        return {
            "method": "ctypes psapi.GetProcessMemoryInfo + kernel32.GetProcessTimes（每 200ms 采样）",
            "interval_seconds": self.interval,
            "pid": self.pid,
            "error": self.error,
            "peak_working_set_bytes": self.peak_working_set,
            "sample_count": len(self.samples),
            "phases": phases,
            "samples": self.samples,
        }


# ---------------------------------------------------------------- 数据集（全新唯一内容）


def _ensure_fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    names = ("D5Capacity-Regular", "D5Capacity-Medium")
    registered = set(pdfmetrics.getRegisteredFontNames())
    if names[0] not in registered:
        if not FONT_REGULAR.is_file() or not FONT_MEDIUM.is_file():
            raise RuntimeError(f"缺少派生字体：{FONT_DIR}")
        pdfmetrics.registerFont(TTFont(names[0], str(FONT_REGULAR)))
        pdfmetrics.registerFont(TTFont(names[1], str(FONT_MEDIUM)))
    return names


def write_xlsx(path: Path, header: list[str], rows: list[list[object]]) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "数据"
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    workbook.save(str(path))


def write_docx(path: Path, title: str, paragraphs: list[str]) -> None:
    from docx import Document as DocxDocument

    document = DocxDocument()
    document.add_heading(title, level=1)
    for line in paragraphs:
        document.add_paragraph(line)
    document.save(str(path))


def write_text_pdf(path: Path, title: str, lines: list[str]) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    regular, medium = _ensure_fonts()
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(title)
    pdf.setAuthor("T09-D5 capacity")
    width, height = A4
    y = height - 80
    pdf.setFont(medium, 16)
    pdf.drawString(56, y, title)
    y -= 36
    pdf.setFont(regular, 11)
    for line in lines:
        pdf.drawString(56, y, line)
        y -= 20
    pdf.showPage()
    pdf.save()


def _render_image(lines: list[str], size: tuple[int, int] = (1200, 800)):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(str(FONT_MEDIUM), 40)
    body_font = ImageFont.truetype(str(FONT_REGULAR), 28)
    draw.text((60, 60), lines[0], font=title_font, fill=(0, 0, 0))
    y = 150
    for line in lines[1:]:
        draw.text((60, y), line, font=body_font, fill=(0, 0, 0))
        y += 52
    return image


def write_image(path: Path, lines: list[str]) -> None:
    _render_image(lines).save(str(path), format="PNG")


def write_scan_pdf(path: Path, lines: list[str]) -> None:
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    _ensure_fonts()
    image = _render_image(lines)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle("扫描件")
    pdf.setAuthor("T09-D5 capacity")
    pdf.drawImage(ImageReader(buffer), 0, 0, width=A4[0], height=A4[1])
    pdf.showPage()
    pdf.save()


def build_dataset(target: Path) -> dict:
    """生成 50 份全新资料（8 xlsx / 12 docx / 12 文字 PDF / 8 扫描 PDF / 10 图片）。"""
    target.mkdir(parents=True, exist_ok=False)
    files: list[dict] = []

    def record(path: Path, category: str, rows: int | None = None, note: str = "") -> None:
        files.append(
            {
                "name": path.name,
                "category": category,
                "bytes": path.stat().st_size,
                "sha256": sha256_path(path),
                "rows": rows,
                "note": note,
            }
        )

    positions = target / "容量物品位置表.xlsx"
    write_xlsx(
        positions,
        ["标识", "门店", "物品", "别名", "位置"],
        [
            ["CP01", "城东店", "宣传海报", "海报", "B区1号货架第二层"],
            ["CP02", "城西店", "宣传海报", "海报", "C区2号货架第一层"],
            ["CP03", "城东店", "展架", "展示架", "A区2号货架底层"],
            ["CP04", "城西店", "展架", "展示架", "B区3号货架中层"],
        ],
    )
    record(positions, "xlsx_positions", rows=4, note="记录型问答主表")

    stores = target / "容量合作店家信息.xlsx"
    write_xlsx(
        stores,
        ["标识", "门店", "联系人", "联系电话", "地址", "合作状态"],
        [
            ["CS01", "城东店", "陈青", "010-10000001", "东区一号路 1 号", "合作中"],
            ["CS02", "城西店", "林白", "010-10000002", "西区二号路 2 号", "合作中"],
            ["CS03", "滨河店", "周桐", "010-10000003", "滨河路 3 号", "暂停"],
            ["CS04", "城北店", "何叶", "010-10000004", "北区四号路 4 号", "合作中"],
        ],
    )
    record(stores, "xlsx_stores", rows=4, note="门店级记录（电话/联系人）")

    for index, row_count in enumerate(MISC_XLSX_ROWS, start=1):
        path = target / f"容量盘点清单{index:02d}.xlsx"
        rows = [
            [
                f"CL{index:02d}{row:04d}",
                f"容量仓C区{row % 10 + 1:02d}",
                f"容量物料C{index:02d}{row % 50 + 1:03d}",
                f"容量库位C{row % 20 + 1:03d}",
            ]
            for row in range(1, row_count + 1)
        ]
        write_xlsx(path, ["标识", "门店", "物品", "位置"], rows)
        record(path, "xlsx_misc", rows=row_count, note="补充 Excel 记录（不与题集实体重叠）")

    for index, prefix in enumerate(("A", "B"), start=1):
        path = target / f"容量明细表{prefix}.xlsx"
        rows = [
            [
                f"C{prefix}{row:06d}",
                f"容量仓{prefix}区{row % 10 + 1:02d}",
                f"容量物料{prefix}{row % 200 + 1:04d}",
                f"容量库位{prefix}{row % 50 + 1:03d}",
            ]
            for row in range(1, 5001)
        ]
        started = time.monotonic()
        write_xlsx(path, ["标识", "门店", "物品", "位置"], rows)
        record(path, "xlsx_big", rows=5000, note=f"大表 {index}/2；写入耗时 {round(time.monotonic() - started, 3)}s")

    for word in DOCX_WORDS:
        path = target / f"{word}文档.docx"
        write_docx(
            path,
            f"{word}文档",
            [
                f"{word}文档关键要求：领取物料前完成登记，由复核人确认。",
                f"{word}文档处理流程：先提交申请单，再由复核人核对。",
                f"适用范围：{word}文档仅用于容量测试。",
            ],
        )
        record(path, "docx")

    for index, word in enumerate(TEXT_PDF_WORDS, start=1):
        path = target / f"{word}说明.pdf"
        write_text_pdf(
            path,
            f"{word}说明",
            [
                f"{word}说明的注意事项：跨店调拨须两店复核人确认。",
                f"{word}说明适用范围：仅适用于容量测试。",
                f"登记编号：TM{index:02d}{scan_code(word)[-4:]}",
            ],
        )
        record(path, "text_pdf")

    for index, word in enumerate(SCAN_PDF_WORDS, start=1):
        stem = f"扫描说明{word}01"
        path = target / f"{stem}.pdf"
        write_scan_pdf(
            path,
            [stem, f"本页为扫描说明核验内容，登记序号 {index:02d}。", "登记人：容量测试。"],
        )
        record(path, "scan_pdf")

    for index, word in enumerate(SCAN_IMAGE_WORDS, start=1):
        stem = f"扫描样张{word}01"
        path = target / f"{stem}.png"
        write_image(
            path,
            [stem, f"本页为扫描件核验内容，登记序号 {index:02d}。", "登记人：容量测试。"],
        )
        record(path, "scan_image")

    manifest = {
        "label": "d5-dataset",
        "created_at": now_iso(),
        "file_count": len(files),
        "categories": {
            category: sum(1 for item in files if item["category"] == category)
            for category in sorted({item["category"] for item in files})
        },
        "files": files,
        "big_excel_rows": sum(item["rows"] or 0 for item in files if item["category"] == "xlsx_big"),
        "total_excel_rows": sum(item["rows"] or 0 for item in files if item["category"].startswith("xlsx")),
    }
    write_json(target / "dataset-manifest.json", manifest)
    return manifest


def ensure_dataset(dataset_dir: Path) -> dict:
    manifest_path = dataset_dir / "dataset-manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest["files"]:
            path = dataset_dir / item["name"]
            if not path.is_file() or sha256_path(path) != item["sha256"]:
                raise RuntimeError(f"数据集文件缺失或被改动：{path}")
        return manifest
    return build_dataset(dataset_dir)


# ---------------------------------------------------------------- DB 计数（只读）


def db_counts(db_path: Path) -> dict:
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=15)
    try:
        cur = con.cursor()

        def scalar(sql: str, params=()) -> int:
            row = cur.execute(sql, params).fetchone()
            return int(row[0]) if row and row[0] is not None else 0

        per_document = [
            {"name": name, "units": int(units)}
            for name, units in cur.execute(
                "select d.name, count(su.id) from documents d left join source_units su on su.document_id = d.id "
                "where d.deleted = 0 group by d.id order by d.name"
            ).fetchall()
        ]
        per_document_rows = []
        for item in per_document:
            table_rows = scalar(
                "select count(*) from source_units su join documents d on d.id = su.document_id "
                "where d.name = ? and su.kind = 'table_row'",
                (item["name"],),
            )
            per_document_rows.append({**item, "table_rows": table_rows})
        big_rows = [
            row
            for row in per_document_rows
            if row["name"].startswith("容量明细表")
        ]
        return {
            "db_path": str(db_path),
            "db_bytes": Path(db_path).stat().st_size if Path(db_path).is_file() else 0,
            "wal_bytes": (Path(str(db_path) + "-wal").stat().st_size if Path(str(db_path) + "-wal").is_file() else 0),
            "shm_bytes": (Path(str(db_path) + "-shm").stat().st_size if Path(str(db_path) + "-shm").is_file() else 0),
            "documents_live": scalar("select count(*) from documents where deleted = 0"),
            "documents_with_active": scalar(
                "select count(*) from documents where deleted = 0 and active_version_id is not null"
            ),
            "versions_total": scalar("select count(*) from document_versions"),
            "versions_published": scalar("select count(*) from document_versions where state = 'published'"),
            "versions_review_required": scalar(
                "select count(*) from document_versions where state = 'review_required'"
            ),
            "source_units_total": scalar("select count(*) from source_units"),
            "source_units_table_row": scalar("select count(*) from source_units where kind = 'table_row'"),
            "source_units_paragraph": scalar("select count(*) from source_units where kind = 'paragraph'"),
            "source_units_image_text": scalar("select count(*) from source_units where kind = 'image_text'"),
            "retrieval_unit_index_total": scalar("select count(*) from retrieval_unit_index"),
            "retrieval_field_index_total": scalar("select count(*) from retrieval_field_index"),
            "source_unit_fts_total": scalar("select count(*) from source_unit_fts"),
            "knowledge_revision": scalar("select revision from knowledge_state where id = 1"),
            "big_files": big_rows,
            "big_files_table_rows_total": sum(row["table_rows"] for row in big_rows),
            "per_document": per_document_rows,
        }
    finally:
        con.close()


def directory_size(path: Path) -> dict:
    files = 0
    total = 0
    for item in Path(path).rglob("*"):
        if item.is_file():
            files += 1
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return {"path": str(path), "files": files, "bytes": total}


# ---------------------------------------------------------------- 服务端（--serve）


CURRENT_STEM = contextvars.ContextVar("d5_capacity_stem", default=None)


class CapacityOCRStandIn:
    """受控 OCR 替身：只按“文档名 + 页码”生成确定性转录，逐次记录调用；不内置任何题目答案。"""

    def __init__(self, logger=None) -> None:
        self.calls: list[dict] = []
        self._lock = threading.Lock()
        self._logger = logger

    def recognize(self, page, *, mode):
        from mktkb.providers.types import OCRPageResult

        stem = CURRENT_STEM.get()
        if not stem:
            raise RuntimeError("容量 OCR 替身没有绑定文档名，拒绝识别（不允许编造内容）")
        text = ocr_text_for(stem, page.page)
        entry = {
            "stem": stem,
            "page": page.page,
            "mode": mode,
            "bbox": None if page.bbox is None else list(page.bbox),
            "content_bytes": len(page.content),
            "content_sha256": sha256_bytes(page.content),
            "text": text,
        }
        with self._lock:
            self.calls.append(entry)
        if self._logger is not None:
            self._logger.event(
                "ocr_call",
                stem=stem,
                page=page.page,
                mode=mode,
                content_bytes=entry["content_bytes"],
                content_sha256=entry["content_sha256"][:16],
                text_sha256=sha256_bytes(text.encode("utf-8"))[:16],
            )
        return OCRPageResult(text=text, provider_request_id=f"d5stub-{stem}-p{page.page}", confidence=90.0)

    def summary(self) -> list[dict]:
        with self._lock:
            return list(self.calls)


class CapacityWorker(threading.Thread):
    """单并发 worker：claim_job → 绑定文档名（OCR 替身）→ run_one_job。"""

    def __init__(self, app, logger, ocr, stop_event: threading.Event) -> None:
        super().__init__(name="capacity-worker", daemon=True)
        self.app = app
        self.logger = logger
        self.ocr = ocr
        self.stop_event = stop_event

    def run(self) -> None:
        from mktkb.documents.models import Document, DocumentVersion
        from mktkb.ingestion.worker import claim_job, run_one_job

        self.logger.event("worker_started", owner="capacity-worker", pid=os.getpid())
        while not self.stop_event.is_set():
            db = None
            try:
                db = self.app.state.db.session()
                lease = claim_job(db, owner="capacity-worker")
                if lease is None:
                    db.close()
                    db = None
                    self.stop_event.wait(WORKER_IDLE_SECONDS)
                    continue
                version = db.get(DocumentVersion, lease.version_id)
                document = db.get(Document, version.document_id) if version is not None else None
                stem = Path(document.name).stem if document is not None else None
                self.logger.event(
                    "claim",
                    job_id=str(lease.job_id),
                    version_id=str(lease.version_id),
                    document_name=getattr(document, "name", None),
                )
                token = CURRENT_STEM.set(stem or "")
                started = time.monotonic()
                try:
                    result = run_one_job(db, self.app.state.store, ocr=self.ocr, lease=lease, owner="capacity-worker")
                finally:
                    CURRENT_STEM.reset(token)
                self.logger.event(
                    "job_done",
                    job_id=str(result.job_id) if result.job_id else None,
                    state=result.state,
                    document_name=getattr(document, "name", None),
                    units_written=result.units_written,
                    units_reused=result.units_reused,
                    error_code=result.error_code,
                    seconds=round(time.monotonic() - started, 3),
                )
            except Exception as exc:  # noqa: BLE001 - worker 不得因单次异常退出
                self.logger.event("worker_error", type=type(exc).__name__, message=str(exc)[:300])
                self.stop_event.wait(0.2)
            finally:
                if db is not None:
                    try:
                        db.close()
                    except Exception:  # noqa: BLE001
                        pass
        self.logger.event("worker_stopped")


def serve(args) -> int:
    """真实 uvicorn 服务（容量轮专用进程）。"""
    for extra in (ROOT / "backend" / "src", ROOT / "backend" / "tests", ROOT / "backend" / "tests" / "acceptance"):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))

    import uvicorn
    from fastapi import APIRouter

    from support import b0
    from support.serve_acceptance import JsonlLogger, OutboundGuard
    from conftest import EvidenceEchoGateway
    from mktkb.auth.service import create_account
    from mktkb.main import create_app

    data_dir = Path(args.data_dir).resolve()
    log_file = Path(args.log_file).resolve()
    if data_dir.exists():
        print(f"ERROR data dir already exists: {data_dir}", file=sys.stderr, flush=True)
        return 2
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=False, exist_ok=False)

    logger = JsonlLogger(log_file)
    guard = OutboundGuard()
    guard.install()
    logger.event(
        "start",
        argv=list(sys.argv),
        cwd=str(Path.cwd()),
        python=sys.executable,
        python_version=platform.python_version(),
        platform=platform.platform(),
        pid=os.getpid(),
        label=args.label,
        data_dir=str(data_dir),
        log_file=str(log_file),
        host=args.host,
        port=int(args.port),
    )
    logger.event("outbound", phase="start", **guard.snapshot())

    settings = b0.make_settings(data_dir)
    b0.assert_fake_configuration(settings)
    origin = f"http://{args.host}:{int(args.port)}"
    settings.trusted_origins = list(dict.fromkeys([*settings.trusted_origins, origin, f"http://localhost:{int(args.port)}"]))
    logger.event(
        "config_asserted",
        fake_model_key=settings.model_api_key.get_secret_value() == b0.FAKE_MODEL_API_KEY,
        fake_model_base_url=settings.model_base_url == b0.FAKE_MODEL_BASE_URL,
        fake_ocr_id=settings.ocr_secret_id.get_secret_value() == b0.FAKE_OCR_SECRET_ID,
        fake_ocr_key=settings.ocr_secret_key.get_secret_value() == b0.FAKE_OCR_SECRET_KEY,
        trusted_origins=list(settings.trusted_origins),
        env_file="None (_env_file=None)",
    )

    model = EvidenceEchoGateway()
    ocr = CapacityOCRStandIn(logger)
    app = create_app(settings, model_gateway=model, ocr_gateway=ocr)
    if app.state.model_gateway is not model or app.state.ocr_gateway is not ocr:
        logger.event("gateway_error", message="注入的替身没有被应用采用")
        logger.close()
        return 1
    logger.event("app_created", data_dir=str(data_dir), database_url=settings.resolved_database_url())

    db = app.state.db.session()
    try:
        for username, password, display in EXTRA_ACCOUNTS:
            try:
                create_account(
                    db,
                    username=username,
                    password=password,
                    display_name=display,
                    role="employee",
                    rounds=settings.bcrypt_rounds,
                )
                logger.event("account_created", username=username, role="employee")
            except ValueError:
                logger.event("account_exists", username=username)
    finally:
        db.close()

    state = {"stop_event": threading.Event(), "server": None, "started_at": time.time(), "label": args.label}

    router = APIRouter(prefix="/__capacity")

    def counts() -> dict:
        try:
            return db_counts(data_dir / "mktkb.sqlite3")
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}

    @router.get("/state")
    def capacity_state() -> dict:
        snapshot = counts()
        outbound = guard.snapshot()
        payload = {
            "status": "ready",
            "label": state["label"],
            "pid": os.getpid(),
            "data_dir": str(data_dir),
            "uptime_seconds": round(time.time() - state["started_at"], 3),
            "revision": snapshot.get("knowledge_revision"),
            "outbound": outbound,
            "model_calls": len(model.calls),
            "ocr_calls": len(ocr.summary()),
            "documents_live": snapshot.get("documents_live"),
            "versions_published": snapshot.get("versions_published"),
            "source_units_total": snapshot.get("source_units_total"),
            "retrieval_unit_index_total": snapshot.get("retrieval_unit_index_total"),
            "source_unit_fts_total": snapshot.get("source_unit_fts_total"),
            "worker_alive": any(thread.name == "capacity-worker" and thread.is_alive() for thread in threading.enumerate()),
        }
        logger.event(
            "state_snapshot",
            revision=payload["revision"],
            documents_live=payload["documents_live"],
            versions_published=payload["versions_published"],
            source_units_total=payload["source_units_total"],
            model_calls=payload["model_calls"],
            ocr_calls=payload["ocr_calls"],
            outbound_external=list(outbound.get("external") or []),
            outbound_local_count=outbound.get("local_count"),
        )
        return payload

    @router.post("/shutdown")
    def capacity_shutdown() -> dict:
        logger.event("shutdown_requested", reason="control", note="容量轮结束，优雅停服")
        state["stop_event"].set()
        server = state["server"]
        if server is not None:
            server.should_exit = True
        return {"ok": True, "label": state["label"]}

    app.include_router(router)
    logger.event("control_router_mounted", prefix="/__capacity", routes=["GET /state", "POST /shutdown"])

    stop_event: threading.Event = state["stop_event"]
    worker = CapacityWorker(app, logger, ocr, stop_event)
    worker.start()
    logger.event("worker_thread_started", name=worker.name)

    config = uvicorn.Config(app, host=args.host, port=int(args.port), log_level="info", access_log=False, lifespan="on")
    server = uvicorn.Server(config)
    state["server"] = server

    def ready_watch() -> None:
        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline and not getattr(server, "started", False):
            if getattr(server, "should_exit", False):
                return
            time.sleep(0.05)
        if not getattr(server, "started", False):
            logger.event("ready_timeout", seconds=READY_TIMEOUT_SECONDS)
            return
        try:
            healthz_ms = wait_http_ready(f"http://{args.host}:{int(args.port)}/api/v1/healthz", 60.0)
        except Exception as exc:  # noqa: BLE001
            logger.event("healthz_error", type=type(exc).__name__, message=str(exc)[:300])
            return
        logger.event("ready", url=f"http://{args.host}:{int(args.port)}", healthz_ms=healthz_ms)
        print(f"CAPACITY READY http://{args.host}:{int(args.port)} ({healthz_ms} ms)", flush=True)

    threading.Thread(target=ready_watch, name="capacity-ready", daemon=True).start()
    exit_code = 0
    try:
        server.run()
    except BaseException as exc:  # noqa: BLE001
        exit_code = 1
        logger.event("server_error", type=type(exc).__name__, message=str(exc)[:500])
    finally:
        stop_event.set()
        worker.join(timeout=10)
        logger.event("outbound", phase="final", **guard.snapshot())
        logger.event(
            "shutdown",
            exit_code=exit_code,
            pid=os.getpid(),
            label=args.label,
            data_dir=str(data_dir),
            model_calls=len(model.calls),
            ocr_calls=len(ocr.summary()),
        )
        logger.close()
    return exit_code


# ---------------------------------------------------------------- 驱动端（一轮）


def _login(client, username: str, password: str, origin: str) -> dict:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password}, headers={"Origin": origin})
    if response.status_code != 200:
        raise RuntimeError(f"{username} 登录失败：HTTP {response.status_code} {response.text[:300]}")
    payload = response.json()
    csrf = payload.get("csrf_token")
    if not csrf:
        raise RuntimeError(f"{username} 登录响应缺少 csrf_token")
    me = client.get("/api/v1/auth/me")
    expected_role = "admin" if username == "admin" else "employee"
    if me.status_code != 200 or me.json().get("user", {}).get("role") != expected_role:
        raise RuntimeError(f"{username} /auth/me 不符：{me.status_code} {me.text[:300]}")
    return {"Origin": origin, "X-CSRF-Token": csrf}


def _upload(client, headers: dict, path: Path) -> dict:
    suffix = path.suffix.lower().lstrip(".")
    mime = MIME.get(suffix, "application/octet-stream")
    with path.open("rb") as handle:
        response = client.post(
            "/api/v1/documents",
            files={"file": (path.name, handle, mime)},
            data={"allow_same_name": "false"},
            headers=headers,
            timeout=600.0,
        )
    if response.status_code != 202:
        raise RuntimeError(f"上传 {path.name} 失败：HTTP {response.status_code} {response.text[:400]}")
    return response.json()


def _wait_job(client, headers: dict, job_id: str, timeout: float = JOB_TIMEOUT_SECONDS) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers, timeout=60.0)
        if response.status_code != 200:
            raise RuntimeError(f"查询任务 {job_id} 失败：HTTP {response.status_code} {response.text[:300]}")
        last = response.json()
        if last["state"] in {"succeeded", "failed", "blocked", "cancelled"}:
            return last
        time.sleep(0.05)
    raise TimeoutError(f"等待任务 {job_id} 超时（最后状态 {last and last.get('state')}）")


def _publish(client, headers: dict, document_id: str, version_id: str, revision: int) -> dict:
    response = client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        json={"expected_active_version_id": None, "expected_revision": revision},
        headers=headers,
        timeout=600.0,
    )
    if response.status_code != 200:
        raise RuntimeError(f"发布 {document_id} 失败：HTTP {response.status_code} {response.text[:400]}")
    return response.json()


def _detail(client, headers: dict, document_id: str) -> dict:
    response = client.get(f"/api/v1/documents/{document_id}", headers=headers, timeout=60.0)
    if response.status_code != 200:
        raise RuntimeError(f"读取资料 {document_id} 失败：HTTP {response.status_code} {response.text[:300]}")
    return response.json()


def _ask(client, headers: dict, conversation_id: str, question: str) -> tuple[dict, dict, float, float]:
    started_conv = time.perf_counter()
    created = client.post("/api/v1/conversations", json={}, headers=headers, timeout=60.0)
    conv_ms = (time.perf_counter() - started_conv) * 1000
    if created.status_code != 201:
        raise RuntimeError(f"新建会话失败：HTTP {created.status_code} {created.text[:300]}")
    conversation = created.json()["id"]
    started = time.perf_counter()
    response = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=headers,
        timeout=ASK_TIMEOUT_SECONDS,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:500]}
    return payload, {"status": response.status_code, "conversation_id": conversation}, round(conv_ms, 1), round(elapsed_ms, 1)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((percentile / 100.0) * (len(ordered) - 1)))))
    return round(ordered[index], 1)


def _latency_stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "mean_ms": round(statistics.fmean(values), 1),
        "p50_ms": _percentile(values, 50),
        "p95_ms": _percentile(values, 95),
        "max_ms": round(max(values), 1),
        "min_ms": round(min(values), 1),
    }


def _question_result(user: str, phase: str, spec: dict, payload: dict, http: dict, conv_ms: float, ask_ms: float) -> dict:
    expected = expected_value(spec)
    text = str(payload.get("text") or "")
    kind = payload.get("kind")
    sources = payload.get("sources") or []
    return {
        "user": user,
        "phase": phase,
        "question_id": spec["id"],
        "category": spec["category"],
        "question": spec["question"],
        "status": http["status"],
        "kind": kind,
        "expect_kind": spec["expect_kind"],
        "kind_ok": kind == spec["expect_kind"],
        "expect_value": expected,
        "value_ok": expected in text,
        "source_count": len(sources),
        "source_names": [source.get("document_name") for source in sources][:8],
        "text_chars": len(text),
        "text_head": text[:160],
        "error_code": payload.get("error_code"),
        "conversation_ms": conv_ms,
        "ask_ms": ask_ms,
        "at": now_iso(),
    }


def _run_question_set(client, headers, user: str, phase: str, specs, offset: int = 0) -> list[dict]:
    results = []
    for spec in specs:
        payload, http, conv_ms, ask_ms = _ask(client, headers, "", spec["question"])
        results.append(_question_result(user, phase, spec, payload, http, conv_ms, ask_ms))
    return results


def run(args) -> int:
    import httpx

    evidence_root = Path(args.evidence_root).resolve()
    label = args.label
    logs = evidence_root / "logs"
    actual = evidence_root / "actual" / label
    run_tmp = evidence_root / "tmp" / f"capacity-{label}"
    data_dir = run_tmp / "data"
    input_dir = run_tmp / "files"
    server_jsonl = logs / f"capacity-server-{label}.jsonl"
    server_stdout = logs / f"capacity-server-{label}.stdout.log"
    server_stderr = logs / f"capacity-server-{label}.stderr.log"
    dataset_dir = evidence_root / "tmp" / "dataset-master"

    for path in (actual, data_dir, input_dir, server_jsonl):
        if path.exists():
            print(f"ERROR 已存在，拒绝覆盖：{path}", file=sys.stderr, flush=True)
            return 2
    logs.mkdir(parents=True, exist_ok=True)
    actual.mkdir(parents=True, exist_ok=False)
    run_tmp.mkdir(parents=True, exist_ok=True)

    started_wall = now_iso()
    started_mono = time.monotonic()
    checks: list[dict] = []
    admin_client = None
    clients: dict[str, httpx.Client] = {}
    sampler: ProcessSampler | None = None
    server_proc: subprocess.Popen | None = None
    server_exit: int | None = None
    ready_ms: float | None = None
    phase = "startup"
    run_record: dict = {
        "label": label,
        "argv": list(sys.argv),
        "cwd": str(Path.cwd()),
        "python": sys.executable,
        "started_at": started_wall,
        "ended_at": None,
        "duration_seconds": None,
        "machine": machine_facts(ROOT),
        "dataset": None,
        "server": {"command": [], "pid": None, "ready_ms": None, "exit_code": None, "jsonl": str(server_jsonl)},
        "phases": {},
        "checks": checks,
        "failed_checks": [],
        "outbound": None,
        "exit_code": None,
    }

    def add_check(name: str, ok: bool, detail=None) -> None:
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    def state_json() -> dict:
        assert admin_client is not None
        response = admin_client.get("/__capacity/state", timeout=120.0)
        if response.status_code != 200:
            raise RuntimeError(f"读取容量状态失败：HTTP {response.status_code} {response.text[:300]}")
        return response.json()

    try:
        # ---- 0. 数据集（只在证据 tmp 生成一次；本轮复制为独立输入） ----
        dataset = ensure_dataset(dataset_dir)
        run_record["dataset"] = {
            "master_dir": str(dataset_dir),
            "manifest_sha256": sha256_path(dataset_dir / "dataset-manifest.json"),
            "file_count": dataset["file_count"],
            "categories": dataset["categories"],
            "big_excel_rows": dataset["big_excel_rows"],
            "total_excel_rows": dataset["total_excel_rows"],
        }
        input_dir.mkdir(parents=True, exist_ok=False)
        input_files: list[dict] = []
        for item in dataset["files"]:
            source = dataset_dir / item["name"]
            target = input_dir / item["name"]
            shutil.copyfile(source, target)
            digest = sha256_path(target)
            if digest != item["sha256"]:
                raise RuntimeError(f"输入复制后哈希不一致：{item['name']}")
            input_files.append({**item, "path": str(target)})
        if int(getattr(args, "debug_max_files", 0) or 0):
            input_files = input_files[: int(args.debug_max_files)]

        # ---- 1. 端口与服务启动 ----
        port_check = check_port_free(int(args.port), args.host)
        run_record["port_before"] = port_check
        add_check("port_available", not port_check["in_use"], port_check)
        if port_check["in_use"]:
            raise RuntimeError(f"端口 {args.port} 已被占用：{port_check}")
        data_dir.parent.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-B",
            str(HERE),
            "--serve",
            "--label",
            label,
            "--data-dir",
            str(data_dir),
            "--log-file",
            str(server_jsonl),
            "--host",
            args.host,
            "--port",
            str(int(args.port)),
        ]
        run_record["server"]["command"] = command
        env = {key: value for key, value in os.environ.items() if not key.startswith("MKTKB_")}
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        with server_stdout.open("w", encoding="utf-8") as out_handle, server_stderr.open("w", encoding="utf-8") as err_handle:
            server_proc = subprocess.Popen(command, cwd=str(ROOT), stdout=out_handle, stderr=err_handle, env=env)
        run_record["server"]["pid"] = server_proc.pid
        phase = "startup"
        ready_ms = wait_http_ready(f"http://{args.host}:{int(args.port)}/api/v1/healthz", READY_TIMEOUT_SECONDS, server_proc)
        run_record["server"]["ready_ms"] = ready_ms
        add_check("server_ready", True, {"ready_ms": ready_ms})

        origin = f"http://{args.host}:{int(args.port)}"
        admin_client = httpx.Client(base_url=f"http://{args.host}:{int(args.port)}", timeout=300.0, trust_env=False)
        admin_headers = _login(admin_client, ADMIN[0], ADMIN[1], origin)
        session_clients: dict[str, tuple[httpx.Client, dict]] = {}
        for username, password in USERS:
            client = httpx.Client(
                base_url=f"http://{args.host}:{int(args.port)}", timeout=ASK_TIMEOUT_SECONDS, trust_env=False
            )
            headers = _login(client, username, password, origin)
            session_clients[username] = (client, headers)
            clients[username] = client
        run_record["accounts"] = sorted(session_clients)
        add_check("logins", len(session_clients) == 3, sorted(session_clients))

        state_start = state_json()
        run_record["state_start"] = state_start
        run_record["server"]["popen_pid"] = server_proc.pid
        run_record["server"]["service_pid"] = state_start.get("pid")
        add_check("service_pid_matches", state_start.get("pid") is not None, state_start.get("pid"))
        add_check("outbound_start_empty", state_start["outbound"]["external"] == [], state_start["outbound"])

        # 采样真实服务进程（Windows venv 的 python.exe 是启动器，Popen pid 可能不是服务进程）。
        sampler = ProcessSampler(int(state_start["pid"]))
        sampler.set_phase("startup")
        sampler.start()

        # ---- 2. 入库：50 份真实 HTTP 上传 → worker → 发布 ----
        phase = "ingest"
        if sampler is not None:
            sampler.set_phase("ingest")
        ingest_started_at = now_iso()
        ingest_started = time.monotonic()
        files: list[dict] = []
        ingest_errors: list[str] = []
        for index, item in enumerate(input_files, start=1):
            path = Path(item["path"])
            file_started = time.monotonic()
            record: dict = {
                "index": index,
                "name": path.name,
                "category": item["category"],
                "input_bytes": item["bytes"],
                "input_sha256": item["sha256"],
            }
            try:
                upload_started = time.monotonic()
                receipt = _upload(admin_client, admin_headers, path)
                record["upload_ms"] = round((time.monotonic() - upload_started) * 1000, 1)
                document_id = receipt["document"]["id"]
                version_id = receipt["version"]["id"]
                job_id = receipt["job"]["id"]
                record.update({"document_id": document_id, "version_id": version_id, "job_id": job_id})
                job_started = time.monotonic()
                job = _wait_job(admin_client, admin_headers, job_id)
                record["job_wait_ms"] = round((time.monotonic() - job_started) * 1000, 1)
                record["job_state"] = job["state"]
                record["job_pages"] = [job.get("completed_pages"), job.get("total_pages")]
                if job["state"] != "succeeded":
                    raise RuntimeError(f"任务未成功：{job['state']} {job.get('error_code')} {job.get('message')}")
                detail = _detail(admin_client, admin_headers, document_id)
                publish_started = time.monotonic()
                publication = _publish(admin_client, admin_headers, document_id, version_id, int(detail["revision"]))
                record["publish_ms"] = round((time.monotonic() - publish_started) * 1000, 1)
                record["publish_revision"] = publication["revision"]
                record["ok"] = True
            except Exception as exc:  # noqa: BLE001 - 单个文件失败要如实记录
                record["ok"] = False
                record["error"] = f"{type(exc).__name__}: {exc}"
                ingest_errors.append(f"{path.name}: {record['error']}")
            record["total_ms"] = round((time.monotonic() - file_started) * 1000, 1)
            files.append(record)
            print(f"UPLOAD {index:02d}/50 {path.name} ok={record['ok']} total_ms={record['total_ms']}", flush=True)
            if not record["ok"]:
                break
        ingest_seconds = round(time.monotonic() - ingest_started, 3)
        job_states: dict[str, int] = {}
        for item in files:
            state_name = str(item.get("job_state") or "error")
            job_states[state_name] = job_states.get(state_name, 0) + 1
        counts_after_ingest = db_counts(data_dir / "mktkb.sqlite3")
        state_after_ingest = state_json()
        run_record["phases"]["ingest"] = {
            "started_at": ingest_started_at,
            "seconds": ingest_seconds,
            "files_ok": sum(1 for item in files if item.get("ok")),
            "files_failed": sum(1 for item in files if not item.get("ok")),
            "job_states": job_states,
            "errors": ingest_errors,
            "state": state_after_ingest,
        }
        add_check("ingest_all_files_ok", not ingest_errors and len(files) == 50, {"files": len(files), "errors": ingest_errors})
        add_check("documents_50", counts_after_ingest["documents_live"] == 50, counts_after_ingest["documents_live"])
        add_check("versions_published_50", counts_after_ingest["versions_published"] == 50, counts_after_ingest["versions_published"])
        add_check(
            "big_excel_10000_rows",
            counts_after_ingest["big_files_table_rows_total"] == 10000,
            {"total": counts_after_ingest["big_files_table_rows_total"], "big_files": counts_after_ingest["big_files"]},
        )
        add_check(
            "fts_rows_match_units",
            counts_after_ingest["source_unit_fts_total"] == counts_after_ingest["source_units_total"],
            {
                "fts": counts_after_ingest["source_unit_fts_total"],
                "units": counts_after_ingest["source_units_total"],
            },
        )
        add_check(
            "outbound_after_ingest_empty",
            state_after_ingest["outbound"]["external"] == [],
            state_after_ingest["outbound"],
        )

        # ---- 3. 问答：1 用户基线 + 3 用户并发 ----
        if not ingest_errors and not getattr(args, "debug_skip_qa", False):
            phase = "warmup"
            if sampler is not None:
                sampler.set_phase("warmup")
            warm_payload, warm_http, warm_conv, warm_ask = _ask(*session_clients["employee"], "", QUESTION_SPECS[0]["question"])
            run_record["warmup"] = {
                "status": warm_http["status"],
                "kind": warm_payload.get("kind"),
                "ask_ms": warm_ask,
                "conversation_ms": warm_conv,
            }
            add_check(
                "warmup_answer",
                warm_http["status"] == 200 and warm_payload.get("kind") == "answer",
                {"kind": warm_payload.get("kind"), "status": warm_http["status"]},
            )

            phase = "qa_baseline"
            if sampler is not None:
                sampler.set_phase("qa_baseline")
            baseline_started = time.monotonic()
            baseline_results = _run_question_set(*session_clients["employee"], "employee", "baseline", QUESTION_SPECS)
            baseline_seconds = round(time.monotonic() - baseline_started, 3)
            run_record["phases"]["qa_baseline"] = {
                "seconds": baseline_seconds,
                "requests": len(baseline_results),
                "latency": _latency_stats([item["ask_ms"] for item in baseline_results]),
                "throughput_rps": round(len(baseline_results) / baseline_seconds, 3) if baseline_seconds else None,
            }

            phase = "qa_load"
            if sampler is not None:
                sampler.set_phase("qa_load")
            load_results: list[dict] = []
            errors: list[str] = []
            lock = threading.Lock()
            barrier = threading.Barrier(len(USERS))
            load_started = time.monotonic()

            def worker_thread(username: str) -> None:
                client, headers = session_clients[username]
                try:
                    barrier.wait(timeout=60)
                except threading.BrokenBarrierError:
                    pass
                try:
                    local = _run_question_set(client, headers, username, "load", QUESTION_SPECS)
                except Exception as exc:  # noqa: BLE001
                    with lock:
                        errors.append(f"{username}: {type(exc).__name__}: {exc}")
                    return
                with lock:
                    load_results.extend(local)

            threads = [threading.Thread(target=worker_thread, args=(username,), name=f"capacity-user-{username}") for username, _ in USERS]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=ASK_TIMEOUT_SECONDS + 60)
            load_seconds = round(time.monotonic() - load_started, 3)
            load_results.sort(key=lambda item: (item["question_id"], item["user"]))
            run_record["phases"]["qa_load"] = {
                "seconds": load_seconds,
                "users": len(USERS),
                "requests": len(load_results),
                "errors": errors,
                "latency": _latency_stats([item["ask_ms"] for item in load_results]),
                "throughput_rps": round(len(load_results) / load_seconds, 3) if load_seconds else None,
                "per_user": {
                    username: _latency_stats([item["ask_ms"] for item in load_results if item["user"] == username])
                    for username, _ in USERS
                },
            }
            all_results = baseline_results + load_results
            http_errors = [item for item in all_results if item["status"] != 200]
            server_errors = [item for item in http_errors if 500 <= int(item["status"]) < 600]
            unexpected_kind = [item for item in all_results if not item["kind_ok"]]
            value_mismatch = [item for item in all_results if not item["value_ok"]]
            add_check("qa_requests_30", len(load_results) == 30, len(load_results))
            add_check("qa_zero_5xx", not server_errors, [item["question_id"] for item in server_errors])
            add_check("qa_zero_http_errors", not http_errors, [(item["user"], item["question_id"], item["status"]) for item in http_errors])
            add_check("qa_expected_kinds", not unexpected_kind, [(item["user"], item["question_id"], item["kind"]) for item in unexpected_kind])
            add_check("qa_expected_values", not value_mismatch, [(item["user"], item["question_id"]) for item in value_mismatch])
            add_check("qa_no_thread_errors", not errors, errors)
            write_json(actual / "requests.json", {
                "label": label,
                "baseline": baseline_results,
                "load": load_results,
                "warmup": run_record.get("warmup"),
            })
        else:
            add_check("qa_skipped", False, "入库失败或调试模式跳过问答阶段")

        # ---- 4. 收尾：终态、停服、端口释放、DB 与尺寸 ----
        phase = "finalize"
        if sampler is not None:
            sampler.set_phase("finalize")
        state_final = state_json()
        run_record["state_final"] = state_final
        add_check("outbound_final_empty", state_final["outbound"]["external"] == [], state_final["outbound"])
        add_check(
            "ocr_calls_expected",
            state_final["ocr_calls"] >= len(SCAN_PDF_WORDS) + len(SCAN_IMAGE_WORDS),
            {"observed": state_final["ocr_calls"], "minimum": len(SCAN_PDF_WORDS) + len(SCAN_IMAGE_WORDS)},
        )
        add_check("model_calls_positive", state_final["model_calls"] > 0, state_final["model_calls"])

        # 先停采样再停服：避免把进程退出后的零值计入阶段峰值。
        sampler.stop_event.set()
        sampler.join(timeout=5)
        resources = sampler.summary()
        write_json(actual / "resources.json", {"label": label, **resources})
        run_record["resources"] = {key: value for key, value in resources.items() if key != "samples"}

        shutdown_response = admin_client.post("/__capacity/shutdown", json={}, timeout=60.0)
        add_check("shutdown_accepted", shutdown_response.status_code == 200, shutdown_response.status_code)
        try:
            server_exit = server_proc.wait(timeout=SERVER_EXIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            server_proc.terminate()
            try:
                server_exit = server_proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server_proc.kill()
                server_exit = -9
        run_record["server"]["exit_code"] = server_exit
        add_check("server_exit_zero", server_exit == 0, server_exit)
        time.sleep(0.5)
        port_after = check_port_free(int(args.port), args.host)
        run_record["port_after"] = port_after
        add_check("port_released", not port_after["in_use"], port_after)

        counts_final = db_counts(data_dir / "mktkb.sqlite3")
        sizes = {
            "data_dir": directory_size(data_dir),
            "input_dir": directory_size(input_dir),
            "db": {
                "bytes": counts_final["db_bytes"],
                "wal_bytes": counts_final["wal_bytes"],
                "shm_bytes": counts_final["shm_bytes"],
            },
        }
        run_record["sizes"] = sizes
        write_json(actual / "files.json", {"label": label, "files": files})
        write_json(actual / "db-counts.json", {"label": label, "after_ingest": counts_after_ingest, "final": counts_final})
        write_json(actual / "outbound.json", {"label": label, "start": state_start, "after_ingest": state_after_ingest, "final": state_final})
    except BaseException as exc:  # noqa: BLE001 - 失败必须落证据
        run_record["error"] = f"{type(exc).__name__}: {exc}"
        run_record["traceback"] = traceback.format_exc()[-4000:]
        add_check("run_completed", False, run_record["error"])
    finally:
        if server_proc is not None and server_proc.poll() is None:
            try:
                admin_client.post("/__capacity/shutdown", json={}, timeout=30.0) if admin_client else None
                server_exit = server_proc.wait(timeout=SERVER_EXIT_TIMEOUT_SECONDS)
            except Exception:  # noqa: BLE001
                server_proc.terminate()
                try:
                    server_exit = server_proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    server_proc.kill()
                    server_exit = -9
        run_record["server"]["exit_code"] = server_exit if server_exit is not None else run_record["server"].get("exit_code")
        if sampler is not None:
            sampler.stop_event.set()
            sampler.join(timeout=5)
            if "resources" not in run_record:
                resources = sampler.summary()
                write_json(actual / "resources.json", {"label": label, **resources})
                run_record["resources"] = {key: value for key, value in resources.items() if key != "samples"}
        for client in clients.values():
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
        if admin_client is not None:
            try:
                admin_client.close()
            except Exception:  # noqa: BLE001
                pass
        failed = [check for check in checks if not check["pass"]]
        run_record["failed_checks"] = failed
        outbound_empty = bool(
            run_record.get("state_final", {}).get("outbound", {}).get("external") == []
            and run_record.get("state_start", {}).get("outbound", {}).get("external") == []
        )
        run_record["exit_code"] = 0 if (not failed and outbound_empty and run_record["server"]["exit_code"] == 0) else 1
        run_record["ended_at"] = now_iso()
        run_record["duration_seconds"] = round(time.monotonic() - started_mono, 3)
        write_json(actual / "run.json", run_record)
        print(
            json.dumps(
                {
                    "label": label,
                    "exit_code": run_record["exit_code"],
                    "failed": [check["name"] for check in failed],
                    "duration_seconds": run_record["duration_seconds"],
                    "outbound": run_record.get("state_final", {}).get("outbound"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return int(run_record["exit_code"])


# ---------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="T09-D5 容量/压力基线执行器（本机 L 层）")
    parser.add_argument("--label", required=True)
    parser.add_argument("--evidence-root", default=None, help="证据根目录；默认 docs/evidence/T09/D5")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--log-file", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--debug-max-files", type=int, default=0, help="调试：只入库前 N 份（0=全部，非正式轮不用）")
    parser.add_argument("--debug-skip-qa", action="store_true", help="调试：跳过问答阶段")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    if args.serve:
        if not args.data_dir or not args.log_file:
            print("--serve 需要 --data-dir 与 --log-file", file=sys.stderr)
            return 2
        return serve(args)
    args.evidence_root = args.evidence_root or str(ROOT / "docs" / "evidence" / "T09" / "D5")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
