import { useState } from "react";
import { changeOwnPassword } from "../api";
import { t } from "../i18n";

export default function ForcePasswordChange({ onDone }) {
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    if (newPw.length < 8) return setError("新密码至少 8 位");
    if (newPw !== confirm) return setError("两次输入不一致");
    setBusy(true);
    try {
      await changeOwnPassword(oldPw, newPw);
      onDone();
    } catch (err) {
      setError(err.response?.data?.detail || "修改失败");
    } finally { setBusy(false); }
  };

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <h2 style={{ margin: "0 0 8px", fontSize: 18 }}>修改默认密码</h2>
        <p style={{ margin: "0 0 16px", color: "var(--muted)", fontSize: 13 }}>
          当前账号还在使用默认密码，为了安全请先设置新密码。
        </p>
        <label className="field"><span>当前密码</span>
          <input type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} required autoFocus />
        </label>
        <label className="field"><span>新密码</span>
          <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} required minLength={8} />
        </label>
        <label className="field"><span>确认新密码</span>
          <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required minLength={8} />
        </label>
        {error && <div className="form-error">{error}</div>}
        <button className="btn primary full" disabled={busy} style={{ marginTop: 12 }}>
          {busy ? "提交中…" : "确认修改"}
        </button>
      </form>
    </div>
  );
}
