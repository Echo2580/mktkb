import { useRef, useState } from 'react';
import { api, errorMessage, isApiError } from '../../api/client';
import type { UploadResponse } from '../../api/client';
import { Dialog } from '../../components/Dialog';
import { Icon } from '../../components/Icon';
import { formatBytes } from '../../utils/format';

const ALLOWED_EXTENSIONS = ['docx', 'xlsx', 'pdf', 'png', 'jpg', 'jpeg'];
const MAX_BYTES = 20 * 1024 * 1024;

export interface UploadTarget {
  id: string;
  name: string;
  activeVersionId?: string | null;
  activeVersionNumber?: number | null;
}

interface UploadDialogProps {
  mode: 'create' | 'replace';
  target?: UploadTarget;
  initialFile?: File;
  onClose: () => void;
  onUploaded: (receipt: UploadResponse) => void;
}

interface ConflictCandidate {
  id?: string;
  name?: string;
  file_type?: string;
  latest_version_number?: number;
  latest_state?: string;
}

function extensionOf(name: string): string {
  return name.split('.').pop()?.toLowerCase() ?? '';
}

function candidatesFrom(details: Record<string, unknown> | null): ConflictCandidate[] {
  const raw = details?.candidates;
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is ConflictCandidate => typeof item === 'object' && item !== null);
}

export function validateUploadFile(selected: File): string | null {
  if (selected.size === 0) return '文件为空，请选择有效文件';
  if (selected.size > MAX_BYTES) return `文件超过单文件 20 MB 上限（当前 ${formatBytes(selected.size)}）`;
  if (!ALLOWED_EXTENSIONS.includes(extensionOf(selected.name))) {
    return '仅支持 .docx、.xlsx、.pdf、.png、.jpg、.jpeg';
  }
  return null;
}

