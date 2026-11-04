import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { E2E_DATA_DIR, PROJECT_ROOT, PYTHON, WORKER_SCRIPT } from './env';

export interface WorkerResult {
  job_id: string | null;
  state: string;
  units_written: number;
  units_reused: number;
  total_pages: number;
  error_code: string | null;
}

/** 以受控 OCR 替身运行一次真实解析 worker（领取一个任务后退出）。 */
export function runWorker(): WorkerResult {
  const dbPath = path.join(E2E_DATA_DIR, 'data', 'mktkb.sqlite3').replace(/\\/g, '/');
  const storageDir = path.join(E2E_DATA_DIR, 'data', 'storage');
  const result = spawnSync(
    PYTHON,
    [
      '-B',
      WORKER_SCRIPT,
      '--database-url',
      `sqlite:///${dbPath}`,
      '--storage-dir',
      storageDir,
    ],
    {
      cwd: PROJECT_ROOT,
      encoding: 'utf8',
      timeout: 120_000,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    },
  );
  if (result.error) {
    throw new Error(`worker 启动失败：${result.error.message}`);
  }
  const lines = (result.stdout ?? '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  let parsed: WorkerResult | null = null;
  for (const line of lines.reverse()) {
    try {
      const value = JSON.parse(line) as WorkerResult;
      if (typeof value.state === 'string') {
        parsed = value;
        break;
      }
    } catch {
      // 跳过非 JSON 行（如日志）
    }
  }
  if (!parsed) {
    throw new Error(
      `worker 未返回 JSON（退出码 ${result.status}）\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
    );
  }
  if (result.status !== 0 && !['failed', 'blocked'].includes(parsed.state)) {
    throw new Error(`worker 异常退出（${result.status}）：${JSON.stringify(parsed)}\n${result.stderr}`);
  }
  return parsed;
}
