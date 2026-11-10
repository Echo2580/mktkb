import { test, expect } from '@playwright/test';
import {
  askViaUi,
  controlPost,
  openSession,
  shotFor,
  waitForAnswer,
  writeJson,
} from './support/acceptance';

/**
 * acceptance-02：六类结果中的四类——answer / clarification / not_found / service_error。
 * 串行执行、状态累积：不假设干净 B0，所需故障注入用控制路由幂等准备。
 */
const shot = shotFor('02-kinds');

test.describe('结果类型与稳定文案', () => {
  test('answer（Q01）：回答值、结果标记与来源依据', async ({ browser }) => {
    const { context, page } = await openSession(browser, 'employee');
    try {
      await page.goto('/chat');
      await askViaUi(page, '城东店的宣传海报在哪里？');
      const answer = await waitForAnswer(page);
      await expect(answer.getByText('基于已发布资料')).toBeVisible({ timeout: 30_000 });
      await expect(answer).toContainText('B区1号货架第二层');
      await expect(answer.getByText('来源与依据')).toBeVisible();
      // B0 的 doc-positions 槽先由 V03 建文档、再以 D01 作为业务 V2 发布，
      // 因此来源显示的是槽文档名 V03_物品位置表_历史V1.xlsx · V2（历史业务 V1 已被替换）。
      const d01Bar = answer.locator('.source-bar').filter({ hasText: 'V03_物品位置表_历史V1.xlsx' }).first();
      await expect(d01Bar).toBeVisible();
      await expect(d01Bar.locator('.source-bar-version')).toHaveText('V2');
      await expect(d01Bar).not.toContainText('· V1');
      await shot(page, '01-answer-q01');
    } finally {
      await context.close();
    }
  });

  test('clarification（C01）：需要确认 + 城东店/城西店候选按钮', async ({ browser }) => {
    const { context, page } = await openSession(browser, 'employee');
    try {
      await page.goto('/chat');
      await askViaUi(page, '宣传海报在哪里？');
      const answer = await waitForAnswer(page);
      await expect(answer.getByText('需要确认')).toBeVisible({ timeout: 30_000 });
      await expect(answer).toContainText('存在多个可能对象，请选择要查询的对象。');
      await expect(answer.getByRole('button', { name: /^选择 城东店/ })).toBeVisible();
      await expect(answer.getByRole('button', { name: /^选择 城西店/ })).toBeVisible();
      await shot(page, '02-clarification-c01', { locator: answer });
    } finally {
      await context.close();
    }
  });

  test('clarification（C02）：无候选时徽标诚实，历史消息不武断', async ({ browser }) => {
    const { context, page } = await openSession(browser, 'employee');
    try {
      await page.goto('/chat');
      await askViaUi(page, '城东店的宣传海报在哪里？');
      await waitForAnswer(page);
      const answer = await askViaUi(page, '城西区的宣传海报在哪？');
      // 未知区域澄清没有候选：徽标不得再显示“需要确认”，也不得暗示“基于已发布资料”。
      await expect(answer.locator('.assistant-head .badge')).toHaveText('需补充条件', { timeout: 30_000 });
      await expect(answer).not.toContainText('需要确认');
      await expect(answer).toContainText('资料中没有收录');
      await expect(answer).not.toContainText('该历史消息未保存');
      await expect(answer).toContainText('没有提供可选项');
      await shot(page, '02b-clarification-no-candidate', { locator: answer });

      // 历史消息没有持久化候选：文案仍必须中性、可自救，不得断言“未保存/资料缺失”。
      await page.reload();
      const history = page.locator('.message-assistant').last();
      await expect(history.locator('.assistant-head .badge')).toHaveText('需补充条件', { timeout: 30_000 });
      await expect(history).not.toContainText('该历史消息未保存');
      await expect(history).toContainText('没有提供可选项');
    } finally {
      await context.close();
    }
  });

  test('not_found（N01）：无匹配资料且无来源依据', async ({ browser }) => {
    const { context, page } = await openSession(browser, 'employee');
    try {
      await page.goto('/chat');
      await askViaUi(page, '城南店联系人是谁？');
      const answer = await waitForAnswer(page);
      await expect(answer.getByText('无匹配资料')).toBeVisible({ timeout: 30_000 });
      await expect(answer).toContainText('资料中未找到');
      await expect(answer.getByText('来源与依据')).toHaveCount(0);
      await shot(page, '03-not-found-n01', { locator: answer });
    } finally {
      await context.close();
    }
  });

  test('service_error：fail-next 注入 → 服务调用失败 + 错误码 + 重新提问可恢复', async ({ browser, request }) => {
    const armed = await controlPost(request, '/__acceptance/gateway/fail-next', {
      count: 1,
      code: 'MODEL_UNAVAILABLE',
    });
    expect(armed.armed).toBe(1);
    writeJson('service-error-fail-next', armed);

    const { context, page } = await openSession(browser, 'employee');
    try {
      await page.goto('/chat');
      await askViaUi(page, '领取活动物料需要哪些步骤？');
      const failed = await waitForAnswer(page);
      // 回答正文同样含「服务调用失败」字样，用结果标记 badge 精确定位避免 strict mode 冲突。
      await expect(failed.locator('.assistant-head .badge')).toHaveText('服务调用失败');
      await expect(failed).toContainText('这是服务调用失败，不是资料中没有答案');
      await expect(failed).toContainText('MODEL_UNAVAILABLE');
      await expect(failed.getByText('无匹配资料')).toHaveCount(0);
      await expect(failed.getByRole('button', { name: '重新提问' })).toBeVisible();
      await shot(page, '04-service-error', { locator: failed });

      // 重新提问走新请求编号，故障只注入一次，应恢复为 answer；
      // 措辞在不同来源里可能是「填写登记表」或「填写领用登记表」，用正则兼容。
      await failed.getByRole('button', { name: '重新提问' }).click();
      const recovered = await waitForAnswer(page);
      await expect(recovered.getByText('基于已发布资料')).toBeVisible({ timeout: 30_000 });
      await expect(recovered).toContainText(/填写.{0,4}登记表/);
      await expect(recovered.getByText('来源与依据')).toBeVisible();
      await shot(page, '05-service-error-recovered', { locator: recovered });
    } finally {
      await context.close();
    }
  });
});
