/**
 * T303 运营页筛选的唯一实现：URL 读写、窗口换算、下钻跳转与接口参数序列化。
 * 图表点击、键盘等价入口与日期切换器都必须调用本文件的函数，禁止各自拼参数。
 */
export const RESULT_KINDS = [
  'answer',
  'clarification',
  'not_found',
  'conflict',
  'service_error',
  'knowledge_changed',
] as const;

export type ResultKind = (typeof RESULT_KINDS)[number];

export const RESULT_LABELS: Record<ResultKind, string> = {
  answer: '已答复',
  clarification: '澄清追问',
  not_found: '未找到',
  conflict: '资料冲突',
  service_error: '服务异常',
  knowledge_changed: '知识变更',
};

export const WINDOW_KEYS = ['today', '7d', '30d', 'custom'] as const;
export type WindowKey = (typeof WINDOW_KEYS)[number];
export const WINDOW_LABELS: Record<WindowKey, string> = {
  today: '今日',
  '7d': '近 7 天',
  '30d': '近 30 天',
  custom: '自定义',
};

export const MAX_WINDOW_DAYS = 90;
export const DEFAULT_WINDOW: WindowKey = '7d';

export interface OperationsFilters {
  window: WindowKey;
  since: string;
  until: string;
  kind: string;
  documentId: string;
  versionId: string;
  state: string;
}

function isWindowKey(value: string | null): value is WindowKey {
  return value !== null && (WINDOW_KEYS as readonly string[]).includes(value);
}

/** 只接受后端同款 YYYY-MM-DD；非法值一律当空，避免把脏参数发给接口。 */
export function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function readFilters(params: URLSearchParams): OperationsFilters {
  const rawWindow = params.get('window');
  let windowKey: WindowKey = isWindowKey(rawWindow) ? rawWindow : DEFAULT_WINDOW;
  const since = params.get('since') ?? '';
  const until = params.get('until') ?? '';
  if (!isWindowKey(rawWindow) && (since || until)) windowKey = 'custom';
  return {
    window: windowKey,
    since: isIsoDate(since) ? since : '',
    until: isIsoDate(until) ? until : '',
    kind: params.get('kind') ?? '',
    documentId: params.get('document_id') ?? '',
    versionId: params.get('version_id') ?? '',
    state: params.get('state') ?? '',
  };
}

/** 筛选 → URLSearchParams；空值不写，保证 URL 可读且刷新可恢复。 */
export function toSearchParams(filters: OperationsFilters): URLSearchParams {
  const params = new URLSearchParams();
  params.set('window', filters.window);
  if (filters.window === 'custom' || filters.since || filters.until) {
    if (filters.since) params.set('since', filters.since);
    if (filters.until) params.set('until', filters.until);
  }
  if (filters.kind) params.set('kind', filters.kind);
  if (filters.documentId) params.set('document_id', filters.documentId);
  if (filters.versionId) params.set('version_id', filters.versionId);
  if (filters.state) params.set('state', filters.state);
  return params;
}

export function toSearch(filters: OperationsFilters): string {
  return toSearchParams(filters).toString();
}

/** 本地“今天”按 Asia/Shanghai 计，不使用运行机器的时区。 */
export function todayInShanghai(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now);
  return parts;
}

export function addDays(isoDate: string, delta: number): string {
  const base = new Date(`${isoDate}T00:00:00Z`);
  base.setUTCDate(base.getUTCDate() + delta);
  return base.toISOString().slice(0, 10);
}

export interface ResolvedWindow {
  since: string;
  until: string;
  error?: string;
}

/** 把 window 预设换算成含首尾的日期；自定义窗口做必填/顺序/90 天校验。 */
export function resolveWindow(filters: OperationsFilters, today: string = todayInShanghai()): ResolvedWindow {
  if (filters.window === 'custom' || filters.since || filters.until) {
    if (!filters.since || !filters.until) {
      return { since: filters.since, until: filters.until, error: '自定义窗口需要同时选择开始和结束日期' };
    }
    if (!isIsoDate(filters.since) || !isIsoDate(filters.until)) {
      return { since: filters.since, until: filters.until, error: '日期格式必须为 YYYY-MM-DD' };
    }
    if (filters.since > filters.until) {
      return { since: filters.since, until: filters.until, error: '开始日期不能晚于结束日期' };
    }
    const span = (Date.parse(`${filters.until}T00:00:00Z`) - Date.parse(`${filters.since}T00:00:00Z`)) / 86400000 + 1;
    if (span > MAX_WINDOW_DAYS) {
      return { since: filters.since, until: filters.until, error: `窗口最多 ${MAX_WINDOW_DAYS} 天，请缩小日期范围` };
    }
    return { since: filters.since, until: filters.until };
  }
  if (filters.window === 'today') return { since: today, until: today };
  if (filters.window === '30d') return { since: addDays(today, -29), until: today };
  return { since: addDays(today, -6), until: today };
}

export function windowLabel(filters: OperationsFilters, today: string = todayInShanghai()): string {
  const resolved = resolveWindow(filters, today);
  if (resolved.error) return resolved.error;
  return `${WINDOW_LABELS[filters.window]} · ${resolved.since} 至 ${resolved.until}（Asia/Shanghai）`;
}

/** 日期切换器：保留 kind/document_id/version_id/state，切换窗口与自定义日期。 */
export function applyWindow(
  filters: OperationsFilters,
  window: WindowKey,
  dates: { since?: string; until?: string } = {},
): OperationsFilters {
  const next: OperationsFilters = { ...filters, window };
  if (window === 'custom') {
    next.since = dates.since ?? filters.since;
    next.until = dates.until ?? filters.until;
  } else {
    next.since = '';
    next.until = '';
  }
  return next;
}

/** 趋势图某天：写 custom + since=until=该日，并跳问答诊断占位页。 */
export function drillToDay(filters: OperationsFilters, day: string): OperationsFilters {
  return { ...filters, window: 'custom', since: day, until: day };
}

export function drillToKind(filters: OperationsFilters, kind: string): OperationsFilters {
  return { ...filters, kind };
}

export function requestsPath(filters: OperationsFilters): string {
  return `/operations/requests?${toSearch(filters)}`;
}

export function documentsPath(filters: OperationsFilters): string {
  return `/operations/documents?${toSearch(filters)}`;
}

export type OverviewQuery = {
  window: WindowKey;
  since?: string;
  until?: string;
};

/** 总览/占位统一从这里取窗口参数；自定义只发 since/until，预设只发 window。 */
export function overviewQuery(filters: OperationsFilters, today: string = todayInShanghai()): OverviewQuery {
  const resolved = resolveWindow(filters, today);
  if (filters.window === 'custom' || filters.since || filters.until) {
    return { window: 'custom', since: resolved.since, until: resolved.until };
  }
  return { window: filters.window };
}

/** T302 的 documents 列表把状态拆成版本态/导入态；URL 只有一个 state，这里做显式映射。 */
export type DocumentStateMapping = { versionState?: string; processingState?: string };

const VERSION_STATES = new Set(['queued', 'processing', 'review_required', 'published', 'superseded', 'cancelled']);
const PROCESSING_STATES = new Set(['failed', 'blocked', 'succeeded']);

export function mapDocumentState(state: string): DocumentStateMapping {
  if (!state) return {};
  if (VERSION_STATES.has(state)) return { versionState: state };
  if (PROCESSING_STATES.has(state)) return { processingState: state };
  return { versionState: state };
}
