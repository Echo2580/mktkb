/**
 * T09-D3 原型视觉对照材料 · 阶段 1（visual-acceptance 专用，不属于产品依赖）。
 *
 * 职责：只读渲染 `原型设计/ai-knowledge-base/{home,session,states,staff,materials}.html`，
 * 在本地静态服务上以 Playwright Chromium 采集桌面 1440×900 与移动 390×844 截图，并记录：
 *   - 页面标题 / 关键 DOM 地标文本 / 按钮文案
 *   - 横向溢出（含 body 裁剪、最右元素边界）与纵向滚动
 *   - 控制台错误、未捕获异常
 *   - 外部 CDN（墨刀 tailwindcss / iconify）资源加载成功或失败、渲染健康度
 *   - 五页 HTML 源码 SHA-256（截图前后各一次，证明只读未改）
 *
 * 输出（全部在 docs/evidence/T09/D3/）：
 *   screenshots/prototype/desktop/<page>.png、screenshots/prototype/mobile/<page>.png
 *   actual/prototype-inventory.json
 *   logs/prototype-capture-<label>.{command.json,stdout.log,stderr.log,exitcode}
 *
 * 用法（cwd 必须是 frontend/）：node e2e/support/capture-prototypes-acceptance.mjs --label d3-prototype-01
 *
 * 约束：不修改原型文件；不访问真实模型/OCR；不安装依赖；端口使用临时空闲端口，避免与他人冲突。
 * CDN 不可达时如实记录“渲染降级”，绝不伪造渲染效果。
 */
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(HERE, '..', '..');
const PROJECT_ROOT = path.resolve(FRONTEND_ROOT, '..');
const PROTOTYPE_DIR = path.join(PROJECT_ROOT, '原型设计', 'ai-knowledge-base');
const D3_ROOT = path.join(PROJECT_ROOT, 'docs', 'evidence', 'T09', 'D3');
const SCREENSHOT_ROOT = path.join(D3_ROOT, 'screenshots', 'prototype');
const ACTUAL_ROOT = path.join(D3_ROOT, 'actual');
const LOG_ROOT = path.join(D3_ROOT, 'logs');

const PAGES = [
  { slug: 'home', file: 'home.html' },
  { slug: 'session', file: 'session.html' },
  { slug: 'states', file: 'states.html' },
  { slug: 'staff', file: 'staff.html' },
  { slug: 'materials', file: 'materials.html' },
];

const VIEWPORTS = [
  // 与 D3 验收配置保持一致：使用普通视口（不启用 isMobile），使移动截图与真实产品页在 390px 视口下可比。
  // 原型本身 min-w-[1120px]，因此 390px 视口下会如实出现内容横向溢出（不回退、不伪造）。
  { group: 'desktop', width: 1440, height: 900, isMobile: false, hasTouch: false, note: '桌面基准 1440×900' },
  { group: 'mobile', width: 390, height: 844, isMobile: false, hasTouch: false, note: '移动基准 390×844（普通视口，未启用 isMobile 缩放）' },
];

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.json': 'application/json; charset=utf-8',
  '.zip': 'application/zip',
};

const CDN_DECLARED = [
  'https://modao.cc/agent-py/static/source/js/tailwindcss.js',
  'https://modao.cc/agent-py/static/source/js/iconify-icon.min.js',
];

// ---------------------------------------------------------------- CLI / 日志

function parseArgs(argv) {
  const args = { label: 'd3-prototype-01' };
  for (let i = 0; i < argv.length; i += 1) {
    const item = argv[i];
    if (item === '--label') {
      args.label = argv[i + 1];
      i += 1;
    } else if (item.startsWith('--label=')) {
      args.label = item.slice('--label='.length);
    } else if (item === '--help' || item === '-h') {
      args.help = true;
    } else {
      throw new Error(`未知参数：${item}`);
    }
  }
  if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(args.label ?? '')) {
    throw new Error(`--label 必须匹配 ^[a-z0-9][a-z0-9-]{0,63}$，收到：${args.label}`);
  }
  return args;
}

const ARGS = parseArgs(process.argv.slice(2));
const LABEL = ARGS.label;
const LOG_BASE = path.join(LOG_ROOT, `prototype-capture-${LABEL}`);

const stdoutLines = [];
const stderrLines = [];

