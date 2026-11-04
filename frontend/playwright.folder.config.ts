import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

const here = path.dirname(fileURLToPath(import.meta.url));
const evidence = path.resolve(here, '../docs/evidence/LOCAL-R1-20261101/S3-DEV');

export default defineConfig({
  testDir: path.join(here, 'e2e'),
  testMatch: 'folder-upload.spec.ts',
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 45_000,
  expect: { timeout: 5000 },
  reporter: [['list']],
  outputDir: path.join(evidence, 'browser-results'),
  use: {
    baseURL: 'http://127.0.0.1:5873',
    browserName: 'chromium',
    locale: 'zh-CN',
    viewport: { width: 1366, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    actionTimeout: 5000,
  },
  webServer: {
    command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5873 --strictPort',
    url: 'http://127.0.0.1:5873',
    cwd: here,
    reuseExistingServer: false,
    timeout: 60_000,
    env: { T08_BACKEND_ORIGIN: 'http://127.0.0.1:1' },
  },
});
