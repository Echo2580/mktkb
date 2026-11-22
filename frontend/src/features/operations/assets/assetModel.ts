/**
 * T305 资产页展示口径（纯函数，无副作用）。
 * 红线：当前生效版本只认 state='published' 的生效版本；不把最新版当生效版展示。
 */
import type { AssetDetail, AssetImport, AssetVersion, DocumentItem, DocumentVersionSummary } from './assetsApi';

export interface FileTypeMeta {
  label: string;
  tile: string;
  icon: string;
}

const FILE_TYPES: Record<string, FileTypeMeta> = {
  xlsx: { label: 'Excel', tile: 'tile-emerald', icon: 'file-spreadsheet' },
  docx: { label: 'Word', tile: 'tile-blue', icon: 'file-text' },
  pdf: { label: 'PDF', tile: 'tile-rose', icon: 'file-type-2' },
  png: { label: '图片', tile: 'tile-violet', icon: 'image' },
  jpg: { label: '图片', tile: 'tile-violet', icon: 'image' },
  jpeg: { label: '图片', tile: 'tile-violet', icon: 'image' },
};

export const IMAGE_FILE_TYPES = ['png', 'jpg', 'jpeg'];

export function fileTypeMeta(fileType?: string | null): FileTypeMeta {
  return (fileType && FILE_TYPES[fileType]) || { label: '文件', tile: 'tile-slate', icon: 'file-text' };
}

export const FILE_TYPE_FILTERS = [
  { value: '', label: '全部类型' },
  { value: 'xlsx', label: 'Excel' },
  { value: 'docx', label: 'Word' },
  { value: 'pdf', label: 'PDF' },
  { value: 'image', label: '图片' },
];

export const STATE_FILTERS = [
  { value: '', label: '全部状态' },
  { value: 'published', label: '生效中' },
  { value: 'review_required', label: '待审核' },
  { value: 'failed', label: '导入失败' },
];

export interface StateBadge {
  label: string;
  badge: string;
}

const VERSION_STATES: Record<string, StateBadge> = {
  published: { label: '生效', badge: 'badge-emerald' },
  review_required: { label: '待审核', badge: 'badge-amber' },
  failed: { label: '导入失败', badge: 'badge-rose' },
  superseded: { label: '已替换', badge: 'badge-slate' },
  deleted: { label: '已删除', badge: 'badge-plain' },
  queued: { label: '排队中', badge: 'badge-blue' },
  processing: { label: '处理中', badge: 'badge-blue' },
  cancelled: { label: '已取消', badge: 'badge-plain' },
};

export function versionStateBadge(state?: string | null): StateBadge {
  return (state && VERSION_STATES[state]) || { label: state || '未记录', badge: 'badge-slate' };
}

const STAGE_LABELS: Record<string, string> = {
  parse: '文件解析',
  ocr: '文字识别',
  extract: '内容提取',
  index: '索引构建',
  embed: '向量化',
  review: '待审核',
};

export function stageLabel(stage?: string | null): string {
  if (!stage) return '未记录';
  return STAGE_LABELS[stage] ?? stage;
}

export function formatMoment(value?: string | null): string {
  if (!value) return '未记录';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date);
  const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? '';
  return `${pick('year')}-${pick('month')}-${pick('day')} ${pick('hour')}:${pick('minute')}`;
}

export function shortId(value?: string | null): string {
  if (!value) return '';
  return value.length > 8 ? value.slice(0, 8) : value;
}

/** 当前生效版本：仅 state='published' 的版本；其余一律“暂无生效版本”。 */
export function effectiveVersion(item?: DocumentItem | null): DocumentVersionSummary | null {
  const current = item?.current_version ?? null;
  if (!current) return null;
  return current.state === 'published' ? current : null;
}

export function latestVersion(detail?: AssetDetail | null): AssetVersion | null {
  const versions = detail?.versions ?? [];
  if (versions.length === 0) return null;
  return versions.reduce((latest, current) => (current.number > latest.number ? current : latest), versions[0]);
}

export function importForVersion(detail: AssetDetail | null | undefined, versionId?: string | null): AssetImport | null {
  if (!detail || !versionId) return null;
  return (detail.imports ?? []).find((job) => job.version_id === versionId) ?? null;
}

export function activeVersion(detail?: AssetDetail | null): AssetVersion | null {
  const versions = detail?.versions ?? [];
  const activeId = detail?.document.active_version_id ?? null;
  if (!activeId) return null;
  return versions.find((version) => version.version_id === activeId) ?? null;
}

/** 列表是否需要补拉详情：无生效版本、或存在导入任务线索时才需要。 */
export function needsDetail(item: DocumentItem): boolean {
  const current = item.current_version;
  if (!current) return true;
  if (current.state !== 'published') return true;
  return (item.latest_import ?? null) !== null;
}

/**
 * 未拉详情时的保守口径：仅当“已发布生效且没有任何导入任务线索”才判定无新版，
 * 其余返回 null 表示未知（不臆造版本状态）。
 */
export function describeNewVersionFallback(item: DocumentItem): NewVersionStatus | null {
  if ((item.latest_import ?? null) === null && effectiveVersion(item)) {
    return { tone: 'none', text: '无新版' };
  }
  return null;
}

export type NewVersionTone = 'none' | 'pending' | 'failed' | 'processing' | 'unknown' | 'published';

export interface NewVersionStatus {
  tone: NewVersionTone;
  text: string;
}

