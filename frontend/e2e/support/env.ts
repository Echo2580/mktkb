import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SUPPORT_DIR = path.dirname(fileURLToPath(import.meta.url));

export const FRONTEND_ROOT = path.resolve(SUPPORT_DIR, '../..');
export const PROJECT_ROOT = path.resolve(FRONTEND_ROOT, '..');
export const E2E_DATA_DIR = path.join(FRONTEND_ROOT, '.e2e-data');
export const AUTH_DIR = path.join(FRONTEND_ROOT, 'e2e', '.auth');
export const EVIDENCE_DIR = path.join(PROJECT_ROOT, 'docs', 'evidence', 'T08');
export const FIXTURES_DIR = path.join(PROJECT_ROOT, 'fixtures', 'acceptance');
export const PYTHON = path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe');
export const WORKER_SCRIPT = path.join(SUPPORT_DIR, 'worker_stub.py');

export const BASE_URL = process.env.T08_BASE_URL || 'http://127.0.0.1:5173';
export const BACKEND_URL = process.env.T08_BACKEND_ORIGIN || 'http://127.0.0.1:8077';

export const ADMIN = { username: 'admin', password: 'AdminPass-T08' };
export const EMPLOYEE = { username: 'employee', password: 'EmployeePass-T08' };

export const ADMIN_STATE = path.join(AUTH_DIR, 'admin.json');
export const EMPLOYEE_STATE = path.join(AUTH_DIR, 'employee.json');
export const SEED_FILE = path.join(AUTH_DIR, 'seed.json');

export const NORMAL = {
  positions: path.join(FIXTURES_DIR, 'normal', 'D01_物品位置表.xlsx'),
  contacts: path.join(FIXTURES_DIR, 'normal', 'D02_合作店家信息.xlsx'),
  guide: path.join(FIXTURES_DIR, 'normal', 'D03_市场部工作指南.docx'),
  materialsPdf: path.join(FIXTURES_DIR, 'normal', 'D05_物料领用规范.pdf'),
  storeGuidePdf: path.join(FIXTURES_DIR, 'normal', 'D06_店家资料维护说明.pdf'),
  eventPlan: path.join(FIXTURES_DIR, 'normal', 'D04_活动策划流程.docx'),
};

export const VARIANTS = {
  oldPositions: path.join(FIXTURES_DIR, 'variants', 'V03_物品位置表_历史V1.xlsx'),
  newContacts: path.join(FIXTURES_DIR, 'variants', 'V06_合作店家信息_新电话.xlsx'),
  contactNotice: path.join(FIXTURES_DIR, 'variants', 'V02_店家联系方式变更通知.pdf'),
  mixedScanPdf: path.join(FIXTURES_DIR, 'variants', 'A08_混合页含失败页文档.pdf'),
  corruptDocx: path.join(FIXTURES_DIR, 'variants', 'A01_损坏的文档.docx'),
};

export const MIME: Record<string, string> = {
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.pdf': 'application/pdf',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
};

export function mimeFor(filePath: string): string {
  return MIME[path.extname(filePath).toLowerCase()] ?? 'application/octet-stream';
}

export interface SeedDocument {
  id: string;
  versionId: string;
  name: string;
}

export interface SeedData {
  documents: Record<string, SeedDocument>;
  uploads: Record<string, string>;
}
