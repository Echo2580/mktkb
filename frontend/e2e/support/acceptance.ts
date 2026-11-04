/**
 * T09-D3 B 层浏览器验收共享 support（契约 §3.1）。
 *
 * 只由 frontend-acceptance 维护；spec 01-10 统一从这里 import。所有证据写入
 * `D3_EVIDENCE_ROOT`（默认按本文件位置推导到仓库 `docs/evidence/T09/D3`），
 * 路径/端口全部来自运行器传入的 D3_* env，禁止硬编码盘符。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  expect,
  type APIRequestContext,
  type APIResponse,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from '@playwright/test';

const SUPPORT_DIR = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(SUPPORT_DIR, '../..');
const PROJECT_ROOT = path.resolve(FRONTEND_ROOT, '..');

/** 证据根：运行时由 D3_EVIDENCE_ROOT 指定；缺省按文件位置推导。 */
export const D3_ROOT = process.env.D3_EVIDENCE_ROOT
  ? path.resolve(process.env.D3_EVIDENCE_ROOT)
  : path.join(PROJECT_ROOT, 'docs', 'evidence', 'T09', 'D3');
/** 本轮唯一 label（运行器传入 D3_LABEL）。 */
export const LABEL = process.env.D3_LABEL || 'unlabeled';
/** 浏览器访问的 Vite 源（同源 /api 代理到后端）。 */
export const BASE_URL = process.env.D3_BASE_URL || 'http://127.0.0.1:5199';
/** 验收后端直连地址（控制路由 /__acceptance/*）。 */
export const BACKEND_URL = process.env.D3_BACKEND_URL || 'http://127.0.0.1:8188';

export const ADMIN = { username: 'admin', password: 'AdminPass-1' };
export const EMPLOYEE = { username: 'employee', password: 'EmployeePass-1' };

/** 证据根下的绝对路径。 */
export function d3Path(...parts: string[]): string {
  return path.join(D3_ROOT, ...parts);
}

function ensureDir(target: string): void {
  fs.mkdirSync(path.dirname(target), { recursive: true });
}

export interface ShotOptions {
  fullPage?: boolean;
  locator?: Locator;
}

/**
 * `shotFor('<spec>')` 返回截图函数：写到 `D3_ROOT/screenshots/<LABEL>/<spec>/<name>.png`，
 * 成功态也必须截图，返回绝对路径。传 locator 时只截该元素。
 */
export function shotFor(spec: string): (page: Page, name: string, opts?: ShotOptions) => Promise<string> {
  return async (page: Page, name: string, opts: ShotOptions = {}): Promise<string> => {
    const target = d3Path('screenshots', LABEL, spec, `${name}.png`);
    ensureDir(target);
    if (opts.locator) {
      await opts.locator.scrollIntoViewIfNeeded();
      await opts.locator.screenshot({ path: target, animations: 'disabled' });
    } else {
      await page.screenshot({
        path: target,
        fullPage: Boolean(opts.fullPage),
        animations: 'disabled',
      });
    }
    return target;
  };
}

