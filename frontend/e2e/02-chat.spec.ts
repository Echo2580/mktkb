import { test, expect } from '@playwright/test';
import { BACKEND_URL, EMPLOYEE_STATE } from './support/env';

test.describe('员工问答、来源与会话', () => {
  test.use({ storageState: EMPLOYEE_STATE });

  test('示例问题填入、发送、回答与来源详情', async ({ page }) => {
    await page.goto('/chat');
    await expect(page.getByRole('heading', { name: '有什么需要查询的？' })).toBeVisible();

    await page.getByRole('button', { name: '城东店的宣传海报放在哪里？' }).click();
    await expect(page.getByLabel('输入你的问题')).toHaveValue('城东店的宣传海报放在哪里？');
    await page.getByRole('button', { name: '发送', exact: true }).click();

    const answer = page.locator('.message-assistant').last();
    await expect(answer).toContainText('B区1号货架第二层', { timeout: 15_000 });
    await expect(answer.getByText('基于已发布资料')).toBeVisible();
    await expect(answer.locator('.source-bar-name')).toContainText('D01_物品位置表.xlsx');
    await expect(answer.locator('.source-bar-version')).toHaveText('V1');
    await expect(answer.getByText('来源与依据')).toBeVisible();

    await answer.getByRole('button', { name: '查看依据' }).first().click();
    const drawer = page.getByRole('dialog');
    await expect(drawer.getByRole('heading', { name: '来源详情' })).toBeVisible();
    await expect(drawer).toContainText('本次引用的内容');
    await expect(drawer).toContainText('B区1号货架第二层');
    await expect(drawer).toContainText('工作表 物品位置');
    await expect(drawer).toContainText('原始行号 8');
    await expect(drawer.getByRole('link', { name: '在新窗口打开原件' })).toBeVisible();
    const fileHref = await drawer.getByRole('link', { name: '在新窗口打开原件' }).getAttribute('href');
    expect(fileHref).toBeTruthy();
    const fileResponse = await page.request.get(fileHref as string);
    expect(fileResponse.status()).toBe(200);
    expect(fileResponse.headers()['x-content-type-options']).toBe('nosniff');
    await drawer.getByRole('button', { name: '关闭来源详情' }).click();
    await expect(drawer).toHaveCount(0);

    await expect(
      page.getByRole('navigation', { name: '最近对话' }).getByRole('link', { name: '城东店的宣传海报放在哪里？' }),
    ).toBeVisible();
  });

  test('歧义问题给出候选并可选择门店', async ({ page }) => {
    await page.goto('/chat');
    await page.getByLabel('输入你的问题').fill('宣传海报在哪里？');
    await page.getByRole('button', { name: '发送', exact: true }).click();

    const answer = page.locator('.message-assistant').last();
    await expect(answer.getByText('需要确认')).toBeVisible({ timeout: 15_000 });
    await expect(answer).toContainText('请选择要查询的对象');
    await expect(answer.getByRole('button', { name: /选择 城东店/ })).toBeVisible();
    await answer.getByRole('button', { name: /选择 城西店/ }).click();

    const followUp = page.locator('.message-assistant').last();
    await expect(followUp).toContainText('C区2号货架第一层', { timeout: 15_000 });
    await expect(followUp.getByText('基于已发布资料')).toBeVisible();
  });

  test('无答案与部分可答分别显示，且不编造缺失字段', async ({ page }) => {
    await page.goto('/chat');
    await page.getByLabel('输入你的问题').fill('城南店的联系人是谁？');
    await page.getByRole('button', { name: '发送', exact: true }).click();

    let answer = page.locator('.message-assistant').last();
    await expect(answer.getByText('无匹配资料')).toBeVisible({ timeout: 15_000 });
    await expect(answer).toContainText('资料中未找到');
    await expect(answer.getByText('来源与依据')).toHaveCount(0);
    await expect(answer.getByRole('button', { name: '修改原问题后重试' })).toBeVisible();

    await page.getByRole('link', { name: '新建对话' }).click();
    await page.getByLabel('输入你的问题').fill('城东店的地址和营业时间');
    await page.getByRole('button', { name: '发送', exact: true }).click();

    answer = page.locator('.message-assistant').last();
    await expect(answer).toContainText('示例市示例路18号（模拟）', { timeout: 15_000 });
    await expect(answer.locator('.field-row')).toHaveCount(1);
    await expect(answer.locator('.field-row')).toContainText('营业时间');
    await expect(answer.locator('.field-row')).toContainText('未记录');
    await expect(answer.getByText('基于已发布资料')).toBeVisible();
  });

  test('服务故障与资料无答案区分，可重新提问', async ({ page, request }) => {
    const control = await request.post(`${BACKEND_URL}/__t08__/control`, {
      data: { next_model_error: 'unavailable' },
    });
    expect(control.ok()).toBeTruthy();

    await page.goto('/chat');
    await page.getByLabel('输入你的问题').fill('领取活动物料需要哪些步骤？');
    await page.getByRole('button', { name: '发送', exact: true }).click();

    const answer = page.locator('.message-assistant').last();
    await expect(answer.getByText('服务调用失败', { exact: true })).toBeVisible({ timeout: 15_000 });
    await expect(answer).toContainText('不是资料中没有答案');
    await expect(answer).toContainText('MODEL_UNAVAILABLE');
    await expect(answer.getByText('无匹配资料')).toHaveCount(0);
    await expect(answer.getByRole('button', { name: '重新提问' })).toBeVisible();
  });

  test('网络失败准确提示，重试复用同一请求且不重复消息', async ({ page }) => {
    await page.goto('/chat');
    let abortNextPost = true;
    await page.route('**/api/v1/conversations/*/messages', async (route) => {
      if (route.request().method() === 'POST' && abortNextPost) {
        abortNextPost = false;
        await route.abort('failed');
        return;
      }
      await route.continue();
    });

    const question = '物料归还时需要核对什么？';
    await page.getByLabel('输入你的问题').fill(question);
    await page.getByRole('button', { name: '发送', exact: true }).click();

    await expect(page.getByText('提问未完成')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('网络连接失败，请检查网络后重试')).toBeVisible();
    await expect(page.getByRole('button', { name: '重试本次提问' })).toBeVisible();

    await page.getByRole('button', { name: '重试本次提问' }).click();
    const answer = page.locator('.message-assistant').last();
    await expect(answer).toContainText('数量与完好情况', { timeout: 20_000 });
    await expect(answer.getByText('来源与依据')).toBeVisible();
    await expect(page.locator('.message-user-bubble', { hasText: question })).toHaveCount(1);
  });

  test('同一会话追问生成新的回答', async ({ page }) => {
    await page.goto('/chat');
    await page.getByLabel('输入你的问题').fill('城东店的宣传海报在哪里？');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await expect(page.locator('.message-assistant').last()).toContainText('B区1号货架第二层', { timeout: 15_000 });

    await page.getByLabel('输入你的问题').fill('它的负责人是谁？');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await expect(page.locator('.message-assistant')).toHaveCount(2, { timeout: 15_000 });
    await expect(page.locator('.message-assistant').last()).toContainText('负责人');
  });

  test('删除本人会话需确认且从列表移除', async ({ page }) => {
    await page.goto('/chat');
    const question = '滨河店的联系人是谁？';
    await page.getByLabel('输入你的问题').fill(question);
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await expect(page.locator('.message-assistant').last()).toContainText('模拟联系人·周安', { timeout: 15_000 });

    const nav = page.getByRole('navigation', { name: '最近对话' });
    const item = nav.getByRole('link', { name: question });
    await expect(item).toBeVisible();
    await nav.getByRole('button', { name: `删除会话：${question}` }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('删除这条历史会话？');
    await dialog.getByRole('button', { name: '删除会话', exact: true }).click();

    await expect(nav.getByRole('link', { name: question })).toHaveCount(0);
    await expect(page).toHaveURL(/\/chat$/);
  });
});
