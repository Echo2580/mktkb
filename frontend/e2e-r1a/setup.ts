import fs from 'node:fs';
import path from 'node:path';
import { request } from '@playwright/test';
import type { FullConfig } from '@playwright/test';
import {
  ADMIN_STATE,
  AUTH_DIR,
  BASE_URL,
  E2E_DATA_DIR,
  EMPLOYEE_STATE,
  NORMAL,
  SEED_FILE,
  type SeedData,
} from './support/env';
import { closeSession, openSession, publishReceipt, uploadFile } from './support/api';
import { runWorker } from './support/worker';

async function waitForHealth(): Promise<void> {
  const ctx = await request.newContext({ baseURL: BASE_URL });
  try {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      try {
        const response = await ctx.get('/api/v1/healthz');
        if (response.status() === 200) return;
      } catch {
        // 后端尚未就绪，继续等待
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    throw new Error('后端健康检查超时');
  } finally {
    await ctx.dispose();
  }
}

export default async function globalSetup(_config: FullConfig): Promise<void> {
  await waitForHealth();
  fs.mkdirSync(AUTH_DIR, { recursive: true });
  fs.mkdirSync(path.join(E2E_DATA_DIR, 'uploads'), { recursive: true });

  const admin = await openSession('admin');
  const seed: SeedData = { documents: {}, uploads: {} };
  try {
    const items: Array<[string, string]> = [
      ['D01', NORMAL.positions],
      ['D02', NORMAL.contacts],
      ['D03', NORMAL.guide],
      ['D05', NORMAL.materialsPdf],
      ['D06', NORMAL.storeGuidePdf],
    ];
    for (const [key, filePath] of items) {
      const receipt = await uploadFile(admin, filePath);
      const result = runWorker();
      if (result.state !== 'succeeded') {
        throw new Error(`初始化 ${key} 处理失败：${JSON.stringify(result)}`);
      }
      await publishReceipt(admin, receipt);
      seed.documents[key] = {
        id: receipt.document.id,
        versionId: receipt.version.id,
        name: receipt.document.name,
      };
    }
    await admin.ctx.storageState({ path: ADMIN_STATE });
    await closeSession(admin);

    const employee = await openSession('employee');
    try {
      await employee.ctx.storageState({ path: EMPLOYEE_STATE });
    } finally {
      await closeSession(employee);
    }

    fs.writeFileSync(SEED_FILE, JSON.stringify(seed, null, 2), 'utf8');
  } catch (error) {
    await closeSession(admin).catch(() => undefined);
    throw error;
  }
}