function logLine(message) {
  const text = typeof message === 'string' ? message : JSON.stringify(message, null, 2);
  stdoutLines.push(text);
  // 直接写 fd1，避免被上层重定向时丢失
  try {
    fs.writeSync(process.stdout.fd, `${text}\n`);
  } catch {
    // stdout 已关闭（EPIPE）时仍保留内存缓冲，退出阶段写入日志文件
  }
}

function logErr(message) {
  const text = typeof message === 'string' ? message : JSON.stringify(message, null, 2);
  stderrLines.push(text);
  try {
    fs.writeSync(process.stderr.fd, `${text}\n`);
  } catch {
    // 同上
  }
}

function writeLogs(exitCode) {
  try {
    fs.mkdirSync(LOG_ROOT, { recursive: true });
    fs.writeFileSync(`${LOG_BASE}.stdout.log`, `${stdoutLines.join('\n')}\n`, 'utf8');
    fs.writeFileSync(`${LOG_BASE}.stderr.log`, `${stderrLines.join('\n')}\n`, 'utf8');
    fs.writeFileSync(`${LOG_BASE}.exitcode`, `${exitCode}\n`, 'utf8');
  } catch (error) {
    fs.writeSync(process.stderr.fd, `写日志失败：${error instanceof Error ? error.stack : String(error)}\n`);
  }
}

const STARTED_AT = new Date();
const COMMAND_RECORD = {
  label: LABEL,
  argv: process.argv.slice(),
  exec_argv: process.execPath ? [process.execPath, ...process.argv.slice(1)] : process.argv.slice(),
  cwd: process.cwd().replace(/\\/g, '/'),
  script: fileURLToPath(import.meta.url).replace(/\\/g, '/'),
  script_sha256: sha256File(fileURLToPath(import.meta.url)),
  node: process.version,
  platform: `${process.platform} ${process.arch}`,
  started_at: STARTED_AT.toISOString(),
  finished_at: null,
  exitcode: null,
  command_line: `node e2e/support/capture-prototypes-acceptance.mjs --label ${LABEL}`,
  ports: null,
  outputs: {
    inventory: path.relative(PROJECT_ROOT, path.join(ACTUAL_ROOT, 'prototype-inventory.json')).replace(/\\/g, '/'),
    screenshots: path.relative(PROJECT_ROOT, SCREENSHOT_ROOT).replace(/\\/g, '/'),
    logs_base: path.relative(PROJECT_ROOT, LOG_BASE).replace(/\\/g, '/'),
  },
};

function writeCommandRecord(exitCode) {
  try {
    fs.mkdirSync(LOG_ROOT, { recursive: true });
    COMMAND_RECORD.finished_at = new Date().toISOString();
    COMMAND_RECORD.exitcode = exitCode;
    fs.writeFileSync(`${LOG_BASE}.command.json`, `${JSON.stringify(COMMAND_RECORD, null, 2)}\n`, 'utf8');
  } catch (error) {
    fs.writeSync(process.stderr.fd, `写 command.json 失败：${error instanceof Error ? error.stack : String(error)}\n`);
  }
}

function finalizeAndExit(exitCode) {
  writeCommandRecord(exitCode);
  writeLogs(exitCode);
  process.exitCode = exitCode;
}

process.on('exit', (code) => {
  // 兜底：正常路径已写过，重复写覆盖为同内容；异常路径保证至少留下 command.json 与 exitcode
  if (COMMAND_RECORD.exitcode === code && COMMAND_RECORD.finished_at !== null) return;
  COMMAND_RECORD.finished_at = COMMAND_RECORD.finished_at ?? new Date().toISOString();
  COMMAND_RECORD.exitcode = code;
  try {
    fs.mkdirSync(LOG_ROOT, { recursive: true });
    fs.writeFileSync(`${LOG_BASE}.command.json`, `${JSON.stringify(COMMAND_RECORD, null, 2)}\n`, 'utf8');
    fs.writeFileSync(`${LOG_BASE}.stdout.log`, `${stdoutLines.join('\n')}\n`, 'utf8');
    fs.writeFileSync(`${LOG_BASE}.stderr.log`, `${stderrLines.join('\n')}\n`, 'utf8');
    fs.writeFileSync(`${LOG_BASE}.exitcode`, `${code}\n`, 'utf8');
  } catch {
    // 忽略：进程退出阶段无法再恢复
  }
});

