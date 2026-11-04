"""Local launcher. Enter/Ctrl+C stops only the services started by this process."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend/src'))


def free_port(first: int) -> int:
    for port in range(first, first + 30):
        with socket.socket() as probe:
            if os.name == 'nt':
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                probe.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    raise RuntimeError(f'没有可用端口：{first}–{first + 29}')


def wait_ready(url, alive, *, json_health=False):
    import httpx
    with httpx.Client(timeout=1.0, trust_env=False) as client:
        for _ in range(150):
            if not alive():
                raise RuntimeError('服务启动失败，请查看启动窗口和前端日志。')
            try:
                response = client.get(url)
                if response.status_code == 200 and (not json_health or response.json() == {'status': 'ok'}):
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.2)
    raise RuntimeError(f'等待本机服务超时：{url}')


def available_commit_bytes() -> int | None:
    """Windows 下返回当前还能提交的内存（物理内存 + 页面文件剩余）；其它平台返回 None。"""
    if os.name != 'nt':
        return None
    import ctypes

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ('dwLength', ctypes.c_ulong),
            ('dwMemoryLoad', ctypes.c_ulong),
            ('ullTotalPhys', ctypes.c_ulonglong),
            ('ullAvailPhys', ctypes.c_ulonglong),
            ('ullTotalPageFile', ctypes.c_ulonglong),
            ('ullAvailPageFile', ctypes.c_ulonglong),
            ('ullTotalVirtual', ctypes.c_ulonglong),
            ('ullAvailVirtual', ctypes.c_ulonglong),
            ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
    except (AttributeError, OSError):
        return None
    return int(status.ullAvailPageFile)


def read_log_tail(path, limit: int = 40) -> str:
    try:
        text = Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    return '\n'.join(text.splitlines()[-limit:])


def start_frontend(node, vite, frontend_port, base, origin, log_dir, smoke):
    """启动 Vite；首次启动失败（如系统内存瞬时不足）自动以更低内存占用重试一次。"""
    for attempt in (1, 2):
        log_path = log_dir / f'frontend-{datetime.now():%Y%m%d-%H%M%S-%f}-try{attempt}.log'
        env = os.environ.copy()
        env['T08_BACKEND_ORIGIN'] = base
        command = [node, str(vite), '--host', '127.0.0.1', '--port', str(frontend_port), '--strictPort']
        if attempt > 1:
            # 第 2 次尝试跳过 Node 启动快照，降低启动阶段的内存峰值。
            command.insert(1, '--no-node-snapshot')
        with log_path.open('w', encoding='utf-8') as log:
            # Run node directly so cleanup targets Vite, not an npm.cmd wrapper.
            frontend = subprocess.Popen(command, cwd=ROOT / 'frontend', env=env, stdout=log,
                                        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            try:
                wait_ready(origin + '/api/v1/healthz', lambda: frontend.poll() is None, json_health=True)
                return frontend, log_path
            except RuntimeError:
                if frontend.poll() is None:
                    frontend.kill()
                    try:
                        frontend.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                tail = read_log_tail(log_path).lower()
                if attempt == 1:
                    if not smoke:
                        print('前台页面首次启动失败，正在以更低内存占用重试一次……', flush=True)
                    time.sleep(2.0)
                    continue
                if 'out of memory' in tail or 'memorychunk allocation failed' in tail or 'enomem' in tail:
                    reason = '系统可用内存不足（Node 启动时内存分配失败）。请关闭部分占用内存较大的程序后重试。'
                else:
                    reason = '请查看前端日志。'
                raise RuntimeError(f'前台页面启动失败：{reason}\n前端日志：{log_path.resolve()}') from None
    raise RuntimeError('前台页面启动失败，请查看前端日志。')


def worker_loop(app, stop):
    from mktkb.ingestion.worker import OcrRateLimiter, run_one_job
    settings = app.state.settings
    limiter = OcrRateLimiter(max_per_second=settings.ocr_max_requests_per_second)
    options = {
        'max_attempts': settings.ocr_max_attempts,
        'retry_base_seconds': settings.ocr_retry_base_seconds,
        'retry_max_single_seconds': settings.ocr_retry_max_single_seconds,
        'retry_total_seconds': settings.ocr_retry_total_seconds,
    }
    while not stop.is_set():
        db = app.state.db.session()
        try:
            run_one_job(db, app.state.store, ocr=app.state.ocr_gateway, ocr_limiter=limiter,
                        ocr_options=options, lease_seconds=settings.job_lease_seconds,
                        renew_seconds=settings.job_lease_renew_seconds)
        except Exception as exc:
            # Do not print credentials or provider request bodies from exceptions.
            print(f'文件处理暂时失败（{type(exc).__name__}），请查看资料页面的处理状态。', flush=True)
        finally:
            db.close()
        stop.wait(0.5)


def smoke_check(base, origin):
    import httpx
    manifest = json.loads((ROOT / 'fixtures/acceptance/manifest.json').read_text(encoding='utf-8'))
    word = next(row for row in manifest['normal_files'] if row['id'] == 'D03')
    with httpx.Client(base_url=base, headers={'Origin': origin}, timeout=10, trust_env=False) as client:
        login = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'launcher-smoke-admin'})
        login.raise_for_status()
        client.headers['X-CSRF-Token'] = login.json()['csrf_token']
        with (ROOT / 'fixtures/acceptance' / word['path']).open('rb') as content:
            response = client.post('/api/v1/documents', files={'file': ('launcher-word.docx', content)})
        response.raise_for_status()
        job_id = response.json()['job']['id']
        for _ in range(80):
            job = client.get(f'/api/v1/jobs/{job_id}').json()
            if job['state'] == 'succeeded':
                return {'backend': True, 'frontend': True, 'login': True, 'word_import': True}
            if job['state'] in {'failed', 'blocked', 'cancelled'}:
                raise RuntimeError('Word 自动处理检查失败。')
            time.sleep(0.25)
    raise RuntimeError('Word 自动处理检查超时。')


def sanitize_no_proxy() -> None:
    """清掉 NO_PROXY 里 httpx 无法解析的写法（本机实测）。

    httpx 0.28 会把 NO_PROXY 的每一项当 URL 解析；Windows 上常见的
    ``NO_PROXY=localhost,127.0.0.1,::1,[::1]`` 会让 ``httpx.Client()`` 在构造阶段
    抛 ``InvalidURL: Invalid port: ':1]'``，产品一创建 provider 客户端就崩。
    这里只去掉含 IPv6 冒号的条目（保留 localhost/127.0.0.1），不改代理本体。
    """
    for key in ('NO_PROXY', 'no_proxy'):
        raw = os.environ.get(key)
        if not raw:
            continue
        kept = [item.strip() for item in raw.split(',') if item.strip() and ':' not in item]
        os.environ[key] = ','.join(kept)


def run(smoke: bool):
    import httpx
    import uvicorn
    from mktkb.config import Settings
    from mktkb.main import create_app

    sanitize_no_proxy()
    # .env 既要给 pydantic Settings 用，也要给直接读 os.environ 的 RAG 配置用
    # （rag.config.RagConfig.from_env 读 DASHSCOPE_API_KEY / MKTKB_MODEL_* ）。
    # 用 override=False：调用方显式设置的进程环境优先，不被 .env 覆盖。
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / '.env', override=False, encoding='utf-8')
    except Exception:  # noqa: BLE001 - 缺 dotenv 时仍按既有 Settings 路径运行
        pass
    os.chdir(ROOT)
    node = shutil.which('node')
    vite = ROOT / 'frontend/node_modules/vite/bin/vite.js'
    if not node or not vite.is_file():
        raise RuntimeError('未找到现有 Node/Vite 依赖，请先准备项目运行环境。')
    backend_port, frontend_port = free_port(8077), free_port(5673)
    base, origin = f'http://127.0.0.1:{backend_port}', f'http://127.0.0.1:{frontend_port}'
    if smoke:
        evidence = ROOT / 'docs/evidence/local-launcher-smoke'
        evidence.mkdir(parents=True, exist_ok=True)
        data = Path(tempfile.mkdtemp(prefix='run-', dir=evidence))
        settings = Settings(_env_file=None, data_dir=data,
                            database_url=f'sqlite:///{(data / "mktkb.sqlite3").as_posix()}',
                            storage_dir=data / 'storage', trusted_origins=[base, origin], cookie_secure=False,
                            csrf_secret='launcher-smoke-csrf-secret', bcrypt_rounds=4,
                            admin_username='admin', admin_password='launcher-smoke-admin',
                            employee_password='launcher-smoke-employee', model_base_url=None,
                            model_name=None, model_api_key=None, ocr_secret_id=None, ocr_secret_key=None)
    else:
        settings = Settings(_env_file=ROOT / '.env')
        settings = settings.model_copy(update={
            'trusted_origins': list(dict.fromkeys([*settings.trusted_origins, base, origin])),
            'cookie_secure': False,
        })
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    log_dir = settings.data_dir / 'launcher-logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=backend_port, log_level='warning'))
    backend = threading.Thread(target=server.run, name='local-api', daemon=True)
    stop = threading.Event()
    worker = None
    frontend = None
    result = None
    try:
        if not smoke:
            print('正在启动本机后端……', flush=True)
        backend.start()
        try:
            wait_ready(base + '/api/v1/healthz', lambda: backend.is_alive(), json_health=True)
        except RuntimeError:
            raise RuntimeError('本机后端启动失败，请检查 .env 配置、依赖和上方错误信息。') from None
        if not smoke:
            print('正在启动前台页面……', flush=True)
            available = available_commit_bytes()
            if available is not None and available < 1 << 30:
                print(f'提示：系统可用内存偏低（剩余可提交约 {available / (1 << 30):.1f} GB），'
                      '前台页面若启动失败请先关闭部分程序再试。', flush=True)
        frontend, log_path = start_frontend(node, vite, frontend_port, base, origin, log_dir, smoke)
        if not smoke:
            print('正在启动文件自动处理……', flush=True)
        worker = threading.Thread(target=worker_loop, args=(app, stop), name='local-worker', daemon=True)
        worker.start()
        if smoke:
            result = smoke_check(base, origin)
        else:
            print(f'\n主人，项目已启动：{origin}\n数据目录：{settings.data_dir.resolve()}\n前端日志：{log_path.resolve()}')
            print('登录账号使用 .env 中配置的管理员/员工用户名与口令。')
            print('上传文件会自动处理；问答和扫描件使用现有真实服务配置。')
            webbrowser.open(origin)
            input('\n窗口保留期间服务持续运行。按回车或 Ctrl+C 停止本次服务：')
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        if not smoke and (frontend is not None or worker is not None):
            print('正在停止本次服务……', flush=True)
        stop.set()
        if frontend is not None and frontend.poll() is None:
            if os.name == 'nt':
                # taskkill 一并清理 Vite 可能派生的子进程；被系统拒绝时再直接结束本进程。
                subprocess.run(['taskkill', '/PID', str(frontend.pid), '/T', '/F'], capture_output=True)
            else:
                frontend.terminate()
            try:
                frontend.wait(timeout=15)
            except subprocess.TimeoutExpired:
                frontend.kill()
                try:
                    frontend.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print('前台进程未能在 20 秒内退出，请手动关闭对应窗口。', flush=True)
        if worker is not None:
            if worker.is_alive() and not smoke:
                print('正在等待当前文件处理结束并保存状态……', flush=True)
            worker.join()
        server.should_exit = True
        backend.join(timeout=15)
        if result is not None:
            with httpx.Client(timeout=0.5, trust_env=False) as client:
                def released(url):
                    try:
                        client.get(url)
                        return False
                    except httpx.HTTPError:
                        return True
                result['ports_released'] = released(base + '/api/v1/healthz') and released(origin)
            print('SMOKE_RESULT=' + json.dumps(result, ensure_ascii=False), flush=True)
    if smoke and result is None:
        raise RuntimeError('启动自检未完成。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='市场部 AI 知识库本机启动')
    parser.add_argument('--smoke-test', action='store_true', help='临时空库检查，禁用真实模型/OCR，完成即停服')
    args = parser.parse_args()
    try:
        run(args.smoke_test)
    except Exception as exc:
        # Settings hides configuration inputs in its validation errors.
        if isinstance(exc, RuntimeError):
            print(f'启动失败：{exc}', file=sys.stderr)
        else:
            print(f'启动失败（{type(exc).__name__}），请检查现有 .env、依赖及启动日志。', file=sys.stderr)
        sys.exit(1)
