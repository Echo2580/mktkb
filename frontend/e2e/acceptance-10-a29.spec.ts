/**
 * T09-D3 B 层浏览器验收 · acceptance-10-a29
 *
 * 覆盖冻结用例 A-29：前端不得持有/展示模型或 OCR 密钥，不得直连外部模型/OCR 服务。
 * 做法（全部真实运行，不 mock 网络）：
 *   1. 从首个导航前开始用 trackRequests(page) 收集浏览器全部请求，断言除 127.0.0.1/localhost 外
 *      没有任何外部 host（含显式黑名单 api.deepseek.com / ocr.tencentcloudapi.com）；
 *   2. 扫描页面 DOM 与 localStorage/sessionStorage 中的密钥模式；
 *   3. 扫描已加载 JS bundle 文本中的密钥模式与模型/OCR endpoint 字面量；
 *   4. 用 /__acceptance/state 断言后端进程级闸门 outbound.external 为空数组。
 * 命中的文本一律脱敏后落盘，证据不复制密钥。
 *
 * 串行前提：07/08/09 已完成；本 spec 只读，不重置数据。问答用 Q03（不受位置/电话更新影响）。
 */
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import {
  acceptanceState,
  askViaUi,
  externalRequests,
  loginViaUi,
  scanLoadedScriptsForSecrets,
  scanPageForSecrets,
  shotFor,
  trackRequests,
  writeJson,
} from './support/acceptance';

const shot = shotFor('acceptance-10-a29');

const QUESTION = '城东店的展架在哪里？';
const EXPECTED_ANSWER = 'A区2号货架底层';