// ---------------------------------------------------------------- 工具

function sha256File(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

function sha256Buffer(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

function toRepoPath(absolutePath) {
  return path.relative(PROJECT_ROOT, absolutePath).replace(/\\/g, '/');
}

function safeHost(url) {
  try {
    return new URL(url).host;
  } catch {
    return null;
  }
}

function isLocalHost(host) {
  if (!host) return true;
  const name = host.split(':')[0].toLowerCase();
  return name === '127.0.0.1' || name === 'localhost' || name === '::1' || name === '[::1]';
}

function startStaticServer() {
  const server = http.createServer((request, response) => {
    let urlPath;
    try {
      urlPath = decodeURIComponent((request.url ?? '/').split('?')[0]);
    } catch {
      response.statusCode = 400;
      response.end('bad request');
      return;
    }
    const relative = urlPath.replace(/^\/+/, '') || 'home.html';
    const target = path.resolve(PROTOTYPE_DIR, relative);
    if (!target.startsWith(PROTOTYPE_DIR) || !fs.existsSync(target) || !fs.statSync(target).isFile()) {
      response.statusCode = 404;
      response.end('not found');
      return;
    }
    response.setHeader('Content-Type', MIME[path.extname(target).toLowerCase()] ?? 'application/octet-stream');
    response.setHeader('Cache-Control', 'no-store');
    response.end(fs.readFileSync(target));
  });
  return new Promise((resolve, reject) => {
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

function snapshotHtmlSources() {
  const snapshot = {};
  for (const page of PAGES) {
    const filePath = path.join(PROTOTYPE_DIR, page.file);
    const stat = fs.statSync(filePath);
    snapshot[page.slug] = {
      file: page.file,
      path: toRepoPath(filePath),
      bytes: stat.size,
      mtime_iso: stat.mtime.toISOString(),
      sha256: sha256File(filePath),
    };
  }
  return snapshot;
}

function scanDeclaredExternalUrls() {
  const declared = {};
  const pattern = /https?:\/\/[^"'\s<>)]+/g;
  for (const page of PAGES) {
    const text = fs.readFileSync(path.join(PROTOTYPE_DIR, page.file), 'utf8');
    const urls = [...new Set(text.match(pattern) ?? [])].sort();
    declared[page.slug] = urls;
  }
  return declared;
}

// 页面内采集：渲染健康度 + 横向溢出 + DOM 地标
async function collectDomEvidence(page) {
  return page.evaluate(() => {
    const clean = (value) => (value ?? '').replace(/\s+/g, ' ').trim();
    const isVisible = (element) => {
      const rect = element.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return false;
      const style = getComputedStyle(element);
      return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
    };
    const summarizeElement = (element) => {
      const tag = element.tagName.toLowerCase();
      const id = element.id ? `#${element.id}` : '';
      const classes = typeof element.className === 'string' ? element.className.split(/\s+/).filter(Boolean).slice(0, 3) : [];
      return `${tag}${id}${classes.length ? `.${classes.join('.')}` : ''}`;
    };
    const describe = (element) => ({
      tag: element.tagName.toLowerCase(),
      text: clean(element.textContent),
      testid: element.getAttribute('data-testid') ?? null,
      aria_label: element.getAttribute('aria-label') ?? null,
    });

    const docEl = document.documentElement;
    const body = document.body;
    const innerWidth = window.innerWidth;
    const innerHeight = window.innerHeight;

    // 区分“内容真的横向溢出”与“刻意藏在画布外的浮层”（如 translate-x-full 的抽屉）。
    // 隐藏浮层不应被误报为布局溢出；它们单独记录在 off_canvas 里。
    let contentMaxRight = -Infinity;
    let contentMaxElement = null;
    let elementsBeyondViewport = 0;
    const offCanvasRoots = [];
    const offCanvas = [];
    for (const element of body.querySelectorAll('*')) {
      const rect = element.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) continue;
      // 画布外浮层（如关闭状态的抽屉）整体跳过：其子元素同样不属于布局内容
      if (offCanvasRoots.some((root) => root !== element && root.contains(element))) continue;
      const style = getComputedStyle(element);
      const fullyOutsideHorizontally = rect.right <= 0.5 || rect.left >= innerWidth - 0.5;
      const transformed = style.transform && style.transform !== 'none';
      const overlayLike =
        style.position === 'fixed' ||
        style.position === 'absolute' ||
        element.getAttribute('role') === 'dialog' ||
        element.getAttribute('aria-modal') === 'true';
      if (fullyOutsideHorizontally && (transformed || overlayLike)) {
        offCanvasRoots.push(element);
        if (offCanvas.length < 12) {
          offCanvas.push({
            element: summarizeElement(element),
            role: element.getAttribute('role') ?? null,
            position: style.position,
            transform: style.transform,
            rect: { left: Math.round(rect.left), right: Math.round(rect.right) },
            aria_hidden: element.getAttribute('aria-hidden') ?? null,
          });
        }
        continue;
      }
      if (rect.right > contentMaxRight) {
        contentMaxRight = rect.right;
        contentMaxElement = summarizeElement(element);
      }
      if (Math.round(rect.right) > innerWidth + 1) elementsBeyondViewport += 1;
    }

    const bodyStyle = getComputedStyle(body);
    let ruleCount = 0;
    let stylesheetHrefs = [];
    for (const sheet of document.styleSheets) {
      if (sheet.href) stylesheetHrefs.push(sheet.href);
      try {
        ruleCount += sheet.cssRules.length;
      } catch {
        // 跨域样式表无法读规则，忽略
      }
    }

    const iconifyElements = [...document.querySelectorAll('iconify-icon')];
    let renderedIcons = 0;
    for (const element of iconifyElements) {
      // iconify-icon 会以 shadow DOM 渲染 svg；未渲染表示图标数据/脚本失败
      if (element.shadowRoot && element.shadowRoot.querySelector('svg')) renderedIcons += 1;
    }

    const headings = [...document.querySelectorAll('h1,h2,h3')]
      .filter(isVisible)
      .map(describe)
      .slice(0, 40);

    const navs = [...document.querySelectorAll('nav,[role="navigation"]')]
      .filter(isVisible)
      .map((nav) => ({
        aria_label: nav.getAttribute('aria-label') ?? null,
        items: [...nav.querySelectorAll('a,button')].filter(isVisible).map((node) => clean(node.textContent)).filter(Boolean),
      }))
      .slice(0, 10);

    const visibleButtons = [...document.querySelectorAll('button, a[role="button"]')]
      .filter(isVisible)
      .map((node) => clean(node.textContent))
      .filter(Boolean);

    const asideBrand = clean(document.querySelector('aside a')?.textContent);
    const mainHeading = clean(document.querySelector('main h1')?.textContent);
    const landmarkSelectors = ['aside', 'header', 'main', 'nav', 'footer'];
    const landmarks = landmarkSelectors
      .map((selector) => ({ selector, count: document.querySelectorAll(selector).length }))
      .filter((entry) => entry.count > 0);

    return {
      title: document.title,
      lang: docEl.getAttribute('lang'),
      meta_viewport: document.querySelector('meta[name="viewport"]')?.getAttribute('content') ?? null,
      ready_state: document.readyState,
      body: {
        margin: bodyStyle.margin,
        font_family: bodyStyle.fontFamily,
        font_size: bodyStyle.fontSize,
        overflow_x: bodyStyle.overflowX,
        overflow_y: bodyStyle.overflowY,
      },
      stylesheets: { count: document.styleSheets.length, rule_count: ruleCount, hrefs: stylesheetHrefs.slice(0, 10) },
      iconify: {
        elements: iconifyElements.length,
        rendered_svg: renderedIcons,
        custom_element_defined: !!window.customElements?.get?.('iconify-icon'),
        global_defined: typeof window.IconifyIcon !== 'undefined',
      },
      tailwind_global_defined: typeof window.tailwind !== 'undefined',
      landmarks,
      headings,
      navs,
      brand_text: asideBrand,
      main_heading: mainHeading,
      visible_buttons: [...new Set(visibleButtons)].slice(0, 40),
      overflow: {
        inner_width: innerWidth,
        inner_height: innerHeight,
        document_scroll_width: docEl.scrollWidth,
        document_client_width: docEl.clientWidth,
        body_scroll_width: body.scrollWidth,
        body_client_width: body.clientWidth,
        document_scroll_height: docEl.scrollHeight,
        // 内容溢出：以 body.scrollWidth 为准（documentElement 会被画布外抽屉撑大）
        horizontal_overflow: body.scrollWidth > innerWidth + 1,
        // 原始 documentElement 溢出（含画布外浮层，仅作参考）
        document_horizontal_overflow: docEl.scrollWidth > innerWidth + 1,
        vertical_scroll: docEl.scrollHeight > innerHeight + 1,
        content_max_right: contentMaxRight === -Infinity ? null : Math.round(contentMaxRight * 100) / 100,
        content_max_element: contentMaxElement,
        elements_beyond_viewport: elementsBeyondViewport,
        off_canvas_count: offCanvasRoots.length,
        off_canvas: offCanvas,
      },
      dom_nodes: document.querySelectorAll('*').length,
    };
  });
}

function classifyRenderHealth(dom) {
  const cssApplied = dom.body.margin === '0px' && dom.stylesheets.rule_count > 20;
  const tailwindLoaded = dom.tailwind_global_defined || (dom.stylesheets.rule_count > 200 && cssApplied);
  const iconifyLoaded = dom.iconify.custom_element_defined && dom.iconify.rendered_svg > 0;
  const iconifyScriptLoaded = dom.iconify.custom_element_defined;
  let status;
  let note;
  if (tailwindLoaded && iconifyLoaded) {
    status = 'full';
    note = 'Tailwind 与 iconify 均生效，原型按设计稿渲染';
  } else if (!tailwindLoaded && !iconifyScriptLoaded) {
    status = 'degraded_cdn_unavailable';
    note = 'Tailwind 与 iconify 均未生效：CDN 不可达时原型会降级为无样式 HTML，本证据不伪造渲染效果';
  } else if (!tailwindLoaded) {
    status = 'degraded_tailwind_missing';
    note = 'Tailwind 未生效，布局/间距/颜色全部缺失';
  } else if (!iconifyScriptLoaded) {
    status = 'degraded_iconify_missing';
    note = 'iconify 图标脚本未生效，图标位置为空';
  } else {
    status = 'degraded_icons_unrendered';
    note = 'iconify 脚本已执行但图标 svg 未渲染（图标数据请求可能失败）';
  }
  return {
    status,
    note,
    tailwind_loaded: tailwindLoaded,
    iconify_script_loaded: iconifyScriptLoaded,
    iconify_icons_rendered: iconifyLoaded,
  };
}

// ---------------------------------------------------------------- 主流程

async function captureViewportGroup(browser, viewport, baseUrl) {
  const results = [];
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: 1,
    isMobile: viewport.isMobile,
    hasTouch: viewport.hasTouch,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    colorScheme: 'light',
    reducedMotion: 'reduce',
  });

  for (const pageDef of PAGES) {
    const record = {
      slug: pageDef.slug,
      file: pageDef.file,
      group: viewport.group,
      viewport: { width: viewport.width, height: viewport.height, is_mobile: viewport.isMobile },
      url: `${baseUrl}/${pageDef.file}`,
      status: null,
      load_error: null,
      console: [],
      console_errors: [],
      page_errors: [],
      requests: { total: 0, external_total: 0, external_failed: 0, failed: [] },
      cdn: [],
      network: [],
      dom: null,
      render_health: null,
      screenshot: null,
    };
    const page = await context.newPage();
    const responses = [];
    const requestByUrl = new Map();
    page.on('request', (request) => {
      const host = safeHost(request.url());
      requestByUrl.set(request.url(), { host, resource_type: request.resourceType() });
      record.requests.total += 1;
      if (!isLocalHost(host)) record.requests.external_total += 1;
    });
    page.on('response', (response) => {
      const url = response.url();
      if (isLocalHost(safeHost(url))) return;
      const request = requestByUrl.get(url);
      responses.push({
        url,
        host: safeHost(url),
        status: response.status(),
        resource_type: request?.resource_type ?? response.request().resourceType(),
      });
    });
    page.on('requestfailed', (request) => {
      const url = request.url();
      const host = safeHost(url);
      if (isLocalHost(host)) return;
      record.requests.external_failed += 1;
      record.requests.failed.push({
        url,
        host,
        resource_type: request.resourceType(),
        error_text: request.failure()?.errorText ?? null,
      });
    });
    page.on('console', (message) => {
      const entry = { type: message.type(), text: message.text(), location: message.location()?.url ?? null };
      if (entry.type === 'error' || entry.type === 'warning') record.console.push(entry);
      if (entry.type === 'error') record.console_errors.push(entry);
    });
    page.on('pageerror', (error) => {
      record.page_errors.push({ message: error.message, stack: error.stack ?? null });
    });

    try {
      const response = await page.goto(record.url, { waitUntil: 'load', timeout: 45_000 });
      record.status = response?.status() ?? null;
      // 等待外部 CDN 与图标数据请求静默；不可达时不阻塞（记录真实降级）
      await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
      // 稳定渲染：等 tailwind 生成样式或超时，再给图标 shadow DOM 一点时间
      await page
        .waitForFunction(
          () => typeof window.tailwind !== 'undefined' || document.styleSheets.length > 0,
          null,
          { timeout: 10_000 },
        )
        .catch(() => {});
      await page.waitForTimeout(1200);
      record.dom = await collectDomEvidence(page);
      record.render_health = classifyRenderHealth(record.dom);
    } catch (error) {
      record.load_error = error instanceof Error ? error.message : String(error);
    }

    const shotPath = path.join(SCREENSHOT_ROOT, viewport.group, `${pageDef.slug}.png`);
    try {
      fs.mkdirSync(path.dirname(shotPath), { recursive: true });
      await page.screenshot({ path: shotPath, animations: 'disabled' });
      const buffer = fs.readFileSync(shotPath);
      record.screenshot = {
        group: viewport.group,
        path: toRepoPath(shotPath),
        bytes: buffer.length,
        sha256: sha256Buffer(buffer),
      };
    } catch (error) {
      record.screenshot = { error: error instanceof Error ? error.message : String(error) };
      logErr(`截图失败 ${viewport.group}/${pageDef.slug}：${record.screenshot.error}`);
    }

    record.network = responses;
    const cdnHosts = new Set(['modao.cc', 'api.iconify.design', 'code.iconify.design', 'iconify.design']);
    for (const declared of CDN_DECLARED) {
      const match = responses.find((entry) => entry.url === declared);
      const failed = record.requests.failed.find((entry) => entry.url === declared);
      record.cdn.push({
        url: declared,
        role: declared.includes('tailwindcss') ? 'tailwindcss' : 'iconify-runtime',
        loaded: !!match && match.status >= 200 && match.status < 400,
        status: match?.status ?? null,
        failed: !!failed,
        error_text: failed?.error_text ?? null,
      });
    }
    record.cdn.push({
      url: 'iconify-icon-data (api.iconify.design)',
      role: 'iconify-icon-data',
      loaded: responses.some((entry) => entry.host === 'api.iconify.design' && entry.status >= 200 && entry.status < 400),
      status: responses.filter((entry) => entry.host === 'api.iconify.design').map((entry) => entry.status).slice(0, 5),
      failed: false,
      error_text: record.requests.failed
        .filter((entry) => (entry.host ?? '').includes('iconify'))
        .map((entry) => entry.error_text)
        .slice(0, 5)
        .join('; ') || null,
    });
    record.network_hosts = [...new Set(responses.map((entry) => entry.host).filter(Boolean))].sort();
    record.cdn_hosts_observed = [...new Set(responses.map((entry) => entry.host).filter((host) => host && cdnHosts.has(host)))].sort();

    results.push(record);
    logLine(
      `[${viewport.group}] ${pageDef.slug}: status=${record.status} title=${record.dom?.title ?? '(n/a)'} ` +
        `contentOverflow=${record.dom?.overflow.horizontal_overflow ?? 'n/a'} offCanvas=${record.dom?.overflow.off_canvas_count ?? 'n/a'} ` +
        `render=${record.render_health?.status ?? 'n/a'} consoleErrors=${record.console_errors.length} ` +
        `external=${record.requests.external_total}/failed=${record.requests.external_failed} shot=${record.screenshot?.path ?? 'FAILED'}`,
    );
    await page.close();
  }

  await context.close();
  return results;
}

async function main() {
  logLine(`[start] label=${LABEL} node=${process.version} cwd=${process.cwd().replace(/\\/g, '/')}`);
  logLine(`[paths] prototype=${toRepoPath(PROTOTYPE_DIR)} screenshots=${toRepoPath(SCREENSHOT_ROOT)} actual=${toRepoPath(ACTUAL_ROOT)}`);

  fs.mkdirSync(SCREENSHOT_ROOT, { recursive: true });
  fs.mkdirSync(ACTUAL_ROOT, { recursive: true });
  fs.mkdirSync(LOG_ROOT, { recursive: true });

  const htmlBefore = snapshotHtmlSources();
  COMMAND_RECORD.html_sha256_before = Object.fromEntries(
    Object.entries(htmlBefore).map(([slug, entry]) => [slug, entry.sha256]),
  );
  logLine(`[readonly] 截图前五页 HTML SHA-256：${JSON.stringify(COMMAND_RECORD.html_sha256_before, null, 2)}`);

  const server = await startStaticServer();
  const address = server.address();
  const baseUrl = `http://127.0.0.1:${address.port}`;
  COMMAND_RECORD.ports = { static_server: address.port };
  COMMAND_RECORD.static_server_url = baseUrl;
  logLine(`[server] 本地静态服务已启动 ${baseUrl}（临时端口，仅回环）`);

  const browser = await chromium.launch({ headless: true });
  const browserVersion = browser.version();
  logLine(`[browser] chromium ${browserVersion} headless`);
  COMMAND_RECORD.browser = { name: 'chromium', version: browserVersion, headless: true };

  const pages = [];
  try {
    for (const viewport of VIEWPORTS) {
      logLine(`[group] ${viewport.group} ${viewport.width}×${viewport.height} 开始`);
      const records = await captureViewportGroup(browser, viewport, baseUrl);
      pages.push(...records);
      logLine(`[group] ${viewport.group} 完成，${records.length} 页`);
    }
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }

  const htmlAfter = snapshotHtmlSources();
  const readonlyFiles = PAGES.map((page) => {
    const before = htmlBefore[page.slug];
    const after = htmlAfter[page.slug];
    return {
      file: page.file,
      path: toRepoPath(path.join(PROTOTYPE_DIR, page.file)),
      bytes_before: before.bytes,
      bytes_after: after.bytes,
      mtime_iso_before: before.mtime_iso,
      mtime_iso_after: after.mtime_iso,
      sha256_before: before.sha256,
      sha256_after: after.sha256,
      unchanged: before.sha256 === after.sha256 && before.bytes === after.bytes,
    };
  });
  const readonlyUnchanged = readonlyFiles.every((entry) => entry.unchanged);

  const screenshots = pages.map((record) => record.screenshot).filter((shot) => shot && !shot.error);
  const summary = {
    page_count: PAGES.length,
    viewport_groups: VIEWPORTS.map((viewport) => viewport.group),
    pages_captured: pages.length,
    screenshots: screenshots.length,
    screenshots_expected: PAGES.length * VIEWPORTS.length,
    readonly_unchanged: readonlyUnchanged,
    console_errors_total: pages.reduce((total, record) => total + record.console_errors.length, 0),
    page_errors_total: pages.reduce((total, record) => total + record.page_errors.length, 0),
    load_failures: pages.filter((record) => record.load_error).map((record) => ({ group: record.group, slug: record.slug, error: record.load_error })),
    render_health: pages.reduce((accumulator, record) => {
      const status = record.render_health?.status ?? 'unknown';
      accumulator[status] = (accumulator[status] ?? 0) + 1;
      return accumulator;
    }, {}),
    cdn: Object.fromEntries(
      ['tailwindcss', 'iconify-runtime', 'iconify-icon-data'].map((role) => {
        const entries = pages.flatMap((record) => record.cdn.filter((entry) => entry.role === role));
        return [
          role,
          {
            pages_checked: entries.length,
            loaded_pages: entries.filter((entry) => entry.loaded).length,
            failed_pages: entries.filter((entry) => entry.failed).length,
            statuses: [...new Set(entries.flatMap((entry) => (Array.isArray(entry.status) ? entry.status : entry.status === null ? [] : [entry.status])))],
          },
        ];
      }),
    ),
    horizontal_overflow_pages: pages
      .filter((record) => record.dom?.overflow.horizontal_overflow)
      .map((record) => `${record.group}/${record.slug}`),
    content_overflow_detail: pages
      .filter((record) => record.dom?.overflow.horizontal_overflow)
      .map((record) => ({
        page: `${record.group}/${record.slug}`,
        inner_width: record.dom.overflow.inner_width,
        body_scroll_width: record.dom.overflow.body_scroll_width,
        content_max_right: record.dom.overflow.content_max_right,
        content_max_element: record.dom.overflow.content_max_element,
        elements_beyond_viewport: record.dom.overflow.elements_beyond_viewport,
      })),
    off_canvas_pages: pages
      .map((record) => ({
        page: `${record.group}/${record.slug}`,
        off_canvas_count: record.dom?.overflow.off_canvas_count ?? 0,
        off_canvas: record.dom?.overflow.off_canvas ?? [],
        document_horizontal_overflow: record.dom?.overflow.document_horizontal_overflow ?? null,
      }))
      .filter((entry) => entry.off_canvas_count > 0),
    external_request_pages: pages
      .filter((record) => record.requests.external_total > 0)
      .map((record) => ({ page: `${record.group}/${record.slug}`, external: record.requests.external_total, failed: record.requests.external_failed })),
  };

  const inventory = {
    schema: 't09-d3-prototype-inventory/v1',
    generated_at: new Date().toISOString(),
    label: LABEL,
    task: 'T09-D3 阶段 1 · 原型只读渲染与截图取证',
    prototype_dir: toRepoPath(PROTOTYPE_DIR),
    base_url: baseUrl,
    browser: COMMAND_RECORD.browser,
    node: process.version,
    viewports: VIEWPORTS.map((viewport) => ({
      group: viewport.group,
      width: viewport.width,
      height: viewport.height,
      is_mobile: viewport.isMobile,
      has_touch: viewport.hasTouch,
      note: viewport.note,
    })),
    emulation_note:
      '截图使用 Playwright Chromium 普通视口（未启用 isMobile/deviceScaleFactor=1），与 D3 验收配置口径一致；' +
      '原型声明 min-w-[1120px] 且为桌面布局，390px 视口下横向溢出属原型自身事实，脚本如实记录而非伪造移动适配。',
    readonly_verification: {
      note: '五页原型 HTML 源码在截图前后各计算一次 SHA-256；unchanged=true 表示本轮未修改原型（只读）。',
      files: readonlyFiles,
      all_unchanged: readonlyUnchanged,
    },
    cdn_dependency: {
      note:
        '原型依赖墨刀 CDN 的 tailwindcss.js 与 iconify-icon.min.js，图标数据由 iconify 运行时向 api.iconify.design 拉取。' +
        '若 CDN 不可达，原型会降级为无样式 HTML；本文件按实际观测记录，不伪造渲染效果。',
      declared_urls: scanDeclaredExternalUrls(),
      judged_by: 'render_health.status：full=完整；degraded_*=降级（原因见 note）',
    },
    screenshots,
    pages,
    summary,
  };

  const inventoryPath = path.join(ACTUAL_ROOT, 'prototype-inventory.json');
  fs.writeFileSync(inventoryPath, `${JSON.stringify(inventory, null, 2)}\n`, 'utf8');
  logLine(`[write] ${toRepoPath(inventoryPath)}`);

  // 命令记录补充只读校验结论
  COMMAND_RECORD.html_sha256_after = Object.fromEntries(
    Object.entries(htmlAfter).map(([slug, entry]) => [slug, entry.sha256]),
  );
  COMMAND_RECORD.readonly_unchanged = readonlyUnchanged;
  COMMAND_RECORD.summary = {
    screenshots: summary.screenshots,
    console_errors_total: summary.console_errors_total,
    render_health: summary.render_health,
    readonly_unchanged: readonlyUnchanged,
  };

  logLine(
    `[done] screenshots=${summary.screenshots}/${summary.screenshots_expected} consoleErrors=${summary.console_errors_total} ` +
      `readonlyUnchanged=${readonlyUnchanged} renderHealth=${JSON.stringify(summary.render_health)} ` +
      `cdn=${JSON.stringify(summary.cdn)}`,
  );

  // 若原型被改动、截图缺失或页面加载失败，视为本轮证据不可用
  const failed = !readonlyUnchanged || summary.screenshots !== summary.screenshots_expected || summary.load_failures.length > 0;
  if (failed) {
    logErr(
      `[fail] readonly_unchanged=${readonlyUnchanged} screenshots=${summary.screenshots}/${summary.screenshots_expected} ` +
        `load_failures=${JSON.stringify(summary.load_failures)}`,
    );
  }
  finalizeAndExit(failed ? 1 : 0);
}

main().catch((error) => {
  logErr(`[fatal] ${error instanceof Error ? (error.stack ?? error.message) : String(error)}`);
  finalizeAndExit(1);
});
