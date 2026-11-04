import { test, expect } from '@playwright/test';
import { askViaUi, openSession, shotFor, waitForAnswer } from './support/acceptance';

/**
 * acceptance-04：A-11 候选澄清——点击候选按钮后经 candidate.followup_question
 * 真实再次提问，得到 answer 结果，且最后一条回答不再要求澄清。
 *
 * 覆盖冻结题 C01（宣传海报在哪里？→ 城东店/城西店）与 C02（展架在哪里？）。
 */
const shot = shotFor('04-ambiguity');

test.describe('A-11 候选澄清后可继续完成问答', () => {
  test('C01：宣传海报在哪里？选择「城东店」得到位置 answer', async ({ browser }) => {
    const { context, page } = await openSession(browser, 'employee');
    try {
      await page.goto('/chat');
      await askViaUi(page, '宣传海报在哪里？');
      const clarification = await waitForAnswer(page);
      await expect(clarification.getByText('需要确认')).toBeVisible({ timeout: 30_000 });
      const candidate = clarification.getByRole('button', { name: /^选择 城东店/ });
      await expect(candidate).toBeVisible();
      const candidateLabel = await candidate.getAttribute('aria-label');
      expect(candidateLabel).toContain('城东店');
      await shot(page, '01-c01-clarification', { locator: clarification });

      await candidate.click();
      const followUp = await waitForAnswer(page, 60_000);
      await expect(followUp.getByText('基于已发布资料')).toBeVisible({ timeout: 30_000 });
      await expect(followUp).toContainText('B区1号货架第二层');
      await expect(followUp.getByText('需要确认')).toHaveCount(0);
      await expect(followUp.getByText('来源与依据')).toBeVisible();
      await shot(page, '02-c01-followup-answer', { locator: followUp });
    } finally {
      await context.close();
    }
  });

  test('C02：展架在哪里？选择「城西店」得到位置 answer', async ({ browser }) => {
    const { context, page } = await openSession(browser, 'employee');
    try {
      await page.goto('/chat');
      await askViaUi(page, '展架在哪里？');
      const clarification = await waitForAnswer(page);
      await expect(clarification.getByText('需要确认')).toBeVisible({ timeout: 30_000 });
      await expect(clarification.getByRole('button', { name: /^选择 城东店/ })).toBeVisible();
      const candidate = clarification.getByRole('button', { name: /^选择 城西店/ });
      await expect(candidate).toBeVisible();
      await shot(page, '03-c02-clarification', { locator: clarification });

      await candidate.click();
      const followUp = await waitForAnswer(page, 60_000);
      await expect(followUp.getByText('基于已发布资料')).toBeVisible({ timeout: 30_000 });
      await expect(followUp).toContainText('B区3号货架中层');
      await expect(followUp.getByText('需要确认')).toHaveCount(0);
      await shot(page, '04-c02-followup-answer', { locator: followUp });
    } finally {
      await context.close();
    }
  });
});