/**
 * “新版处理状态”：
 * - 无生效版本时，最新版本就是当前版本，不展示为生效；
 * - 最新版本号 <= 生效版本号即无新版；
 * - 其余按最新版本状态标注版本号。
 */
export function describeNewVersion(item: DocumentItem, latest: AssetVersion | null): NewVersionStatus {
  if (!latest) return { tone: 'unknown', text: '版本状态未取到' };
  const effective = effectiveVersion(item);
  const effectiveNumber = effective?.number ?? 0;
  if (latest.number <= effectiveNumber && latest.state === 'published') {
    return { tone: 'none', text: '无新版' };
  }
  if (latest.number === effectiveNumber && latest.state !== 'published') {
    return { tone: 'none', text: '无新版' };
  }
  switch (latest.state) {
    case 'review_required':
      return { tone: 'pending', text: `V${latest.number} 待审核` };
    case 'failed':
      return { tone: 'failed', text: `V${latest.number} 导入失败` };
    case 'queued':
    case 'processing':
      return { tone: 'processing', text: `V${latest.number} 处理中` };
    case 'published':
      return effectiveNumber === 0
        ? { tone: 'published', text: `V${latest.number} 已发布` }
        : { tone: 'published', text: `V${latest.number} 已发布未生效` };
    case 'superseded':
      return { tone: 'none', text: `V${latest.number} 已替换` };
    case 'deleted':
      return { tone: 'none', text: `V${latest.number} 已删除` };
    default:
      return { tone: 'unknown', text: `V${latest.number} ${versionStateBadge(latest.state).label}` };
  }
}

export type ImportTone = 'failed' | 'pending' | 'normal' | 'unknown';

export interface ImportStatusView {
  tone: ImportTone;
  headline: string;
  body: string;
  stage: string;
  errorCode: string;
  message: string;
  activeNumber: number | null;
  failingNumber: number | null;
}

/**
 * 抽屉“导入状态”三态：失败红 / 待审核琥珀 / 正常绿。
 * 只渲染接口实际返回的字段；逐阶段时间线未返回则不画。
 */
export function describeImportStatus(detail?: AssetDetail | null, item?: DocumentItem | null): ImportStatusView {
  const versions = detail?.versions ?? [];
  const active = activeVersion(detail);
  const activeNumber = active?.number ?? null;
  const failedVersions = versions.filter((version) => version.state === 'failed');
  const latest = latestVersion(detail);

  const failedVersion =
    failedVersions.length > 0
      ? failedVersions.reduce((a, b) => (b.number > a.number ? b : a), failedVersions[0])
      : latest && importForVersion(detail, latest.version_id)?.state === 'failed'
        ? latest
        : null;

  if (failedVersion) {
    const job = importForVersion(detail, failedVersion.version_id);
    const nextEffective = activeNumber !== null ? `V${activeNumber} 继续生效` : '当前无生效版本';
    return {
      tone: 'failed',
      headline: `V${failedVersion.number} 导入失败，${nextEffective}`,
      body: '系统未发布该版本，问答仍引用当前生效版本。可前往资料管理重新上传。',
      stage: job ? stageLabel(job.stage) : '未记录',
      errorCode: job?.error_code ?? failedVersion.error_code ?? '未返回错误码',
      message: job?.message ?? failedVersion.message ?? '',
      activeNumber,
      failingNumber: failedVersion.number,
    };
  }

  const latestJob = latest ? importForVersion(detail, latest.version_id) : null;
  if (
    latest?.state === 'review_required' ||
    latest?.state === 'processing' ||
    latest?.state === 'queued' ||
    latestJob?.state === 'running' ||
    latestJob?.state === 'queued'
  ) {
    return {
      tone: 'pending',
      headline: latest ? `V${latest.number} ${versionStateBadge(latest.state).label}` : '新版处理中',
      body: '新版已提取，等待管理员检查发布；在此之前问答继续引用旧版本。',
      stage: latestJob ? stageLabel(latestJob.stage) : '未记录',
      errorCode: latestJob?.error_code ?? '未返回错误码',
      message: latestJob?.message ?? '',
      activeNumber,
      failingNumber: null,
    };
  }

  if (item && !detail) {
    return {
      tone: 'unknown',
      headline: '详情未取到',
      body: '版本与导入状态暂不可读，请稍后重试。',
      stage: '未记录',
      errorCode: '未返回错误码',
      message: '',
      activeNumber: null,
      failingNumber: null,
    };
  }

  return {
    tone: 'normal',
    headline: activeNumber !== null ? '导入完成，已发布生效' : '尚无生效版本',
    body:
      activeNumber !== null
        ? '当前无待处理版本，问答引用与生效版本一致。'
        : '当前资料没有已发布版本，问答不会引用该资料。',
    stage: latestJob ? stageLabel(latestJob.stage) : '未记录',
    errorCode: latestJob?.error_code ?? '未返回错误码',
    message: latestJob?.message ?? '',
    activeNumber,
    failingNumber: null,
  };
}

/** 列表“新版处理状态”文案的色调。 */
export function newVersionToneClass(tone: NewVersionTone): string {
  switch (tone) {
    case 'pending':
      return 'asset-status asset-status-amber';
    case 'failed':
      return 'asset-status asset-status-rose';
    case 'processing':
      return 'asset-status asset-status-blue';
    case 'published':
      return 'asset-status asset-status-emerald';
    case 'unknown':
      return 'asset-status asset-status-muted';
    default:
      return 'asset-status asset-status-muted';
  }
}
