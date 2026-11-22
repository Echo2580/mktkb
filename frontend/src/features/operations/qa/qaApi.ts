/**
 * T304 问答诊断页的只读接口封装。
 *
 * 仅封装 3 个 GET（详情 / 评测批次 / 单批次摘要），一律走 ``client.request``，
 * 不新增后端端点、不改 ``client.ts``。类型直接取 T302 生成的 ``schema.d.ts``。
 */
import type { components } from '../../../api/schema';
import { request } from '../../../api/client';

type Schemas = components['schemas'];

export type RequestListItem = Schemas['RequestListItem'];
export type RequestDetailResponse = Schemas['RequestDetailResponse'];
export type ResultBlock = Schemas['ResultBlock'];
export type CitationItem = Schemas['CitationItem'];
export type ConflictGroupItem = Schemas['ConflictGroupItem'];
export type ConflictEntryItem = Schemas['ConflictEntryItem'];
export type TraceBlock = Schemas['TraceBlock'];
export type TraceAttemptItem = Schemas['TraceAttemptItem'];
export type SpanSummary = Schemas['SpanSummary'];
export type EvaluationRunsResponse = Schemas['EvaluationRunsResponse'];
export type EvaluationRunItem = Schemas['EvaluationRunItem'];
export type RunResponse = Schemas['RunResponse'];
export type RunManifestSummary = Schemas['RunManifestSummary'];
export type RunSummaryBlock = Schemas['RunSummaryBlock'];
export type GateSummary = Schemas['GateSummary'];
export type HoldoutSummary = Schemas['HoldoutSummary'];

export const qaApi = {
  /** 单条问答诊断详情；仅返回服务端已关联的只读字段。 */
  getRequestDetail(requestId: string, signal?: AbortSignal): Promise<RequestDetailResponse> {
    return request<RequestDetailResponse>(`/operations/requests/${encodeURIComponent(requestId)}`, { signal });
  },

  /** 固定评测批次列表（白名单摘要；holdout 只回聚合）。 */
  listEvaluationRuns(signal?: AbortSignal): Promise<EvaluationRunsResponse> {
    return request<EvaluationRunsResponse>('/operations/evaluation-runs', { signal });
  },

  /** 单批次聚合摘要，复用现有 observability run 端点；不请求逐题。 */
  getEvaluationRun(runId: string, signal?: AbortSignal): Promise<RunResponse> {
    return request<RunResponse>(`/observability/runs/${encodeURIComponent(runId)}`, { signal });
  },
};
