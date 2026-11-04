/**
 * T09-D3 B 层浏览器验收 · acceptance-07-update
 *
 * 覆盖冻结用例：
 * - A-17 / U02：先恢复 U02 冻结前提（`/__acceptance/scenario/prepare-u02`，幂等，去掉 06 写入的位置
 *   冲突通知 V01），新建会话问 Q01 得到旧值「B区1号货架第二层」；再发布 P01 新位置
 *   （`/__acceptance/scenario/update-position`）→ **同一旧会话追问**必须返回新值「D区暂存柜」且来源
 *   指向新版本；新会话同样返回新值（U02 assertions：新会话使用新值、原会话追问同样使用新值、来源指向新版本）。
 *   —— 采用状态卫生的原因（Lead 定稿）：B 层串行累积后 V01 通知与 D01 同值会把记录型校验推到
 *   MODEL_OUTPUT_INVALID（已单独作为产品健壮性缺口留证，不由本 spec 触发）。
 * - A-21：回答生成期间资料版本发生变化 → knowledge_changed：卡片标签「资料已更新」、说明本次回答已中止、
 *   提供「重新查询」按钮、且**不得展示来源**。用 Q27/D04 文档型问题（05 已删除 doc-guide，不能用 Q25）
 *   保证走到模型调用；期间用 `scenario/update-phone` 发布 V06 制造 revision 变更。
 *
 * 串行前提：01-06 已跑（06 发布 V01/V02，05 删除 doc-guide）。本 spec 只用控制路由做幂等准备，
 * 不重置 B0、不修产品源码；失败保留证据并报告 Lead。
 */
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import {
  acceptanceState,
  controlGet,
  controlPost,
  loginViaUi,
  askViaUi,
  shotFor,
  waitForGatewayStatus,
  writeJson,
} from './support/acceptance';

const shot = shotFor('acceptance-07-update');

// 冻结题：Q01 位置（prepare-u02 后为旧值，update-position 后为新值）、Q27 文档型（能走到模型调用）
const POSITION_QUESTION = '城东店的宣传海报放在哪里？';
const FOLLOWUP_QUESTION = '那现在呢？宣传海报在哪里？';
const DOCUMENT_QUESTION = '活动申请至少提前多久？';
const OLD_POSITION = 'B区1号货架第二层';
const NEW_POSITION = 'D区暂存柜';
const NEW_PHONE = '010-00000088';

function assistantCards(page: Page) {
  return page.locator('article.message-assistant[aria-label="知识库回答"]');
}

async function cardBadge(card: ReturnType<typeof assistantCards>) {
  return (await card.locator('.assistant-head .badge').innerText()).trim();
}

/** 等待本次提问完成：新增一条回答卡 + 在途指示消失，避免把上一条回答误当本次结果。 */
async function waitForSettledAnswer(page: Page, expectedCards: number) {
  await expect(assistantCards(page)).toHaveCount(expectedCards, { timeout: 120_000 });
  await expect(page.locator('.typing')).toHaveCount(0, { timeout: 120_000 });
  const card = assistantCards(page).last();
  await expect(card).toBeVisible({ timeout: 15_000 });
  return card;
}

/** 真实 UI 提问并等待结果落定（askViaUi 负责填表+点击发送）。 */
async function askAndRead(page: Page, question: string) {
  const before = await assistantCards(page).count();
  await askViaUi(page, question);
  return waitForSettledAnswer(page, before + 1);
}