/** 写 JSON 证据到 `D3_ROOT/actual/<LABEL>/<relative>.json`，返回绝对路径。 */
export function writeJson(relative: string, payload: unknown): string {
  const normalized = relative.endsWith('.json') ? relative : `${relative}.json`;
  const target = d3Path('actual', LABEL, normalized);
  ensureDir(target);
  fs.writeFileSync(target, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  return target;
}

// ---------------------------------------------------------------- 控制路由

function controlUrl(suffix: string): string {
  return `${BACKEND_URL}${suffix.startsWith('/') ? suffix : `/${suffix}`}`;
}

async function readControlBody(response: APIResponse, kind: string, label: string): Promise<any> {
  if (!response.ok()) {
    throw new Error(`控制路由 ${kind} ${label} 失败：HTTP ${response.status()} ${await response.text()}`);
  }
  return response.json();
}

/** 调用验收控制路由 GET（直连后端，不带浏览器 Cookie）。 */
export async function controlGet(request: APIRequestContext, route: string): Promise<any> {
  const response = await request.get(controlUrl(route), { timeout: 120_000 });
  return readControlBody(response, 'GET', route);
}

/** 调用验收控制路由 POST（直连后端，不带浏览器 Cookie）。 */
export async function controlPost(request: APIRequestContext, route: string, data?: unknown): Promise<any> {
  const response = await request.post(controlUrl(route), {
    data: data ?? {},
    timeout: 300_000,
    headers: { Accept: 'application/json' },
  });
  return readControlBody(response, 'POST', route);
}

/** `/__acceptance/state` 快照。 */
export async function acceptanceState(request: APIRequestContext): Promise<any> {
  return controlGet(request, '/__acceptance/state');
}

/** `/__acceptance/fixtures` 文件清单（含绝对路径）。 */
export async function acceptanceFixtures(
  request: APIRequestContext,
): Promise<Record<string, { path: string; filename: string; kind: string }>> {
  return controlGet(request, '/__acceptance/fixtures');
}

// ---------------------------------------------------------------- 浏览器会话

export interface SessionOptions {
  viewport?: { width: number; height: number };
}

/**
 * 创建一个已登录的浏览器上下文。
 *
 * 关键点：先 `browser.newContext`，再在 `context.request` 上真实调用
 * `POST /api/v1/auth/login`（带 `Origin: BASE_URL`），Cookie 进入 context 的
 * cookie jar；随后新建的 page 首屏 `/api/v1/auth/me` 即处于已登录状态。
 */
export async function openSession(
  browser: Browser,
  role: 'admin' | 'employee',
  options: SessionOptions = {},
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({
    baseURL: BASE_URL,
    viewport: options.viewport ?? { width: 1440, height: 900 },
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  });
  const credentials = role === 'admin' ? ADMIN : EMPLOYEE;
  try {
    const response = await context.request.post(`${BASE_URL}/api/v1/auth/login`, {
      data: credentials,
      headers: { Origin: BASE_URL, Accept: 'application/json' },
      timeout: 30_000,
    });
    if (response.status() !== 200) {
      throw new Error(`API 登录失败（${role}）：HTTP ${response.status()} ${await response.text()}`);
    }
    const page = await context.newPage();
    return { context, page };
  } catch (error) {
    await context.close().catch(() => undefined);
    throw error;
  }
}

/** 从 /login 开始真实填表点击登录，并等待进入 /chat 欢迎页。 */
export async function loginViaUi(page: Page, role: 'admin' | 'employee'): Promise<void> {
  const credentials = role === 'admin' ? ADMIN : EMPLOYEE;
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
  await page.getByLabel('账号').fill(credentials.username);
  await page.getByLabel('密码').fill(credentials.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByRole('heading', { name: '有什么需要查询的？' })).toBeVisible();
}

// ---------------------------------------------------------------- 问答步骤

/**
 * 真实 UI 提问：填写输入框、点击发送，并等待消息区新增一条 `.message-assistant`
 * （发送中占位卡也算一条），返回最后一条 assistant 卡片 Locator。
 */
export async function askViaUi(page: Page, question: string): Promise<Locator> {
  const before = await page.locator('.message-assistant').count();
  await page.getByLabel('输入你的问题').fill(question);
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.locator('.message-assistant')).toHaveCount(before + 1, { timeout: 30_000 });
  return page.locator('.message-assistant').last();
}

/** 等待当前提问完成（`正在查找资料…` 占位消失），返回最后一条 assistant 卡片。 */
export async function waitForAnswer(page: Page, timeout = 45_000): Promise<Locator> {
  await expect(page.locator('.typing')).toHaveCount(0, { timeout });
  const answer = page.locator('.message-assistant').last();
  await expect(answer).toBeVisible({ timeout });
  return answer;
}

/** 点击侧边栏「新建对话」并等待回到 /chat 欢迎页。 */
export async function openConversation(page: Page): Promise<void> {
  await page.getByRole('link', { name: '新建对话' }).click();
  await expect(page).toHaveURL(/\/chat$/);
}

// ---------------------------------------------------------------- 网络与密钥检查（A-29）

/** 开始记录页面全部请求 URL（含 WebSocket）；返回记录数组，page 关闭前持续有效。 */
export function trackRequests(page: Page): string[] {
  const urls: string[] = [];
  page.on('request', (request) => {
    urls.push(request.url());
  });
  page.on('websocket', (socket) => {
    urls.push(socket.url());
  });
  return urls;
}

/** 契约 §3 提及的别名。 */
export const collectRequests = trackRequests;

const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '::1', '[::1]']);
const NON_NETWORK_PROTOCOLS = new Set(['data:', 'blob:', 'about:', 'chrome-extension:']);

/** 过滤出非回环请求（含 ws/wss）；非网络 scheme 不计为出站。 */
export function externalRequests(urls: string[]): string[] {
  const external: string[] = [];
  for (const url of urls) {
    try {
      const parsed = new URL(url);
      if (NON_NETWORK_PROTOCOLS.has(parsed.protocol)) continue;
      if (LOOPBACK_HOSTS.has(parsed.hostname)) continue;
      external.push(url);
    } catch {
      // 非 URL 文本（如页面内相对标识）不计为网络出站
    }
  }
  return external;
}

/** 断言请求列表里没有非回环请求（失败信息带出具体 URL）。 */
export function expectNoExternalRequests(urls: string[]): void {
  const external = externalRequests(urls);
  expect(external, `检测到非回环请求：${JSON.stringify(external)}`).toEqual([]);
}