const SECRET_PATTERNS: Array<{ name: string; pattern: RegExp }> = [
  { name: 'env_model_key_name', pattern: /MKTK[A-Z_]*MODEL_API_KEY/g },
  { name: 'env_model_base_url_name', pattern: /MKTK[A-Z_]*MODEL_BASE_URL/g },
  { name: 'env_ocr_secret_name', pattern: /MKTK[A-Z_]*(?:SECRET_KEY|SECRET_ID)/g },
  { name: 'env_generic_key_name', pattern: /MKTK[A-Z_]*(?:API_KEY|ACCESS_KEY|TOKEN)/g },
  { name: 'sk_token_literal', pattern: /(?:^|[^A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}/g },
  { name: 'deepseek_host_literal', pattern: /api\.deepseek\.com/g },
  { name: 'tencent_ocr_host_literal', pattern: /ocr\.tencentcloudapi\.com/g },
];

/** 只记录“哪个模式命中”，不把命中文本写进证据（避免证据复制密钥）。 */
function scanText(text: string): string[] {
  const hits: string[] = [];
  for (const { name, pattern } of SECRET_PATTERNS) {
    const matcher = new RegExp(pattern.source, pattern.flags);
    if (matcher.test(text)) hits.push(name);
  }
  return hits;
}

function assistantCards(page: Page) {
  return page.locator('article.message-assistant[aria-label="知识库回答"]');
}

async function waitForSettledAnswer(page: Page, expectedCards: number) {
  await expect(assistantCards(page)).toHaveCount(expectedCards, { timeout: 120_000 });
  await expect(page.locator('.typing')).toHaveCount(0, { timeout: 120_000 });
  const card = assistantCards(page).last();
  await expect(card).toBeVisible({ timeout: 15_000 });
  return card;
}

async function askAndRead(page: Page, question: string) {
  const before = await assistantCards(page).count();
  await askViaUi(page, question);
  return waitForSettledAnswer(page, before + 1);
}

/**
 * 逐条取已加载脚本文本做模式扫描（同源、限流、限量；只记模式名，不记文本）。
 * 说明：`document.scripts` 在 Vite dev 下只有 /src/main.tsx 一个入口，真正加载的业务模块
 * 通过 performance resource entries 暴露，因此两者合并覆盖（A-29 要求检查“已加载的 JS bundle 文本”）。
 */
async function scanLoadedScriptBodies(page: Page, scriptUrls: string[]) {
  const resourceUrls = await page.evaluate(() =>
    performance
      .getEntriesByType('resource')
      .map((entry) => entry.name)
      .filter((name) => /\.(?:js|mjs|cjs|ts|tsx)(?:\?|$)/.test(name)),
  );
  const candidates = [...new Set([...scriptUrls, ...resourceUrls])].filter((url) => {
    try {
      const parsed = new URL(url);
      return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && parsed.hostname === '127.0.0.1';
    } catch {
      return false;
    }
  });

  const hits: Array<{ script: string; patterns: string[] }> = [];
  let scanned = 0;
  let totalBytes = 0;
  for (const url of candidates.slice(0, 200)) {
    if (totalBytes > 16 * 1024 * 1024) break;
    let response;
    try {
      response = await page.request.get(url, { timeout: 15_000 });
    } catch {
      continue;
    }
    if (!response.ok()) continue;
    const body = await response.text();
    scanned += 1;
    totalBytes += body.length;
    const patterns = scanText(body);
    if (patterns.length > 0) hits.push({ script: url, patterns });
  }
  return { candidates: candidates.length, scanned, total_bytes: totalBytes, hits };
}

test.describe('acceptance-10-a29 · 无外部出站 / 无密钥泄漏', () => {
  test('A-29 浏览器网络、DOM、存储、JS bundle 与后端 outbound 均无模型 Key 及外部直连', async ({
    page,
    request,
  }) => {
    test.setTimeout(240_000);

    // 必须是首个导航之前就开始收集，保证覆盖登录页在内的全部请求
    const requestUrls = trackRequests(page);

    await page.goto('/login');
    await expect(page.locator('.login-form')).toBeVisible({ timeout: 30_000 });
    await shot(page, 'a-29-01-login');

    await loginViaUi(page, 'admin');
    await expect(page.locator('.topbar-title')).toHaveText('AI 助手', { timeout: 30_000 });

    // 走一条真实问答链路（会触发后端模型替身；不得有任何外部出站）
    const card = await askAndRead(page, QUESTION);
    await expect(card.locator('.assistant-head .badge')).toHaveText('基于已发布资料');
    await expect(card).toContainText(EXPECTED_ANSWER);
    await shot(page, 'a-29-02-answer');

    // 再走资料管理页（最大的页面，覆盖文档/上传相关模块加载）
    await page.goto('/documents');
    await expect(page.locator('.page-title')).toHaveText('资料管理', { timeout: 30_000 });
    await expect(page.locator('.doc-desktop table.data-table tbody tr').first()).toBeVisible({ timeout: 30_000 });
    await shot(page, 'a-29-03-documents');

    // 1) 网络：除回环地址外不得有任何外部 host
    expect(requestUrls.length, '必须采集到浏览器请求').toBeGreaterThan(0);
    const external = externalRequests(requestUrls);
    expect(external, '浏览器出现外部请求（A-29 违规）').toEqual([]);
    const forbiddenHosts = ['api.deepseek.com', 'ocr.tencentcloudapi.com', 'deepseek.com', 'tencentcloudapi.com'];
    for (const host of forbiddenHosts) {
      expect(
        requestUrls.filter((url) => url.includes(host)),
        `浏览器直连了禁止的外部 host：${host}`,
      ).toEqual([]);
    }
    const hostSummary = [...new Set(
      requestUrls.map((url) => {
        try {
          return new URL(url).host;
        } catch {
          return 'invalid-url';
        }
      }),
    )].sort();

    // 2) DOM + localStorage/sessionStorage 中的密钥模式
    const pageSecrets = await scanPageForSecrets(page);
    expect(pageSecrets.domHits, 'DOM 中出现密钥模式').toEqual([]);
    expect(pageSecrets.storageHits, 'localStorage/sessionStorage 中出现密钥模式').toEqual([]);

    // 3) 已加载 JS bundle 文本中的密钥模式 / 外部 host 字面量
    const scriptSecrets = await scanLoadedScriptsForSecrets(page);
    expect(scriptSecrets.hits, '已加载脚本中出现密钥模式').toEqual([]);
    expect(scriptSecrets.scriptUrls.length, '必须有已加载脚本可供检查').toBeGreaterThan(0);
    const bodyScan = await scanLoadedScriptBodies(page, scriptSecrets.scriptUrls);
    expect(bodyScan.hits, 'JS bundle 文本命中密钥/外部 host 模式').toEqual([]);

    // 4) 后端进程级闸门：外部连接尝试必须为空
    const state = await acceptanceState(request);
    expect(Array.isArray(state.outbound?.external), '后端 outbound.external 必须是数组').toBe(true);
    expect(state.outbound.external, '后端发生外部出站（A-29 违规）').toEqual([]);

    const payload = {
      case: 'A-29',
      browser_requests: {
        total: requestUrls.length,
        hosts: hostSummary,
        external: external,
        forbidden_host_hits: forbiddenHosts.filter((host) => requestUrls.some((url) => url.includes(host))),
      },
      secrets: {
        dom_hits: pageSecrets.domHits,
        storage_hits: pageSecrets.storageHits,
        loaded_script_hits: scriptSecrets.hits,
        loaded_scripts_checked: scriptSecrets.scriptUrls.length,
        loaded_script_bodies: {
          candidates: bodyScan.candidates,
          scanned: bodyScan.scanned,
          total_bytes: bodyScan.total_bytes,
          hits: bodyScan.hits,
        },
        patterns_checked: SECRET_PATTERNS.map((entry) => entry.name),
      },
      backend_outbound: {
        external: state.outbound.external,
        local_count: state.outbound.local_count ?? null,
      },
      backend_counters: {
        model_calls: state.model_calls ?? null,
        ocr_calls: state.ocr_calls ?? null,
      },
    };

    writeJson('acceptance-10-a29/a29-network-and-secret-audit', payload);

    // 断言结论也要能写进 JSON 的“通过”标记，便于报告引用
    expect(payload.browser_requests.external).toEqual([]);
    expect(payload.browser_requests.forbidden_host_hits).toEqual([]);
    expect(payload.secrets.loaded_script_bodies.hits).toEqual([]);
    expect(payload.backend_outbound.external).toEqual([]);
  });
});
