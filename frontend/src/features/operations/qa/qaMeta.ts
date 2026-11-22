/**
 * T304 页面文案与派生逻辑（结果类型元信息、时间格式、评测状态、降级说明）。
 * 文案对齐原型 qa-diagnosis.html 的 TYPE_META，去掉了原型中「由管理员发起」等演示语义。
 */
import type { EvaluationRunItem } from './qaApi';

export type KindTone = 'answer' | 'clarify' | 'notfound' | 'conflict' | 'error' | 'changed' | 'muted';

export interface KindMeta {
  label: string;
  tone: KindTone;
  note: string;
}

/** 六类结果的中文标签与说明；未知/缺失结果不猜类型。 */
export const KIND_META: Record<string, KindMeta> = {
  answer: { label: '已回答', tone: 'answer', note: '已基于当前生效资料返回答案，未触发澄清或冲突。' },
  clarification: { label: '需澄清', tone: 'clarify', note: '问题缺少关键条件（如门店、产品），系统未直接给出答案。' },
  not_found: { label: '未找到', tone: 'notfound', note: '当前已发布资料中未检索到匹配内容，回答不附带来源。' },
  conflict: { label: '资料冲突', tone: 'conflict', note: '两份当前有效资料记载不一致，系统未自动判定哪一份正确。' },
  service_error: { label: '服务异常', tone: 'error', note: '请求失败，未生成回答；不代表资料中没有答案。' },
  knowledge_changed: { label: '知识已变更', tone: 'changed', note: '回答生成后引用资料发生版本更新，原回答已标记失效。' },
};

export function kindMeta(kind?: string | null): KindMeta {
  if (kind && KIND_META[kind]) return KIND_META[kind];
  return { label: '结果未记录', tone: 'muted', note: '该请求未记录结果类型，按接口原始状态展示。' };
}

function shanghaiParts(value: Date): Record<string, string> {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(value);
  return parts.reduce<Record<string, string>>((acc, part) => {
    if (part.type !== 'literal') acc[part.type] = part.value;
    return acc;
  }, {});
}

/** 列表/详情统一按 Asia/Shanghai 显示 MM-dd HH:mm。 */
export function formatMoment(value?: string | null): string {
  if (!value) return '时间未记录';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const parts = shanghaiParts(parsed);
  return `${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
}

export function formatYmdHm(value?: string | null): string {
  if (!value) return '时间未记录';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const parts = shanghaiParts(parsed);
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
}

export function shortId(value?: string | null): string {
  if (!value) return '';
  return value.length > 8 ? `${value.slice(0, 8)}…` : value;
}

export function isDemoEnvironment(): boolean {
  if (typeof window === 'undefined') return false;
  return window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost';
}

export interface DocumentStateMeta {
  label: string;
  tone: 'active' | 'superseded' | 'deleted';
}

/** 引用版本当前状态；只有 active 才展示定位。 */
export function citationState(status?: string | null): DocumentStateMeta {
  if (status === 'active') return { label: '当前有效', tone: 'active' };
  if (status === 'deleted') return { label: '已删除', tone: 'deleted' };
  return { label: '已被替换', tone: 'superseded' };
}

/** locator 只渲染扁平可读键值；不展示 ``cells`` 行快照（T302 已剔除，前端再兜一层）。 */
export function locatorText(locator?: Record<string, unknown> | null): string {
  if (!locator) return '';
  const parts: string[] = [];
  for (const [key, value] of Object.entries(locator)) {
    if (key === 'cells') continue;
    if (value === null || value === undefined) continue;
    if (typeof value === 'object') continue;
    parts.push(`${key} ${String(value)}`);
  }
  return parts.join(' · ');
}

export function formatDuration(ms?: number | null): string {
  if (typeof ms !== 'number' || Number.isNaN(ms)) return '时长未记录';
  return `${ms} ms`;
}

export type EvalTone = 'pending' | 'failed' | 'done';

export interface EvalStatus {
  label: string;
  tone: EvalTone;
  detail: string;
}

const GATE_FAIL_VALUES = new Set(['fail', 'failed', 'error', 'blocked', 'hard_fail']);

function gateFailed(item: EvaluationRunItem): boolean {
  const gate = item.gate;
  if (!gate) return false;
  if (typeof gate.failure_count === 'number' && gate.failure_count > 0) return true;
  if (typeof gate.exit_code === 'number' && gate.exit_code !== 0) return true;
  const quality = (gate.quality_status ?? '').toLowerCase();
  if (GATE_FAIL_VALUES.has(quality)) return true;
  return Object.values(gate.gate_status ?? {}).some((value) =>
    GATE_FAIL_VALUES.has(String(value).toLowerCase()),
  );
}

function firstMetrics(summary: EvaluationRunItem['summary']): string {
  const metrics = summary?.metrics ?? {};
  const entries = Object.entries(metrics)
    .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
    .slice(0, 2);
  if (entries.length === 0) return '指标无样本';
  return entries.map(([key, value]) => `${key} ${Number(value)}`).join(' · ');
}

/**
 * 评测状态派生：无执行记录 → 未评测；有错误样本或门禁失败 → 评测失败；
 * 其余正常完成 → 已完成。任何分数都不标为业务正确率。
 */
export function evalStatusOf(item: EvaluationRunItem): EvalStatus {
  const summary = item.summary;
  const scored = summary?.scored_count ?? null;
  const errors = summary?.error_count ?? null;
  if (!summary || ((scored ?? 0) === 0 && (errors ?? 0) === 0)) {
    return { label: '未评测', tone: 'pending', detail: '批次尚无执行记录' };
  }
  const failed = (errors ?? 0) > 0 || gateFailed(item);
  if (failed) {
    const gateFailures = item.gate?.failure_count ?? 0;
    const detailParts: string[] = [];
    if ((errors ?? 0) > 0) detailParts.push(`失败样本 ${errors}`);
    if (gateFailures > 0) detailParts.push(`门禁失败 ${gateFailures}`);
    if (detailParts.length === 0) detailParts.push('门禁状态未通过');
    return { label: '评测失败', tone: 'failed', detail: detailParts.join(' · ') };
  }
  const caseCount = item.manifest?.case_count ?? summary.case_count ?? null;
  const scoredText = `已评分 ${scored ?? 0}${caseCount !== null ? `/${caseCount}` : ''}`;
  return { label: '已完成', tone: 'done', detail: `${scoredText} · ${firstMetrics(summary)}` };
}

const DEGRADED_LABELS: Record<string, string> = {
  manifest_invalid: 'manifest 解析失败，仅部分字段可见',
  summary_invalid: 'summary 解析失败，评测状态按缺失处理',
  gate_invalid: 'gate 解析失败，门禁状态未知',
  trace_disabled: '该批次读取时 Trace 已关闭，仅聚合结果可见',
  trace_unavailable: '该批次读取时 Trace 暂不可用',
};

export function degradedText(reason?: string | null): string {
  if (!reason) return '';
  return DEGRADED_LABELS[reason] ?? `降级原因：${reason}`;
}
