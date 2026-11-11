import { useEffect, useState } from "react";
import api, { ensureProject } from "../api";
import { useAuth } from "../auth";
import Icon from "../components/Icon";
import { t, useLang } from "../i18n";
import StatusIcon from "../components/StatusIcon";

const METRIC_LABELS = {
  error_rate: "错误率",
  avg_latency_ms: "平均延迟",
  p95_latency_ms: "P95 延迟",
};

const EMPTY_FORM = {
  name: "",
  metric_type: "error_rate",
  threshold: "0.2",
  window_minutes: "15",
  webhook_url: "",
  webhook_format: "generic",
  webhook_secret: "",
};

export default function Alerts() {
  const { user } = useAuth();
  const canWrite = user?.role !== "viewer";
  const [project, setProject] = useState(null);
  const [rules, setRules] = useState([]);
  const [events, setEvents] = useState([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = async (p) => {
    const params = { project_id: p.id };
    const [r, e] = await Promise.all([
      api.get("/alerts/rules", { params }),
      api.get("/alerts/events", { params }),
    ]);
    setRules(r.data);
    setEvents(e.data);
  };

  useEffect(() => {
    ensureProject().then((p) => { setProject(p); return load(p); }).catch(() => {});
  }, []);

  const create = async (ev) => {
    ev.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/alerts/rules", {
        project_id: project.id,
        name: form.name,
        metric_type: form.metric_type,
        threshold: parseFloat(form.threshold),
        window_minutes: parseInt(form.window_minutes, 10),
        webhook_url: form.webhook_url || null,
        webhook_format: form.webhook_format,
        webhook_secret: form.webhook_secret || null,
      });
      setForm({ ...EMPTY_FORM, threshold: form.threshold, window_minutes: form.window_minutes });
      await load(project);
    } catch (e) {
      setError(String(e.response?.data?.detail || e.message));
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (rule) => {
    await api.patch("/alerts/rules/" + rule.id, { enabled: !rule.enabled });
    await load(project);
  };

  const remove = async (rule) => {
    await api.delete("/alerts/rules/" + rule.id);
    await load(project);
  };

  const evaluateNow = async () => {
    setBusy(true);
    try {
      await api.post("/alerts/evaluate", null, { params: { project_id: project.id } });
      await load(project);
    } finally {
      setBusy(false);
    }
  };

  const fmtThreshold = (v) =>
    v.metric_type === "error_rate" ? (v.threshold * 100).toFixed(0) + "%" : v.threshold;
  const fmtValue = (v) =>
    v.metric_type === "error_rate" ? (v.value * 100).toFixed(1) + "%" : v.value;

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  return (
    <div className="page">
      <div className="page-head">
        <h1>告警</h1>
        {canWrite && (
          <button className="btn" onClick={evaluateNow} disabled={busy || !project}>
            <Icon name="radar" size={13} /> 立即检测
          </button>
        )}
      </div>

{canWrite && <h2>新建规则</h2>}
      {canWrite && (
      <form className="form-grid" onSubmit={create}>
        <div className="field">
          <label>规则名称</label>
          <input required placeholder="如：错误率过高" value={form.name} onChange={set("name")} />
        </div>
        <div className="field">
          <label>指标</label>
          <select value={form.metric_type} onChange={set("metric_type")}>
            {Object.entries(METRIC_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div className="field">
          <label>阈值（错误率用 0-1）</label>
          <input required type="number" step="any" value={form.threshold} onChange={set("threshold")} />
        </div>
        <div className="field">
          <label>检测窗口（分钟）</label>
          <input required type="number" min="1" value={form.window_minutes} onChange={set("window_minutes")} />
        </div>
        <div className="field">
          <label>Webhook URL（可选）</label>
          <input placeholder="https://…" value={form.webhook_url} onChange={set("webhook_url")} />
        </div>
        <div className="field">
          <label>通知格式</label>
          <select value={form.webhook_format} onChange={set("webhook_format")}>
            <option value="generic">通用 JSON</option>
            <option value="feishu">飞书机器人</option>
            <option value="dingtalk">钉钉机器人</option>
          <option value="wecom">企业微信机器人</option>
          </select>
        </div>
        <div className="field">
          <label>&nbsp;</label>
          <button className="btn" disabled={busy || !project}>创建规则</button>
        </div>
      </form>
      )}
      {error && <div className="error-text">{error}</div>}

      <h2>规则列表</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th>名称</th><th>指标</th><th>阈值</th><th>窗口</th><th>通知</th><th>状态</th>{canWrite && <th></th>}</tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id}>
                <td style={{ fontWeight: 500 }}>{r.name}</td>
                <td>{METRIC_LABELS[r.metric_type] || r.metric_type}</td>
                <td>{fmtThreshold(r)}</td>
                <td>{r.window_minutes} 分钟</td>
                <td className="muted">{r.webhook_url ? (r.webhook_format + (r.webhook_secret ? " ✓签" : "")) : "—"}</td>
                <td>
                  <span className={"chip " + (r.enabled ? "ok" : "")} style={{ cursor: "pointer" }} onClick={() => toggle(r)}>
                    {r.enabled ? "已启用" : "已停用"}
                  </span>
                </td>
                <td><button className="link-btn danger" onClick={() => remove(r)}><Icon name="trash" size={12} /> 删除</button></td>
              </tr>
            ))}
            {!rules.length && <tr><td colSpan={canWrite ? 7 : 6} className="empty"><Icon name="bell" size={22} />暂无规则 — 创建一条开始监控</td></tr>}
          </tbody>
        </table>
      </div>

      <h2>最近告警</h2>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th></th><th>时间</th><th>规则</th><th>指标</th><th>当前值</th><th>阈值</th></tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id}>
                <td style={{ width: 30 }}><StatusIcon status="error" size={14} /></td>
                <td className="muted">{new Date(e.created_at).toLocaleString("zh-CN")}</td>
                <td style={{ fontWeight: 500 }}>{e.rule_name}</td>
                <td>{METRIC_LABELS[e.metric_type] || e.metric_type}</td>
                <td className="alert-value">{fmtValue(e)}</td>
                <td>{fmtThreshold(e)}</td>
              </tr>
            ))}
            {!events.length && <tr><td colSpan={6} className="empty"><Icon name="inbox" size={22} />暂无告警记录</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}




