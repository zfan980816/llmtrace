import { useState } from "react";
import { rotateProjectKey } from "../api";
import Icon from "../components/Icon";

export default function ApiKeyModal({ project, isAdmin, onClose, onRotated }) {
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState(null);
  const [error, setError] = useState(null);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(project.api_key);
      setHint("已复制");
      setTimeout(() => setHint(null), 2000);
    } catch {
      setError("复制失败，请手动选择复制");
      setTimeout(() => setError(null), 2500);
    }
  };

  const rotate = async () => {
    if (!confirm("轮换后旧 Key 立即失效，已接入的应用会断报，确定？")) return;
    setBusy(true); setError(null);
    try {
      const fresh = await rotateProjectKey(project.id);
      onRotated(fresh);
      setVisible(true);
      setHint("已轮换，旧 Key 已失效");
      setTimeout(() => setHint(null), 2500);
    } catch (e) {
      setError(e.response?.data?.detail || "轮换失败");
    } finally { setBusy(false); }
  };

  const masked = project.api_key.slice(0, 6) + "•".repeat(20) + project.api_key.slice(-4);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>项目 API Key</h3>
          <button className="modal-x" onClick={onClose}>×</button>
        </div>
        <p className="modal-sub">{project.name} · 用于应用接入 LLMTrace</p>

        <div className="key-row">
          <code className="key-text">{visible ? project.api_key : masked}</code>
          <button type="button" className="pw-eye" onClick={() => setVisible(!visible)} tabIndex={-1}>
            <Icon name={visible ? "eye-off" : "eye"} size={14} />
          </button>
        </div>

        {hint && <div className="form-ok">{hint}</div>}
        {error && <div className="form-error">{error}</div>}

        <div className="modal-actions">
          <button className="btn" onClick={copy}>
            <Icon name="file-text" size={13} /> 复制 Key
          </button>
          {isAdmin && (
            <button className="btn btn-ghost" disabled={busy} onClick={rotate} title="旧 Key 立即失效">
              轮换 Key
            </button>
          )}
        </div>

        <p className="modal-hint">
          接入示例：应用侧配置 LANGSMITH_API_KEY={"{...}"} 或 SDK configure(api_key=...)。
          Key 泄露时用「轮换」立即作废。
        </p>
      </div>
    </div>
  );
}
