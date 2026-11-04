import fs from 'node:fs';
import path from 'node:path';
import type { Page } from '@playwright/test';
import { EVIDENCE_DIR } from './env';

/** 保存当前视口截图到 docs/evidence/T08/screenshots/<project>/。 */
export async function capture(page: Page, projectName: string, name: string): Promise<string> {
  const target = path.join(EVIDENCE_DIR, 'screenshots', projectName, `${name}.png`);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  await page.screenshot({ path: target, fullPage: false, animations: 'disabled' });
  return target;
}

/** 检查页面没有横向溢出（容差 1px）。 */
export async function hasNoHorizontalOverflow(page: Page): Promise<{ ok: boolean; scrollWidth: number; innerWidth: number }> {
  const result = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  return { ok: result.scrollWidth <= result.innerWidth + 1, ...result };
}
