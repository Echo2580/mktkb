const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

const timeFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return dateTimeFormatter.format(date).replace(/\//g, '-');
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return timeFormatter.format(date);
}

export function formatDay(value: string | null | undefined): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: 'numeric',
    day: 'numeric',
  }).formatToParts(date);
  const month = parts.find((part) => part.type === 'month')?.value ?? '';
  const day = parts.find((part) => part.type === 'day')?.value ?? '';
  if (!month || !day) return '';
  return `${month} 月 ${day} 日`;
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (bytes >= 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  return `${bytes} B`;
}

export const VERSION_STATE_LABELS: Record<string, string> = {
  queued: '等待处理',
  processing: '处理中',
  review_required: '待确认',
  failed: '处理失败',
  published: '已生效',
  superseded: '已被替换',
  cancelled: '已取消',
  deleted: '已删除',
};

export const JOB_STATE_LABELS: Record<string, string> = {
  queued: '等待处理',
  running: '处理中',
  succeeded: '处理完成',
  failed: '处理失败',
  blocked: '已阻塞',
  cancelled: '已取消',
};

export const SOURCE_STATUS_LABELS: Record<string, string> = {
  active: '已发布',
  superseded: '已被替换',
  deleted: '已删除',
};

export type Tone = 'emerald' | 'amber' | 'rose' | 'blue' | 'slate' | 'violet';

export function versionTone(state: string | null | undefined): Tone {
  switch (state) {
    case 'published':
      return 'emerald';
    case 'review_required':
      return 'amber';
    case 'failed':
      return 'rose';
    case 'processing':
      return 'blue';
    default:
      return 'slate';
  }
}

export function jobTone(state: string | null | undefined): Tone {
  switch (state) {
    case 'succeeded':
      return 'emerald';
    case 'failed':
    case 'blocked':
      return 'rose';
    case 'running':
      return 'blue';
    default:
      return 'slate';
  }
}

const LOCATOR_LABELS: Record<string, string> = {
  sheet: '工作表',
  row: '原始行号',
  header_row: '表头行',
  heading: '所属标题',
  paragraph: '段落',
  page: '页码',
  bbox: '区域',
  style: '段落样式',
  table: '表格',
  column: '列',
};

const LOCATOR_SKIP_KEYS = new Set(['cells', 'cell_types']);

export function locatorParts(locator: Record<string, unknown> | null | undefined): Array<{ key: string; label: string; value: string }> {
  if (!locator) return [];
  const parts: Array<{ key: string; label: string; value: string }> = [];
  for (const [key, raw] of Object.entries(locator)) {
    if (raw === null || raw === undefined || raw === '') continue;
    // cells/cell_types 是解析器内部单元格元数据，不是可读定位；避免把 [object Object] 展示给用户。
    if (LOCATOR_SKIP_KEYS.has(key)) continue;
    if (typeof raw === 'object' && !Array.isArray(raw)) continue;
    if (Array.isArray(raw) && raw.some((item) => typeof item === 'object' && item !== null)) continue;
    let display: string;
    if (Array.isArray(raw)) {
      display = raw.map((item) => String(item)).join(', ');
    } else {
      display = String(raw);
    }
    parts.push({ key, label: LOCATOR_LABELS[key] ?? key, value: display });
  }
  return parts;
}

export function locatorSummary(locator: Record<string, unknown> | null | undefined): string {
  const parts = locatorParts(locator);
  if (parts.length === 0) return '未提供定位信息';
  return parts
    .map((part) => {
      if (part.key === 'row') return `第 ${part.value} 行`;
      if (part.key === 'page') return `第 ${part.value} 页`;
      if (part.key === 'paragraph') return `第 ${part.value} 段`;
      return `${part.label}：${part.value}`;
    })
    .join(' · ');
}

export const RESULT_KIND_LABELS: Record<string, string> = {
  answer: '基于已发布资料',
  clarification: '需要确认',
  not_found: '无匹配资料',
  conflict: '资料记载不一致',
  service_error: '服务暂不可用',
  knowledge_changed: '资料已更新',
};

export function resultKindTone(kind: string | null | undefined): Tone {
  switch (kind) {
    case 'answer':
      return 'emerald';
    case 'clarification':
    case 'conflict':
      return 'amber';
    case 'service_error':
      return 'rose';
    case 'knowledge_changed':
      return 'blue';
    default:
      return 'slate';
  }
}

export const FILE_TYPE_LABELS: Record<string, string> = {
  xlsx: 'Excel',
  docx: 'Word',
  pdf: 'PDF',
  png: '图片',
  jpg: '图片',
  jpeg: '图片',
};

export function truncateMiddle(value: string, head = 8, tail = 6): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}