interface SecretMarker {
  name: string;
  pattern: RegExp;
}

const SECRET_MARKERS: SecretMarker[] = [
  { name: 'model_api_key:sk-', pattern: /sk-[A-Za-z0-9_-]{16,}/ },
  { name: 'model_api_key_env:DEEPSEEK_API_KEY', pattern: /DEEPSEEK_API_KEY|MODEL_API_KEY/ },
  { name: 'model_base_url:api.deepseek.com', pattern: /api\.deepseek\.com/i },
  { name: 'fake_model_key', pattern: /sk-t09-fake-model-key-never-real/ },
  { name: 'fake_ocr_secret_id', pattern: /T09FAKEOCRIDNEVERREAL/ },
  { name: 'fake_ocr_secret_key', pattern: /t09-fake-ocr-key-never-real/ },
  { name: 'account_password', pattern: /AdminPass-1|EmployeePass-1/ },
];

function markerHits(text: string): string[] {
  return SECRET_MARKERS.filter((marker) => marker.pattern.test(text)).map((marker) => marker.name);
}

/** 扫描页面 DOM 文本与 localStorage/sessionStorage，返回命中的密钥标记名。 */
export async function scanPageForSecrets(
  page: Page,
): Promise<{ domHits: string[]; storageHits: string[] }> {
  const domText = await page.evaluate(() => document.documentElement?.innerText ?? '');
  const storageText = await page.evaluate(() => {
    const collect = (storage: Storage): Record<string, string> => {
      const values: Record<string, string> = {};
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index);
        if (key !== null) values[key] = storage.getItem(key) ?? '';
      }
      return values;
    };
    return JSON.stringify({
      local: collect(window.localStorage),
      session: collect(window.sessionStorage),
    });
  });
  return { domHits: markerHits(domText), storageHits: markerHits(storageText) };
}

/** 额外扫描（契约外扩展）：把调用方给定的明文也纳入 DOM/存储扫描。 */
export async function scanForSecrets(
  page: Page,
  secrets: string[] = [],
): Promise<{ domHits: string[]; storageHits: string[] }> {
  const result = await scanPageForSecrets(page);
  const domText = await page.evaluate(() => document.documentElement?.innerText ?? '');
  for (const secret of secrets) {
    if (secret && domText.includes(secret)) result.domHits.push(`custom:${secret}`);
  }
  return result;
}

/** 扫描当前文档已加载脚本（外链拉取源码 + 内联 script）中的密钥标记。 */
export async function scanLoadedScriptsForSecrets(
  page: Page,
): Promise<{ scriptUrls: string[]; hits: string[] }> {
  const scriptUrls = await page.evaluate(() =>
    Array.from(document.scripts)
      .map((script) => script.src)
      .filter((src): src is string => Boolean(src)),
  );
  const hits: string[] = [];
  for (const url of scriptUrls) {
    try {
      const response = await page.request.get(url, { timeout: 30_000 });
      if (!response.ok()) continue;
      const text = await response.text();
      for (const marker of markerHits(text)) hits.push(`${url} :: ${marker}`);
    } catch {
      // 拉取失败不视为密钥命中（由 A-29 spec 另行记录脚本清单）
    }
  }
  const inlineText = await page.evaluate(() =>
    Array.from(document.scripts)
      .filter((script) => !script.src)
      .map((script) => script.textContent ?? '')
      .join('\n'),
  );
  for (const marker of markerHits(inlineText)) hits.push(`inline-script :: ${marker}`);
  return { scriptUrls, hits };
}

// ---------------------------------------------------------------- 轮询辅助

/** 轮询 `/__acceptance/gateway/status` 直到 predicate 为真，返回最后状态；超时抛错。 */
export async function waitForGatewayStatus(
  request: APIRequestContext,
  predicate: (state: any) => boolean,
  timeoutMs = 30_000,
): Promise<any> {
  const deadline = Date.now() + timeoutMs;
  let last: any = null;
  while (Date.now() < deadline) {
    last = await controlGet(request, '/__acceptance/gateway/status');
    if (predicate(last)) return last;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`网关状态在 ${timeoutMs}ms 内未满足条件：${JSON.stringify(last)}`);
}

/** 等待资料列表中出现指定文件名的行，且该行状态为「待确认」。 */
export async function waitForDocumentReview(page: Page, documentName: string, timeoutMs = 90_000): Promise<void> {
  const row = page.locator('tbody tr').filter({ hasText: documentName });
  await expect(row).toHaveCount(1, { timeout: timeoutMs });
  await expect(row).toContainText('待确认', { timeout: timeoutMs });
}

/** 契约 §3 提到的提问别名。 */
export const ask = askViaUi;
