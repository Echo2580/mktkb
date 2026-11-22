/**
 * 执行阶段条：只渲染 T301 冻结映射内**实际记录**的 Span。
 * 未记录 ≠ 0ms：缺失阶段不补齐、不按结果类型虚构；合计只统计已记录的时长。
 */
import type { SpanSummary, TraceAttemptItem } from './qaApi';
import { formatDuration, shortId } from './qaMeta';
import {
  isChildSpan,
  isMappedSpan,
  pathLabel,
  stageDefs,
  stageFamily,
  traceStatusLabel,
  type StageDef,
} from './spanLabels';

interface StageRow {
  def: StageDef;
  span: SpanSummary;
}

function indexSpans(spans: SpanSummary[]): Map<string, SpanSummary> {
  const map = new Map<string, SpanSummary>();
  for (const span of spans) {
    if (typeof span.name === 'string' && span.name && !map.has(span.name)) {
      map.set(span.name, span);
    }
  }
  return map;
}

function durationOf(span: SpanSummary): number | null {
  return typeof span.duration_ms === 'number' && Number.isFinite(span.duration_ms) ? span.duration_ms : null;
}

export function StageBars({ attempt }: { attempt: TraceAttemptItem }) {
  const spans = attempt.spans ?? [];
  const family = stageFamily(attempt.path);
  const defs = stageDefs(family);
  const indexed = indexSpans(spans);
  const rows: StageRow[] = defs
    .filter((def) => indexed.has(def.span))
    .map((def) => ({ def, span: indexed.get(def.span)! }));
  const recorded = rows.filter((row) => durationOf(row.span) !== null);
  const recordedTotal = recorded.reduce((sum, row) => sum + (durationOf(row.span) ?? 0), 0);
  const detailSpans = spans.filter(
    (span) => typeof span.name === 'string' && span.name && isChildSpan(span.name),
  );
  const unmappedSpans = spans.filter(
    (span) => typeof span.name === 'string' && span.name && !isMappedSpan(family, span.name),
  );

  return (
    <div className="qa-stage-block">
      {attempt.replayed && spans.length === 0 ? (
        <p className="qa-stage-empty" data-testid="qa-stage-replay">
          重放请求未记录执行阶段（幂等重放不产生新 Span）。
        </p>
      ) : null}

      {family === null ? (
        <p className="qa-stage-empty" data-testid="qa-stage-nopath">
          路径未记录，无法按冻结映射展示阶段；原始 Span 见下方细节。
        </p>
      ) : rows.length === 0 && spans.length > 0 ? (
        <p className="qa-stage-empty" data-testid="qa-stage-none">
          本次尝试未记录映射内主阶段，不补齐、不推测耗时。
        </p>
      ) : null}

      {rows.length > 0 ? (
        <div className="qa-stages" data-testid="qa-stages">
          {rows.map((row) => {
            const duration = durationOf(row.span);
            const share = duration !== null && recordedTotal > 0 ? Math.max((duration / recordedTotal) * 100, 1) : 0;
            const failed = row.span.status === 'error';
            return (
              <div
                key={`${attempt.trace_id ?? 'trace'}-${row.def.span}`}
                className={`qa-stage-row${failed ? ' is-error' : ''}`}
                data-stage={row.def.span}
                data-status={row.span.status ?? ''}
              >
                <span className="qa-stage-label">{row.def.label}</span>
                <span className="qa-stage-track" aria-hidden="true">
                  {share > 0 ? <span className="qa-stage-bar" style={{ width: `${share}%` }} /> : null}
                </span>
                <span className="qa-stage-value">{formatDuration(duration)}</span>
                {row.span.error_code ? <span className="qa-stage-error">{row.span.error_code}</span> : null}
              </div>
            );
          })}
        </div>
      ) : null}

      {rows.length > 0 && recorded.length > 0 ? (
        <p className="qa-stage-sum" data-testid="qa-stage-sum">
          已记录阶段合计 {recordedTotal} ms
          {recorded.length < rows.length ? `（${rows.length - recorded.length} 个阶段未记录时长，不计入）` : ''}
        </p>
      ) : null}

      {detailSpans.length > 0 || unmappedSpans.length > 0 ? (
        <details className="qa-stage-details" data-testid="qa-stage-details">
          <summary>
            展开细节（子 Span {detailSpans.length + unmappedSpans.length} 个）
          </summary>
          <ul className="qa-span-list">
            {[...detailSpans, ...unmappedSpans].map((span, index) => (
              <li key={`${span.span_id ?? span.name ?? 'span'}-${index}`} className="qa-span-item">
                <span className="qa-span-name">{span.name}</span>
                {unmappedSpans.includes(span) ? <span className="qa-span-note">未在冻结映射内</span> : null}
                <span className="qa-span-meta">{formatDuration(span.duration_ms)}</span>
                <span className="qa-span-meta">状态 {span.status ?? '未记录'}</span>
                {span.error_code ? <span className="qa-span-error">{span.error_code}</span> : null}
                {(span.attribute_count ?? 0) > 0 ? <span className="qa-span-meta">属性 {span.attribute_count} 项</span> : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

export function AttemptList({ attempts }: { attempts: TraceAttemptItem[] }) {
  return (
    <div className="qa-attempts" data-testid="qa-attempts">
      {attempts.map((attempt, index) => (
        <section
          key={attempt.trace_id ?? `attempt-${attempt.attempt}-${index}`}
          className="qa-attempt"
          data-attempt={attempt.attempt}
          data-replayed={attempt.replayed ? 'true' : 'false'}
        >
          <header className="qa-attempt-head">
            <span className="qa-attempt-index">尝试 {attempt.attempt}</span>
            <span className="qa-path-chip">{pathLabel(attempt.path)}</span>
            {attempt.replayed ? <span className="qa-badge is-warn">重放</span> : null}
            {attempt.outcome ? <span className="qa-attempt-meta">结局 {attempt.outcome}</span> : null}
            <span className="qa-attempt-meta">状态 {traceStatusLabel(attempt.status)}</span>
            {attempt.error_code ? <span className="qa-attempt-error">{attempt.error_code}</span> : null}
            {attempt.trace_id ? <span className="qa-attempt-trace">Trace {shortId(attempt.trace_id)}</span> : null}
          </header>
          <StageBars attempt={attempt} />
        </section>
      ))}
    </div>
  );
}
