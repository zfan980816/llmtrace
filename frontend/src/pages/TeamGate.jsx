import { useState } from "react";
import { createTeam, joinTeam } from "../api";
import Icon from "../components/Icon";

export default function TeamGate({ onDone }) {
  const [mode, setMode] = useState(null); // null=选择, "create", "join"
  const [name, setName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const doCreate = async () => {
    setBusy(true); setError(null);
    try {
      await createTeam(name);
      onDone();
    } catch (err) {
      setError(err.response?.data?.detail || "创建失败，请稍后重试");
    } finally { setBusy(false); }
  };

  const doJoin = async () => {
    setBusy(true); setError(null);
    try {
      await joinTeam(inviteCode);
      onDone();
    } catch (err) {
      setError(err.response?.data?.detail || "加入失败，请检查邀请码");
    } finally { setBusy(false); }
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="logo" style={{ justifyContent: "center" }}>
          <span className="logo-mark"><Icon name="radar" size={16} /></span>
          <span className="logo-name">LLMTrace</span>
        </div>
        <p className="login-sub">创建或加入一个团队，开始监控你的 LLM 应用</p>

        {mode === null && (
          <>
            <button className="btn" onClick={() => setMode("create")}>
              <Icon name="plus" size={13} /> 创建新团队
            </button>
            <button type="button" className="btn btn-outline" onClick={() => setMode("join")}>
              <Icon name="users" size={13} /> 加入已有团队
            </button>
            <p className="login-hint">创建团队后会生成项目 API Key 和团队邀请码；加入团队需要向团队管理员索取邀请码。</p>
          </>
        )}

        {mode === "create" && (
          <>
            <input placeholder="团队名称" value={name} autoFocus
              onChange={(e) => setName(e.target.value)} />
            {error && <div className="error-text">{error}</div>}
            <button className="btn" disabled={busy || !name.trim()} onClick={doCreate}>
              <Icon name="check" size={13} /> 创建团队
            </button>
            <button type="button" className="link-btn" onClick={() => setMode(null)}>返回</button>
          </>
        )}

        {mode === "join" && (
          <>
            <input placeholder="团队邀请码" value={inviteCode} autoFocus
              onChange={(e) => setInviteCode(e.target.value)} />
            {error && <div className="error-text">{error}</div>}
            <button className="btn" disabled={busy || !inviteCode.trim()} onClick={doJoin}>
              <Icon name="check" size={13} /> 加入团队
            </button>
            <button type="button" className="link-btn" onClick={() => setMode(null)}>返回</button>
          </>
        )}
      </div>
    </div>
  );
}