export function UploadDialog({ mode, target, initialFile, onClose, onUploaded }: UploadDialogProps) {
  const [file, setFile] = useState<File | null>(initialFile ?? null);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<ConflictCandidate[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<string>('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  function chooseFile(selected: File | null) {
    if (!selected) return;
    const problem = validateUploadFile(selected);
    if (problem) {
      setFile(null);
      setError(problem);
      return;
    }
    setFile(selected);
    setError(null);
    setConflict(null);
  }

  async function upload(options: { allowSameName?: boolean; replaceDocumentId?: string; expectedActiveId?: string | null } = {}) {
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    setPhase(options.replaceDocumentId ? '正在上传新版本…' : '正在上传资料…');
    try {
      const receipt = options.replaceDocumentId
        ? await api.uploadVersion(
            options.replaceDocumentId,
            file,
            options.expectedActiveId ?? target?.activeVersionId ?? null,
          )
        : await api.uploadDocument(file, options.allowSameName ?? false);
      onUploaded(receipt);
    } catch (caught) {
      if (isApiError(caught) && caught.code === 'SAME_NAME_REQUIRES_ACTION') {
        setConflict(candidatesFrom(caught.details));
        setError('已存在同名资料。请选择“替换现有资料”或“作为独立资料新增”，系统不会静默覆盖。');
      } else if (isApiError(caught) && caught.code === 'DUPLICATE_CONTENT') {
        setError('该文件与现有有效或待处理资料字节完全相同，未创建重复资料。');
      } else if (isApiError(caught) && caught.code === 'CONTENT_UNCHANGED') {
        setError('替换内容与当前有效版本完全相同，未创建新版本。');
      } else {
        setError(errorMessage(caught));
      }
    } finally {
      setBusy(false);
      setPhase('');
    }
  }

  const title = mode === 'replace' ? '替换资料' : '上传资料';
  const description =
    mode === 'replace'
      ? '上传后进入检查确认，确认发布前旧版继续生效。'
      : '上传后先完成提取与检查，确认发布后才参与问答。';

  return (
    <Dialog
      title={title}
      description={description}
      onClose={busy ? () => undefined : onClose}
      size="default"
      footer={
        <>
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!file || busy}
            onClick={() =>
              mode === 'replace' && target
                ? void upload({ replaceDocumentId: target.id, expectedActiveId: target.activeVersionId })
                : void upload({})
            }
          >
            {busy ? <span className="spinner spinner-sm" aria-hidden="true" /> : <Icon name="upload" size={14} />}
            {busy ? phase || '正在上传…' : '上传'}
          </button>
        </>
      }
    >
      {mode === 'replace' && target ? (
        <div className="notice notice-info" style={{ marginBottom: 12 }}>
          <Icon name="git-branch" size={14} className="notice-icon" />
          <div className="notice-body">
            <p>
              当前有效版本 <strong>V{target.activeVersionNumber ?? '—'}</strong> · 本次将生成新版本
            </p>
            <p style={{ marginTop: 2, fontSize: 11 }}>
              新版本处理中或失败时，旧版 V{target.activeVersionNumber ?? '—'} 继续生效；旧版不会被覆盖。
            </p>
          </div>
        </div>
      ) : null}

      <input
        ref={fileInputRef}
        type="file"
        accept=".docx,.xlsx,.pdf,.png,.jpg,.jpeg"
        className="sr-only"
        aria-label="选择要上传的文件"
        onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
      />
      <button
        type="button"
        className="upload-drop"
        onClick={() => fileInputRef.current?.click()}
        disabled={busy}
        aria-label="选择文件"
      >
        <Icon name="upload-cloud" size={22} />
        <span className="upload-drop-title">{file ? '重新选择文件' : '选择文件'}</span>
        <span className="upload-drop-desc">支持 .docx / .xlsx / .pdf / .png / .jpg / .jpeg，单文件 20 MB 以内</span>
        <span className="upload-drop-desc">服务端会校验实际类型、大小与可读性；不支持或损坏的文件会被拒绝并说明原因。</span>
      </button>

      {file ? (
        <div className="chosen-file">
          <Icon name="file-text" size={16} />
          <div className="chosen-file-main">
            <p className="file-name">{file.name}</p>
            <p className="file-sub">{formatBytes(file.size)} · {extensionOf(file.name).toUpperCase()}</p>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="移除已选文件"
            disabled={busy}
            onClick={() => {
              setFile(null);
              if (fileInputRef.current) fileInputRef.current.value = '';
            }}
          >
            <Icon name="x" size={15} />
          </button>
        </div>
      ) : null}

      {error ? (
        <div className="form-error" role="alert" style={{ marginTop: 12 }}>
          <Icon name="alert-circle" size={14} className="notice-icon" />
          <span>{error}</span>
        </div>
      ) : null}

      {conflict ? (
        <div style={{ marginTop: 12 }}>
          <p className="form-label">同名资料</p>
          {conflict.length === 0 ? (
            <p className="form-help">服务端未返回同名候选；可改为“作为独立资料新增”。</p>
          ) : (
            <div className="choice-list">
              {conflict.map((candidate) => (
                <div className="choice-item" key={candidate.id ?? candidate.name}>
                  <div className="choice-main">
                    <p className="choice-name">{candidate.name ?? target?.name ?? '同名资料'}</p>
                    <p className="choice-meta">
                      {candidate.file_type?.toUpperCase() ?? '未知类型'} · 最新版本 V
                      {candidate.latest_version_number ?? '—'} · 状态 {candidate.latest_state ?? '未知'}
                    </p>
                  </div>
                  <div className="choice-actions">
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      disabled={busy || !candidate.id}
                      onClick={() => void upload({ replaceDocumentId: candidate.id, expectedActiveId: null })}
                    >
                      替换此资料
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
          <button
            type="button"
            className="btn btn-secondary btn-block"
            style={{ marginTop: 10 }}
            disabled={busy}
            onClick={() => void upload({ allowSameName: true })}
          >
            <Icon name="plus" size={14} />
            作为独立资料新增
          </button>
        </div>
      ) : null}
    </Dialog>
  );
}
