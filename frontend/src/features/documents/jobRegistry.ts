const STORAGE_KEY = 'mktkb.t08.job-registry.v1';

export type JobRegistry = Record<string, string>;

export function loadJobRegistry(): JobRegistry {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return {};
    const result: JobRegistry = {};
    for (const [versionId, jobId] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof jobId === 'string') result[versionId] = jobId;
    }
    return result;
  } catch {
    return {};
  }
}

export function saveJobRegistry(registry: JobRegistry): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(registry));
  } catch {
    // 隐私模式或存储配额不足时仅保留内存状态，不影响上传与处理。
  }
}
