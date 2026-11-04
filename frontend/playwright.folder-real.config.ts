import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

const here = path.dirname(fileURLToPath(import.meta.url));
const evidence = path.resolve(here, '../docs/evidence/LOCAL-R1-20261101/S3-DEV');

/**
 * S3 真实后端浏览器测试：后端/worker/Vite 由 folder-upload-real-run.py 启动，
 * 本配置不声明 webServer，避免误连正式 var/ 数据或 8077 替身服务。
 */
export default defineConfig({
  testDir: path.join(here, 'e2e'),
  testMatch: 'folder-upload-real.spec.ts',
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 180_000,
  expect: { timeout: 20_000 },
  reporter: [['list']],
  outputDir: path.join(evidence, 'real-results'),
  use: {
    baseURL: process.env.S3_REAL_BASE_URL || 'http://127.0.0.1:5874',
    browserName: 'chromium',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    viewport: { width: 1440, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
  },
});
