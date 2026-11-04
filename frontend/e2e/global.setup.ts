import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { request } from '@playwright/test';
import type { FullConfig } from '@playwright/test';
import {
  ADMIN_STATE,
  AUTH_DIR,
  BASE_URL,
  E2E_DATA_DIR,
  EMPLOYEE_STATE,
  FRONTEND_ROOT,
  NORMAL,
  PYTHON,
  SEED_FILE,
  VARIANTS,
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
  const uploadsDir = path.join(E2E_DATA_DIR, 'uploads');
  fs.mkdirSync(uploadsDir, { recursive: true });

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
      seed.documents[key] = { id: receipt.document.id, versionId: receipt.version.id, name: receipt.document.name };
    }

    // 同名但字节不同的输入：用于“同名需选择”流程（不直接上传，由测试按需使用）。
    const sameNameCopy = path.join(uploadsDir, 'D01_物品位置表.xlsx');
    fs.copyFileSync(VARIANTS.oldPositions, sameNameCopy);
    seed.uploads.sameNameDifferentBytes = sameNameCopy;

    // 30 行分页检查表（测试专用虚构数据，测试结束后删除）。
    const pagingPath = path.join(uploadsDir, 'T08_分页测试表.xlsx');
    const generated = spawnSync(
      PYTHON,
      ['-B', path.join(FRONTEND_ROOT, 'e2e', 'support', 'make_fixture.py'), pagingPath],
      { encoding: 'utf8' },
    );
    if (generated.status !== 0) {
      throw new Error(`生成分页测试表失败：${generated.stderr || generated.stdout}`);
    }
    seed.uploads.paging = pagingPath;

    // 保存登录态（仅测试账号，凭据固定写在测试入口）。
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
