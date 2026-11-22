/**
 * T304 执行阶段标签映射（T301-data-audit §4 冻结表，不得增删）。
 *
 * 页面只渲染映射内**实际记录**的 Span：未记录 ≠ 0ms，不补阶段、不按结果类型虚构。
 * ``legacy_with_rag_candidates`` 与 ``legacy`` 共用 legacy 规则。
 */
export type StageFamily = 'rag' | 'legacy';

export interface StageDef {
  span: string;
  label: string;
  /** 条件 Span：实际存在才渲染，缺失不报缺。 */
  conditional: boolean;
}

const RAG_STAGES: StageDef[] = [
  { span: 'parse', label: '解析计划', conditional: false },
  { span: 'recall', label: '检索召回', conditional: false },
  { span: 'vector_recall', label: '向量召回', conditional: true },
  { span: 'fuse', label: '融合排序', conditional: false },
  { span: 'rerank', label: '重排', conditional: true },
  { span: 'answer', label: '答案生成', conditional: false },
  { span: 'index_sync', label: '索引同步', conditional: true },
  { span: 'commit', label: '状态持久化', conditional: false },
];

const LEGACY_STAGES: StageDef[] = [
  { span: 'intent_parse', label: '意图解析', conditional: false },
  { span: 'retrieve', label: '证据检索', conditional: false },
  { span: 'query_expansion', label: '查询扩展', conditional: true },
  { span: 'model_answer', label: '模型作答', conditional: false },
  { span: 'answer_validate', label: '答案校验', conditional: false },
  { span: 'commit', label: '结果提交', conditional: false },
];

/** 子 Span：不进主阶段条，只在「展开细节」折叠区展示。 */
export const CHILD_SPANS = new Set([
  'exact_recall',
  'lexical_recall',
  'embedding_query',
  'hard_filter',
  'fact_validate',
  'entity_conflict_check',
  'model_failure',
]);

export function stageFamily(path?: string | null): StageFamily | null {
  if (path === 'rag') return 'rag';
  if (path === 'legacy' || path === 'legacy_with_rag_candidates') return 'legacy';
  return null;
}

export function stageDefs(family: StageFamily | null): StageDef[] {
  if (family === 'rag') return RAG_STAGES;
  if (family === 'legacy') return LEGACY_STAGES;
  return [];
}

/** 冻结映射内的阶段（含条件 Span与子 Span）。 */
export function isMappedSpan(family: StageFamily | null, name: string): boolean {
  if (family === null) return false;
  return stageDefs(family).some((item) => item.span === name) || CHILD_SPANS.has(name);
}

export function stageLabel(path: string | null | undefined, name: string): string | null {
  const family = stageFamily(path);
  if (family === null) return null;
  return stageDefs(family).find((item) => item.span === name)?.label ?? null;
}

export function isChildSpan(name: string): boolean {
  return CHILD_SPANS.has(name);
}

export function pathLabel(path?: string | null): string {
  if (path === 'rag') return 'RAG 路径';
  if (path === 'legacy') return 'legacy 路径';
  if (path === 'legacy_with_rag_candidates') return 'legacy 路径（含 RAG 候选）';
  return '路径未记录';
}

export function traceStatusLabel(status?: string | null): string {
  switch (status) {
    case 'ok':
      return '正常';
    case 'error':
      return '执行失败';
    case 'incomplete':
      return '记录不完整';
    case 'replayed':
      return '重放';
    default:
      return status ? `状态 ${status}` : '状态未记录';
  }
}
