/**
 * T08 原型渲染与截图（开发辅助脚本，不是产品依赖）。
 * 使用本机已安装的 Playwright Chromium 打开五页原型，记录控制台错误、横向溢出与截图。
 * 原型依赖墨刀 CDN 的 tailwindcss/iconify；若网络不可用会记录加载失败而不是伪造渲染。
 */
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, '../..');
const PROJECT = path.resolve(FRONTEND, '..');
const PROTOTYPE_DIR = path.join(PROJECT, '原型设计', 'ai-knowledge-base');
const OUTPUT = path.join(PROJECT, 'docs', 'evidence', 'T08', 'prototype-shots');
const PORT = 8099;

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.zip': 'application/zip',
};

function startServer() {
  const server = http.createServer((request, response) => {
    const urlPath = decodeURIComponent((request.url ?? '/').split('?')[0]);
    const relative = urlPath.replace(/^\/+/, '');
    const target = path.resolve(PROTOTYPE_DIR, relative || 'home.html');
    if (!target.startsWith(PROTOTYPE_DIR) || !fs.existsSync(target) || !fs.statSync(target).isFile()) {
      response.statusCode = 404;
      response.end('not found');
      return;
    }
    response.setHeader('Content-Type', MIME[path.extname(target).toLowerCase()] ?? 'application/octet-stream');
    response.end(fs.readFileSync(target));
  });
  return new Promise((resolve) => server.listen(PORT, '127.0.0.1', () => resolve(server)));
}

function digest(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

async function main() {
  fs.mkdirSync(path.join(OUTPUT, 'desktop'), { recursive: true });
  fs.mkdirSync(path.join(OUTPUT, 'mobile'), { recursive: true });
  const server = await startServer();
  const browser = await chromium.launch({ headless: true });
  const report = { base: `http://127.0.0.1:${PORT}`, pages: [], console: [], overflow: [], screenshots: [] };

  async function shoot(page, group, name) {
    const file = path.join(OUTPUT, group, `${name}.png`);
    await page.screenshot({ path: file });
    report.screenshots.push({ file: path.relative(PROJECT, file).replace(/\\/g, '/'), sha256: digest(file) });
  }

  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' });
    context.on('console', (message) => {
      if (message.type() === 'error') report.console.push({ page: context.pages().at(-1)?.url(), text: message.text() });
    });
    const page = await context.newPage();

    const pages = ['home.html', 'session.html', 'states.html', 'staff.html', 'materials.html'];
    for (const name of pages) {
      const response = await page.goto(`${report.base}/${name}`, { waitUntil: 'networkidle', timeout: 30_000 });
      await page.waitForTimeout(1200);
      const metrics = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
        title: document.title,
      }));
      report.pages.push({ name, status: response?.status(), ...metrics });
      if (metrics.scrollWidth > metrics.innerWidth + 1) {
        report.overflow.push({ name, ...metrics });
      }
      await shoot(page, 'desktop', name.replace('.html', ''));
    }

    await page.goto(`${report.base}/home.html`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(800);
    await page.locator('[data-question]').first().click();
    await page.waitForTimeout(300);
    await shoot(page, 'desktop', 'home-example-filled');
    await page.locator('#askForm button[type=submit]').click();
    await page.waitForTimeout(1600);
    await shoot(page, 'desktop', 'home-answer');

    await page.goto(`${report.base}/session.html`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(800);
    await page.locator('[data-open-source]').first().click();
    await page.waitForTimeout(600);
    await shoot(page, 'desktop', 'session-source-drawer');
    await page.locator('#drawerClose').click();

    await page.goto(`${report.base}/materials.html`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(800);
    await page.locator('#openUploadButton').click();
    await page.waitForTimeout(300);
    await shoot(page, 'desktop', 'materials-upload-modal');
    await page.locator('#cancelUploadButton').click();
    await page.locator('[data-action="review"]').first().click();
    await page.waitForTimeout(400);
    await shoot(page, 'desktop', 'materials-check-drawer');
    await page.locator('#closeDrawerButton').click();

    await page.goto(`${report.base}/states.html`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(OUTPUT, 'desktop', 'states-fullpage.png'), fullPage: true });
    report.screenshots.push({
      file: 'docs/evidence/T08/prototype-shots/desktop/states-fullpage.png',
      sha256: digest(path.join(OUTPUT, 'desktop', 'states-fullpage.png')),
    });
    await context.close();

    const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: 'zh-CN' });
    const mobilePage = await mobile.newPage();
    for (const name of ['home.html', 'session.html', 'materials.html', 'states.html', 'staff.html']) {
      await mobilePage.goto(`${report.base}/${name}`, { waitUntil: 'networkidle', timeout: 30_000 });
      await mobilePage.waitForTimeout(800);
      const metrics = await mobilePage.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
      }));
      report.overflow.push({ name: `mobile:${name}`, ...metrics });
      await shoot(mobilePage, 'mobile', name.replace('.html', ''));
    }
    await mobile.close();
  } finally {
    await browser.close();
    server.close();
  }

  fs.writeFileSync(path.join(OUTPUT, 'render-report.json'), JSON.stringify(report, null, 2), 'utf8');
  console.log(JSON.stringify({ pages: report.pages.length, screenshots: report.screenshots.length, overflow: report.overflow.length, consoleErrors: report.console.length }, null, 2));
}

await main();
