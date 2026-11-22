/**
 * T305 知识资产页只读数据访问。
 * - 列表复用 client.ts 的 api.operationsDocuments（冻结文件，不在此改写）；
 * - 文档详情直接走契约端点 GET /api/v1/operations/documents/{document_id}，
 *   因为 T302 的列表契约没有 document_id/version_id 过滤参数，也不返回最新版本状态。
 * - 全部只读 GET；本文件不含任何写操作。
 */
import { api, request } from '../../../api/client';
import type { OperationsDocumentsPage, OperationsQuery, Schema } from '../../../api/client';

export type DocumentItem = Schema['DocumentListItem'];
export type AssetDetail = Schema['DocumentDetailResponse'];
export type AssetVersion = Schema['VersionDetail'];
export type AssetImport = Schema['ImportDetail'];
export type DocumentVersionSummary = Schema['DocumentVersionSummary'];

/** 与 T303 占位页一致的游标累计上限；超过即标注可能不完整。 */
export const MAX_PAGES = 20;
const PAGE_SIZE = 20;
const DETAIL_CONCURRENCY = 6;

export interface DocumentsQuery extends OperationsQuery {
  fileType?: string;
  versionState?: string;
  processingState?: string;
}

export interface DocumentsBatch {
  items: DocumentItem[];
  pages: number;
  truncated: boolean;
}

/** 按 next_cursor 累计所有页（上限 MAX_PAGES），用于筛选下总数与列表展示。 */
export async function loadAllDocuments(query: DocumentsQuery): Promise<DocumentsBatch> {
  const items: DocumentItem[] = [];
  let cursor: string | null = null;
  let pages = 0;
  let truncated = false;
  do {
    const page: OperationsDocumentsPage = await api.operationsDocuments({
      window: query.window,
      since: query.since,
      until: query.until,
      fileType: query.fileType,
      versionState: query.versionState,
      processingState: query.processingState,
      cursor: cursor ?? undefined,
      pageSize: PAGE_SIZE,
    });
    items.push(...(page.items ?? []));
    pages += 1;
    cursor = page.next_cursor ?? null;
    if (cursor && pages >= MAX_PAGES) {
      truncated = true;
      break;
    }
  } while (cursor);
  return { items, pages, truncated };
}

/** 文档详情：版本、导入摘要与下钻条件（失败原因已由后端脱敏）。 */
export function loadDocumentDetail(documentId: string): Promise<AssetDetail> {
  return request<AssetDetail>(`/operations/documents/${encodeURIComponent(documentId)}`);
}

/**
 * 逐份补齐详情（受控并发）。列表契约未返回最新版本状态/版本号，
 * 本页在只读范围内用详情端点补齐；单份失败只影响该行标注，不阻断页面。
 */
export async function loadDocumentDetails(
  items: DocumentItem[],
  cache: Map<string, AssetDetail>,
): Promise<Map<string, AssetDetail | null>> {
  const result = new Map<string, AssetDetail | null>();
  for (const item of items) {
    if (cache.has(item.document_id)) {
      result.set(item.document_id, cache.get(item.document_id) ?? null);
    }
  }
  const missing = items.filter((item) => !result.has(item.document_id));
  for (let index = 0; index < missing.length; index += DETAIL_CONCURRENCY) {
    const chunk = missing.slice(index, index + DETAIL_CONCURRENCY);
    await Promise.all(
      chunk.map(async (item) => {
        try {
          const detail = await loadDocumentDetail(item.document_id);
          cache.set(item.document_id, detail);
          result.set(item.document_id, detail);
        } catch {
          result.set(item.document_id, null);
        }
      }),
    );
  }
  return result;
}
