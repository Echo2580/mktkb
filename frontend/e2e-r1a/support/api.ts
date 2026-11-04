import fs from 'node:fs';
import path from 'node:path';
import { request, type APIRequestContext } from '@playwright/test';
import { ADMIN, BASE_URL, EMPLOYEE, mimeFor } from './env';

export interface ApiSession {
  ctx: APIRequestContext;
  csrf: string;
  role: 'admin' | 'employee';
}

export interface UploadReceipt {
  document: { id: string; name: string };
  version: { id: string; number: number; state: string };
  job: { id: string; state: string };
}

function headers(session: ApiSession): Record<string, string> {
  return { 'X-CSRF-Token': session.csrf };
}

export async function openSession(role: 'admin' | 'employee'): Promise<ApiSession> {
  const ctx = await request.newContext({
    baseURL: BASE_URL,
    extraHTTPHeaders: { Origin: BASE_URL },
  });
  const credentials = role === 'admin' ? ADMIN : EMPLOYEE;
  const response = await ctx.post('/api/v1/auth/login', { data: credentials });
  if (response.status() !== 200) {
    throw new Error(`登录失败 (${role})：HTTP ${response.status()} ${await response.text()}`);
  }
  const body = (await response.json()) as { csrf_token: string };
  return { ctx, csrf: body.csrf_token, role };
}

export async function uploadFile(
  session: ApiSession,
  filePath: string,
  displayName?: string,
  options: { allowSameName?: boolean; documentId?: string; expectedActiveVersionId?: string | null } = {},
): Promise<UploadReceipt> {
  const name = displayName ?? path.basename(filePath);
  const multipart: Record<string, string | { name: string; mimeType: string; buffer: Buffer }> = {
    file: { name, mimeType: mimeFor(name), buffer: fs.readFileSync(filePath) },
  };
  if (options.allowSameName) multipart.allow_same_name = 'true';
  if (options.expectedActiveVersionId) multipart.expected_active_version_id = options.expectedActiveVersionId;
  const url = options.documentId ? `/api/v1/documents/${options.documentId}/versions` : '/api/v1/documents';
  const response = await session.ctx.post(url, { multipart, headers: headers(session) });
  if (response.status() !== 202) {
    throw new Error(`上传失败 ${name}：HTTP ${response.status()} ${await response.text()}`);
  }
  return (await response.json()) as UploadReceipt;
}

export async function getDocument(session: ApiSession, documentId: string): Promise<Record<string, unknown>> {
  const response = await session.ctx.get(`/api/v1/documents/${documentId}`);
  if (response.status() !== 200) {
    throw new Error(`读取资料失败：HTTP ${response.status()} ${await response.text()}`);
  }
  return (await response.json()) as Record<string, unknown>;
}

export async function publishVersion(
  session: ApiSession,
  documentId: string,
  versionId: string,
  expectedRevision: number,
  expectedActiveVersionId: string | null,
): Promise<void> {
  const response = await session.ctx.post(`/api/v1/documents/${documentId}/versions/${versionId}/publish`, {
    data: {
      expected_active_version_id: expectedActiveVersionId,
      expected_revision: expectedRevision,
    },
    headers: headers(session),
  });
  if (response.status() !== 200) {
    throw new Error(`发布失败：HTTP ${response.status()} ${await response.text()}`);
  }
}

export async function publishReceipt(session: ApiSession, receipt: UploadReceipt): Promise<void> {
  const detail = (await getDocument(session, receipt.document.id)) as unknown as {
    revision: number;
    document: { active_version: { id: string } | null };
  };
  await publishVersion(
    session,
    receipt.document.id,
    receipt.version.id,
    detail.revision,
    detail.document.active_version?.id ?? null,
  );
}

export async function deleteDocument(session: ApiSession, documentId: string, expectedRevision: number): Promise<void> {
  const response = await session.ctx.delete(`/api/v1/documents/${documentId}?expected_revision=${expectedRevision}`, {
    headers: headers(session),
  });
  if (response.status() !== 200) {
    throw new Error(`删除失败：HTTP ${response.status()} ${await response.text()}`);
  }
}

export async function getRevision(session: ApiSession, documentId: string): Promise<number> {
  const detail = (await getDocument(session, documentId)) as unknown as { revision: number };
  return detail.revision;
}

export async function findDocumentByName(session: ApiSession, name: string): Promise<Record<string, unknown> | null> {
  const response = await session.ctx.get(`/api/v1/documents?q=${encodeURIComponent(name)}&limit=100`);
  if (response.status() !== 200) {
    throw new Error(`查询资料失败：HTTP ${response.status()} ${await response.text()}`);
  }
  const body = (await response.json()) as { items: Array<Record<string, unknown>> };
  return body.items.find((item) => item.name === name) ?? null;
}

export async function closeSession(session: ApiSession): Promise<void> {
  await session.ctx.dispose();
}
