import { test, expect } from '@playwright/test';
import {
  askViaUi,
  controlPost,
  openSession,
  shotFor,
  waitForAnswer,
  waitForDocumentReview,
  writeJson,
} from './support/acceptance';

/**
 * acceptance-03：A-03 五类文件（Word / Excel / 文字 PDF / 扫描 PDF / 图片）
 * 走真实管理员 UI：上传 → 待确认 → 查看/检查（处理报告字段）→ 确认并发布 →
 * 新会话提问该材料问题 → 回答含 expected_value。
 *
 * 5 份文件由 `/__acceptance/materials/generate` 在本轮 data 目录旁生成，
 * 不重复上传 fixtures 里的 B0 文件（字节重复会被产品拒绝）。
 */
const shot = shotFor('03-upload');

interface MaterialInfo {
  path: string;
  filename: string;
  kind: string;
  expected_text: string;
  question: string;
  expected_value: string;
  ocr: boolean;
}

const MATERIAL_KEYS = ['word', 'excel', 'pdf_text', 'pdf_scan', 'image'] as const;

const REPORT_FIELDS: Record<string, string[]> = {
  docx: ['处理报告', '处理完整', '段落'],
  xlsx: ['处理报告', '处理完整', '有效数据行'],
  'pdf-text': ['处理报告', '处理完整', '总页数'],
  'pdf-scan': ['处理报告', '处理完整', '总页数'],
  png: ['处理报告', '处理完整', '总页数'],
};

const CONTENT_CHECKS: Record<string, string[]> = {
  docx: ['入职第一天请在前台领取工牌'],
  xlsx: ['差旅报销-住宿费'],
  'pdf-text': ['预约会议室需提前一天'],
  'pdf-scan': ['员工培训报名通知'],
  png: ['办公设备报修流程'],
};

async function uploadCheckAndPublish(
  page: import('@playwright/test').Page,
  key: string,
  material: MaterialInfo,
): Promise<void> {
  await page.goto('/documents');
  await expect(page.getByRole('heading', { name: '资料管理', exact: true, level: 2 })).toBeVisible();

  // 1. 上传
  await page.getByRole('button', { name: '上传资料', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: '上传资料' })).toBeVisible();
  await dialog.getByLabel('选择要上传的文件').setInputFiles(material.path);
  await expect(dialog).toContainText(material.filename);
  await shot(page, `${key}-01-file-chosen`);
  await dialog.getByRole('button', { name: '上传', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText(`已上传「${material.filename}」`)).toBeVisible();

  // 2. 等待后台 worker 处理完成 → 待确认
  const row = page.locator('tbody tr').filter({ hasText: material.filename });
  await expect(row).toHaveCount(1);
  await waitForDocumentReview(page, material.filename);
  await shot(page, `${key}-02-review-required`);

  // 3. 查看/检查：处理报告字段 + 提取内容
  await row.getByRole('button', { name: '查看/检查' }).click();
  const drawer = page.getByRole('dialog');
  await expect(drawer.getByRole('heading', { name: '检查待确认版本' })).toBeVisible();
  for (const field of REPORT_FIELDS[material.kind] ?? ['处理报告', '处理完整']) {
    await expect(drawer).toContainText(field, { timeout: 30_000 });
  }
  await expect(drawer.locator('.preview-unit').first()).toBeVisible({ timeout: 30_000 });
  for (const expectedText of CONTENT_CHECKS[material.kind] ?? []) {
    await expect(drawer).toContainText(expectedText, { timeout: 30_000 });
  }
  await shot(page, `${key}-03-inspection`);

  // 4. 确认并发布
  await drawer.getByRole('button', { name: '确认并发布' }).click();
  const confirm = page.getByRole('dialog', { name: /确认发布 V1/ });
  await expect(confirm).toBeVisible();
  await shot(page, `${key}-04-confirm-publish`);
  await confirm.getByRole('button', { name: '确认发布', exact: true }).click();
  await expect(page.getByText('V1 已发布并生效')).toBeVisible({ timeout: 30_000 });
  await shot(page, `${key}-05-published`);
  await drawer.getByRole('button', { name: '关闭检查抽屉' }).click();
  await expect(drawer).toHaveCount(0);
  await expect(row).toContainText('当前版本已生效');

  // 5. 新会话提问该材料问题
  await page.getByRole('link', { name: '新建对话' }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await askViaUi(page, material.question);
  const answer = await waitForAnswer(page);
  await expect(answer.getByText('基于已发布资料')).toBeVisible({ timeout: 30_000 });
  await expect(answer).toContainText(material.expected_value);
  await expect(answer.getByText('来源与依据')).toBeVisible();
  await shot(page, `${key}-06-answer`, { locator: answer });
}

for (const key of MATERIAL_KEYS) {
  test(`A-03 ${key}：上传→检查→发布→问答`, async ({ browser, request }) => {
    const payload = await controlPost(request, '/__acceptance/materials/generate');
    const materials = payload.materials as Record<string, MaterialInfo>;
    const material = materials[key];
    expect(material, `材料 ${key} 未由控制路由生成`).toBeTruthy();
    expect(material.path).toBeTruthy();
    writeJson(`a03-material-${key}`, {
      key,
      filename: material.filename,
      kind: material.kind,
      question: material.question,
      expected_value: material.expected_value,
      ocr: material.ocr,
      path: material.path,
    });

    const { context, page } = await openSession(browser, 'admin');
    try {
      await uploadCheckAndPublish(page, key, material);
    } finally {
      await context.close();
    }
  });
}
