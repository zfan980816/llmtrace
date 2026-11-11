import { useEffect, useState } from "react";
import { adminCreateUser, adminListAudit, adminListUsers, adminUpdateUser, api } from "../api";
import Icon from "../components/Icon";
import StatusIcon from "../components/StatusIcon";
import { useAuth } from "../auth";

const ROLE_LABELS = { admin: "管理员", member: "成员", viewer: "只读" };
const ROLES = ["admin", "member", "viewer"];

const ACTION_LABELS = {
  "user.create": "创建用户", "user.update": "更新用户",
  "project.create": "创建项目", "project.update": "更新项目",
  "rule.create": "创建规则", "rule.update": "更新规则", "rule.delete": "删除规则",
};

function ProjectRow({ p, onChanged }) {
  const [mask, setMask] = useState(p.mask_pii);
  const [retention, setRetention] = useState(p.retention_days);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);

  const copyKey = async () => {
    try {
      await navigator.clipboard.writeText(p.api_key);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* ignore */ }
  };

  const rotate = async () => {
    if (!window.confirm("轮换后旧 API Key 立即失效（SDK 需更新配置），确定？")) return;
    await api.post("/projects/" + p.id + "/rotate-key");
    onChanged();
  };

  const toggleMask = async () => {
    const r = await api.patch("/projects/" + p.id, { mask_pii: !mask });
    setMask(r.data.mask_pii);
  };
  const save = async () => {
    setSaving(true);
    try {
      await api.patch("/projects/" + p.id, { retention_days: Number(retention) });
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  return (
    <tr>
      <td style={{ fontWeight: 500 }}>{p.name}</td>
      <td>
        <span className="mono" style={{ maxWidth: 130 }}>{p.api_key.slice(0, 12)}…</span>
        <button className="link-btn" style={{ marginLeft: 6 }} onClick={copyKey}>
          {copied ? "已复制" : "复制"}
        </button>
        <button className="link-btn danger" style={{ marginLeft: 6 }} onClick={rotate} title="轮换 API Key">
          <Icon name="refresh" size={12} />
        </button>
      </td>
      <td>
        <span className={"chip " + (mask ? "ok" : "")} style={{ cursor: "pointer" }} onClick={toggleMask}>
          {mask ? "脱敏中" : "未开启"}
        </span>
      </td>
      <td className="num">
        <input type="number" min="0" max="3650" value={retention}
          onChange={(e) => setRetention(e.target.value)}
          style={{ width: 76, textAlign: "right" }} />
      </td>
      <td className="num">
        <button className="btn btn-ghost" onClick={save} disabled={saving}>保存</button>
      </td>
    </tr>
  );
}

function AuditSection({ logs }) {
  return (
    <div>
      <h2>审计日志</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th>时间</th><th>操作人</th><th>操作</th><th>对象</th><th>详情</th></tr>
          </thead>
          <tbody>
            {logs.map((a) => (
              <tr key={a.id}>
                <td className="muted">{new Date(a.created_at).toLocaleString("zh-CN")}</td>
                <td style={{ fontWeight: 500 }}>{a.username}</td>
                <td><span className="chip">{ACTION_LABELS[a.action] || a.action}</span></td>
                <td>{a.target || "—"}</td>
                <td><span className="mono" style={{ maxWidth: 340 }}>{a.detail ? JSON.stringify(a.detail) : "—"}</span></td>
              </tr>
            ))}
            {!logs.length && (
              <tr><td colSpan={5}>
                <div className="empty"><Icon name="inbox" size={22} />暂无审计记录</div>
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Users() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [users, setUsers] = useState([]);
  const [projects, setProjects] = useState([]);
  const [audit, setAudit] = useState([]);
  const [form, setForm] = useState({ username: "", display_name: "", password: "", role: "member" });
  const [error, setError] = useState(null);

  const load = async () => {
    try {
      setUsers(await adminListUsers());
      setProjects((await api.get("/projects")).data);
      setAudit(await adminListAudit());
    } catch (e) {
      setError(String(e.response?.data?.detail || e.message));
    }
  };

  useEffect(() => { if (isAdmin) load(); }, [isAdmin]);

  if (!isAdmin) {
    return <div className="empty"><Icon name="alert-triangle" size={22} />需要管理员权限</div>;
  }

  const create = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      await adminCreateUser(form);
      setForm({ username: "", display_name: "", password: "", role: "member" });
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "创建失败");
    }
  };

  const setRole = async (u, role) => {
    await adminUpdateUser(u.id, { role });
    await load();
  };

  const toggleActive = async (u) => {
    await adminUpdateUser(u.id, { is_active: !u.is_active });
    await load();
  };

  const resetPassword = async (u) => {
    const pwd = window.prompt("为 " + u.username + " 设置新密码（至少 6 位）：");
    if (!pwd) return;
    try {
      await adminUpdateUser(u.id, { password: pwd });
      setError(null);
    } catch (err) {
      setError(err.response?.data?.detail || "重置失败");
    }
  };

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  return (
    <div className="page">
      <h1 style={{ marginBottom: 18 }}>成员管理</h1>

      <h2>添加成员</h2>
      <form className="form-grid" onSubmit={create}>
        <div className="field"><label>用户名</label>
          <input required minLength={2} value={form.username} onChange={set("username")} /></div>
        <div className="field"><label>显示名</label>
          <input value={form.display_name} placeholder="可选" onChange={set("display_name")} /></div>
        <div className="field"><label>初始密码</label>
          <input required minLength={6} type="password" value={form.password} onChange={set("password")} /></div>
        <div className="field"><label>角色</label>
          <select value={form.role} onChange={set("role")}>
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
          </select></div>
        <div className="field"><label>&nbsp;</label>
          <button className="btn"><Icon name="plus" size={13} /> 添加</button></div>
      </form>
      {error && <div className="error-text">{error}</div>}

      <h2>成员列表</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th>用户名</th><th>显示名</th><th>角色</th><th>状态</th><th>操作</th></tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td style={{ fontWeight: 550 }}>{u.username}</td>
                <td className="muted">{u.display_name || "—"}</td>
                <td>
                  <select value={u.role} disabled={u.id === user.id}
                    onChange={(e) => setRole(u, e.target.value)}>
                    {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                  </select>
                </td>
                <td><StatusIcon status={u.is_active ? "ok" : "error"} /></td>
                <td>
                  <button className="link-btn" onClick={() => toggleActive(u)} disabled={u.id === user.id}>
                    {u.is_active ? "停用" : "启用"}
                  </button>
                  {" · "}
                  <button className="link-btn" onClick={() => resetPassword(u)}>重置密码</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>项目设置（脱敏 / 数据保留）</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th>项目</th><th>API Key</th><th>敏感信息脱敏</th><th className="num">保留天数（0 = 永久）</th><th className="num"></th></tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <ProjectRow key={p.id} p={p} onChanged={load} />
            ))}
          </tbody>
        </table>
      </div>

      <AuditSection logs={audit} />
    </div>
  );
}