test.describe('acceptance-07-update · A-17 旧会话追问新值 / A-21 knowledge_changed', () => {
  test('A-17 恢复 U02 前提后，旧会话追问返回新值且来源指向新版本', async ({ page, request }) => {
    test.setTimeout(300_000);

    await page.goto('/login');
    await loginViaUi(page, 'admin');

    // 0) 状态卫生：恢复 U02 冻结前提（去掉 06 发布的位置冲突通知 V01，回到“B0 + 无 V01”）
    const prepared = await controlPost(request, '/__acceptance/scenario/prepare-u02');
    expect(prepared.applied, 'prepare-u02 必须幂等成功').toBe(true);
    expect(typeof prepared.revision).toBe('number');
    const stateAfterPrepare = await acceptanceState(request);
    expect(stateAfterPrepare.scenarios.prepare_u02?.applied ?? true).toBe(true);

    // 1) 更新前：新建会话问 Q01，必须得到旧值答案 —— 这个会话就是后面的“旧会话”
    await page.goto('/chat');
    await expect(page.locator('#welcome-title')).toBeVisible({ timeout: 30_000 });
    const preCard = await askAndRead(page, POSITION_QUESTION);
    await expect(preCard.locator('.assistant-head .badge')).toHaveText('基于已发布资料');
    await expect(preCard).toContainText(OLD_POSITION);
    const preText = await preCard.innerText();
    const conversationUrl = page.url();
    expect(conversationUrl).toMatch(/\/chat\/[0-9a-f-]{8,}/i);
    await shot(page, 'a-17-01-before-update-old-value');

    // 2) 控制路由：把 V04 作为 doc-positions 槽新版本上传→处理→发布（幂等）
    const update = await controlPost(request, '/__acceptance/scenario/update-position');
    expect(update.applied).toBe(true);
    expect(update.slot).toBe('doc-positions');
    expect(update.new_value).toBe(NEW_POSITION);
    expect(typeof update.version_id).toBe('string');
    expect(update.version_id.length).toBeGreaterThan(0);
    expect(update.version_number).toBeGreaterThanOrEqual(2);
    const updateVersionLabel = `V${update.version_number}`;
    const stateAfterUpdate = await acceptanceState(request);
    expect(stateAfterUpdate.scenarios.update_position.applied).toBe(true);

    // 3) 回到原会话（刷新证明是服务端旧会话），在同一会话里追问新值
    await page.goto(conversationUrl);
    await expect(assistantCards(page)).toHaveCount(1, { timeout: 30_000 });
    let followCard = await askAndRead(page, FOLLOWUP_QUESTION);
    let followBadge = await cardBadge(followCard);
    // 上下文式追问若被解析为澄清（缺门店），按 Lead 允许的兜底：同一会话再问一次 Q01
    const followupPhraseResolved = followBadge === '基于已发布资料';
    if (!followupPhraseResolved) {
      await shot(page, 'a-17-02a-followup-phrase-needs-explicit-question');
      followCard = await askAndRead(page, POSITION_QUESTION);
      followBadge = await cardBadge(followCard);
    }
    await expect(followCard.locator('.assistant-head .badge')).toHaveText('基于已发布资料');
    const followText = await followCard.innerText();
    expect(followText, '旧会话追问必须返回新值').toContain(NEW_POSITION);
    expect(followText, '旧会话追问不得再出现旧值').not.toContain(OLD_POSITION);
    await expect(followCard.getByText('来源与依据')).toBeVisible();
    expect(followText, '来源必须指向《物品位置表》').toContain('物品位置表');
    const versionTexts = (await followCard.locator('.source-bar-version').allInnerTexts()).map((text) => text.trim());
    expect(versionTexts, `来源版本必须是最新发布的 ${updateVersionLabel}`).toContain(updateVersionLabel);
    await expect(followCard.locator('.source-bar .badge').first()).toHaveText('有效');
    await shot(page, 'a-17-03-old-session-followup-new-value');

    // 4) U02 另一断言：新会话同样使用新值
    await page.goto('/chat');
    await expect(page.locator('#welcome-title')).toBeVisible();
    const newCard = await askAndRead(page, POSITION_QUESTION);
    const newBadge = await cardBadge(newCard);
    const newText = await newCard.innerText();
    expect(newBadge).toBe('基于已发布资料');
    expect(newText).toContain(NEW_POSITION);
    expect(newText).not.toContain(OLD_POSITION);
    await shot(page, 'a-17-04-new-session-new-value');

    writeJson('acceptance-07-update/a17-update-and-followup', {
      case: ['A-17', 'U02'],
      prepare: {
        applied: prepared.applied,
        revision: prepared.revision ?? null,
        response: prepared,
      },
      update: {
        applied: update.applied,
        slot: update.slot,
        document_id: update.document_id,
        version_id: update.version_id,
        version_number: update.version_number,
        previous_active_version_id: update.previous_active_version_id ?? null,
        new_value: update.new_value,
        revision: update.revision,
      },
      old_conversation: {
        url: conversationUrl,
        first_question: POSITION_QUESTION,
        first_answer: preText,
        first_answer_contains_old_value: preText.includes(OLD_POSITION),
        followup_question: FOLLOWUP_QUESTION,
        followup_phrase_resolved_as_answer: followupPhraseResolved,
        followup_badge: followBadge,
        followup_contains_new_value: followText.includes(NEW_POSITION),
        followup_contains_old_value: followText.includes(OLD_POSITION),
        source_versions: versionTexts,
        expected_source_version: updateVersionLabel,
      },
      new_conversation: {
        question: POSITION_QUESTION,
        badge: newBadge,
        contains_new_value: newText.includes(NEW_POSITION),
        contains_old_value: newText.includes(OLD_POSITION),
      },
    });
  });

  test('A-21 回答生成期间资料更新 → knowledge_changed（中止回答且不带来源）', async ({ page, request }) => {
    test.setTimeout(300_000);

    await page.goto('/login');
    await loginViaUi(page, 'admin');

    // 前序 spec 应已消费完故障注入；此处先释放可能的阻塞残留并确认网关干净
    await controlPost(request, '/__acceptance/gateway/release');
    const clean = await controlGet(request, '/__acceptance/gateway/status');
    expect(clean.block_remaining, '网关阻塞计数应为 0（前序 spec 未清理会污染本用例）').toBe(0);
    expect(clean.fail_remaining, '网关失败注入应为 0（前序 spec 未清理会污染本用例）').toBe(0);

    // 布好阻塞：下一次模型调用进入等待，为“生成期间发布新版本”创造时间窗
    const armed = await controlPost(request, '/__acceptance/gateway/block-next', { count: 1 });
    expect(armed.armed).toBe(1);

    // 新建会话，问文档型问题（Q27/D04，必然走到模型调用；doc-guide 已被 05 删除，不能用 Q25）
    await page.goto('/chat');
    await expect(page.locator('#welcome-title')).toBeVisible({ timeout: 30_000 });
    const before = await assistantCards(page).count();

    // 真实 UI 点击发送；不等待回答，先取证“在途”（此时不能用 askViaUi，它可能阻塞到回答完成）
    await page.locator('#question-input').fill(DOCUMENT_QUESTION);
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await expect(page.locator('.typing')).toBeVisible({ timeout: 30_000 });

    // 后端模型调用必须已经进入阻塞（entered=true），证明更新发生在生成期间
    const entered = await waitForGatewayStatus(request, (state) => state.entered === true, 30_000);
    expect(entered.entered).toBe(true);
    await shot(page, 'a-21-01-question-in-flight');

    // 生成期间制造知识变更：把 V06 发布为 doc-stores 槽新版本（新电话）
    const phoneUpdate = await controlPost(request, '/__acceptance/scenario/update-phone');
    expect(phoneUpdate.applied).toBe(true);
    expect(phoneUpdate.new_value).toBe(NEW_PHONE);

    // 释放模型调用，让早先的 ask 走到提交阶段；提交时 revision 已变化 → knowledge_changed
    const release = await controlPost(request, '/__acceptance/gateway/release');
    expect(release.released).toBe(true);

    const card = await waitForSettledAnswer(page, before + 1);
    await expect(card.locator('.assistant-head .badge')).toHaveText('资料已更新');
    await expect(card).toContainText('资料已更新，本次回答已中止，请重新查询。');
    await expect(card).toContainText('回答生成期间资料版本发生变化');
    await expect(card.getByRole('button', { name: '重新查询' })).toBeVisible();

    // knowledge_changed 不得带来源（来源区块、来源条、查看依据按钮都不应存在）
    await expect(card.getByText('来源与依据')).toHaveCount(0);
    await expect(card.locator('.source-bar')).toHaveCount(0);
    await expect(card.getByText('查看依据')).toHaveCount(0);
    const cardText = await card.innerText();
    expect(cardText).not.toContain(NEW_PHONE); // 中止的回答不得泄露生成期间的新值
    await shot(page, 'a-21-02-knowledge-changed-no-sources');

    const after = await waitForGatewayStatus(
      request,
      (state) => state.entered === false && state.block_remaining === 0,
      15_000,
    );
    expect(after.block_remaining).toBe(0);
    const finalState = await acceptanceState(request);
    expect(finalState.scenarios.update_phone.applied).toBe(true);

    writeJson('acceptance-07-update/a21-knowledge-changed', {
      case: 'A-21',
      question: DOCUMENT_QUESTION,
      gateway: { entered, release, after },
      phone_update: {
        applied: phoneUpdate.applied,
        new_value: phoneUpdate.new_value,
        version_id: phoneUpdate.version_id,
        revision: phoneUpdate.revision,
      },
      message: {
        badge: await cardBadge(card),
        text: cardText,
        has_sources: (await card.locator('.source-bar').count()) > 0,
        has_source_section: (await card.getByText('来源与依据').count()) > 0,
        has_retry_button: (await card.getByRole('button', { name: '重新查询' }).count()) > 0,
      },
      outbound_external: finalState.outbound?.external ?? null,
    });
  });
});
