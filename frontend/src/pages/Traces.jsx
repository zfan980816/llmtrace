import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import api, { ensureProject } from "../api";
import Icon from "../components/Icon";
import StatusIcon from "../components/StatusIcon";
import { latClass } from "./TraceDetail";
import { t, useLang } from "../i18n";

const PAGE_SIZE = 50;
const SPAN_TYPES = [["", ""], ["llm", "spanType.llm"], ["tool", "spanType.tool"], ["retrieval", "spanType.retrieval"], ["agent", "spanType.agent"], ["chain", "spanType.chain"]];
const VIEWS = [["traces", "view.traces"], ["threads", "view.threads"], ["runs", "view.runs"]];

function timeAgo(iso) {
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
  if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
  if (diff < 86400 * 7) return Math.floor(diff / 86400) + " 天前";
  return d.toLocaleString("zh-CN");
}

function fmtLatency(ms) {
  return ms >= 1000 ? (ms / 1000).toFixed(2) + " s" : ms + " ms";
}

function fmtTokens(n) {
  if (!n) return "0";
  if (n >= 1000) {
    const k = n / 1000;
    return (k >= 100 ? k.toFixed(0) : k.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")) + "K";
  }
  return String(n);
}

function firstText(v) {
  if (v == null) return null;
  if (typeof v === "string") return v;
  if (Array.isArray(v)) {
    const msgs = v.filter((m) => m && (m.content != null || m.tool_calls));
    const m = msgs[0];
    if (!m) return null;
    const role = m.role === "user" || m.role === "human" ? "human" : m.role === "assistant" || m.role === "ai" ? "ai" : m.role;
    if (m.tool_calls?.length) return role + ": 🛠 " + m.tool_calls.map((t) => t.function?.name).join(", ");
    const text = typeof m.content === "string" ? m.content : JSON.stringify(m.content);
    return role + ": " + text;
  }
  if (typeof v === "object") {
    for (const k of ["user_message", "query", "question", "input", "prompt", "message", "text", "itinerary"]) {
      if (typeof v[k] === "string" && v[k].trim()) return v[k];
    }
    for (const val of Object.values(v)) {
      if (val == null || val === "") continue;
      const inner = firstText(val);
      if (inner) return inner;
    }
    return null;
  }
  return String(v);
}

function preview(v, max = 64) {
  const s = firstText(v);
  if (!s) return "—";
  return s.length > max ? s.slice(0, max) + "…" : s;
}

function errText(e) {
  if (!e) return "—";
  const s = typeof e === "string" ? e : e.message || JSON.stringify(e);
  return s.length > 50 ? s.slice(0, 50) + "…" : s;
}

async function download(project_id, format) {
  const r = await api.get("/traces/export", { params: { project_id, format }, responseType: "blob" });
  const url = URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = "traces." + format;
  a.click();
  URL.revokeObjectURL(url);
}

const EMPTY_FILTER = { model: "", span_type: "", min_latency: "", max_latency: "" };

function useDebounced(value, ms) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function Traces() {
  const lang = useLang();
  const [project, setProject] = useState(null);
  const [view, setView] = useState("traces");
  const [items, setItems] = useState([]);
  const [threads, setThreads] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sp] = useSearchParams();
  const [status, setStatus] = useState(() => sp.get("status") || "");
  const [q, setQ] = useState(() => sp.get("q") || "");
  const dq = useDebounced(q, 400);
  const [draft, setDraft] = useState(EMPTY_FILTER);
  const [filters, setFilters] = useState(EMPTY_FILTER);
  const [nonce, setNonce] = useState(0);

  useEffect(() => { ensureProject().then(setProject).catch(() => {}); }, []);

  useEffect(() => {
    if (!project) return;
    if (view === "threads") {
      api.get("/sessions", { params: { project_id: project.id } })
        .then((r) => setThreads(r.data)).catch(() => setThreads([]));
      return;
    }
    const url = view === "runs" ? "/traces/runs" : "/traces";
    const params = { project_id: project.id, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE };
    if (view === "traces") {
      params.status = status || undefined;
      params.model = filters.model || undefined;
      params.span_type = filters.span_type || undefined;
      params.min_latency = filters.min_latency || undefined;
      params.max_latency = filters.max_latency || undefined;
    } else {
      params.model = filters.model || undefined;
      params.span_type = filters.span_type || undefined;
    }
    if (view !== "threads" && dq) params.q = dq;
    api.get(url, { params }).then((r) => {
      setItems(r.data.items);
      setTotal(r.data.total);
    }).catch(() => { setItems([]); setTotal(0); });
  }, [project, view, status, filters, page, dq, nonce]);

  // WebSocket 实时推送：新 trace 到达后防抖刷新
  useEffect(() => {
    if (!project || view === "threads") return;
    const token = localStorage.getItem("llmtrace_token");
    if (!token) return;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/traces?token=${token}`);
    let timer = null;
    ws.onopen = () => ws.send(JSON.stringify({ type: "subscribe", project_id: project.id }));
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === "trace.new") {
          clearTimeout(timer);
          timer = setTimeout(() => setNonce((n) => n + 1), 500);
        }
      } catch { /* ignore */ }
    };
    return () => { clearTimeout(timer); ws.close(); };
  }, [project, view]);

  const shown = items;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const setF = (key) => (e) => setDraft({ ...draft, [key]: e.target.value });
  const applyFilters = () => { setFilters({ ...draft }); setPage(1); };
  const resetFilters = () => { setDraft(EMPTY_FILTER); setFilters(EMPTY_FILTER); setPage(1); };
  const switchView = (v) => { setView(v); setPage(1); };

  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("traces.title")}</h1>
        <div className="head-actions">
          <div className="seg view-tabs">
            {VIEWS.map(([v, key]) => (
              <button key={v} className={view === v ? "active" : ""} onClick={() => switchView(v)}>{t(key)}</button>
            ))}
          </div>
          {view === "traces" && (
            <div className="seg">
              {[["", "status.all"], ["ok", "status.ok"], ["error", "status.error"]].map(([v, key]) => (
                <button key={v} className={status === v ? "active" : ""} onClick={() => { setStatus(v); setPage(1); }}>
                  {t(key)}
                </button>
              ))}
            </div>
          )}
          <div style={{ position: "relative" }}>
            <input placeholder={t("search.placeholder")} value={q} onChange={(e) => setQ(e.target.value)}
              style={{ width: 170, paddingLeft: 30 }} />
            <Icon name="search" size={13}
              style={{ position: "absolute", left: 10, top: 9, pointerEvents: "none", color: "#5a6478" }} />
          </div>
          {project && view === "traces" && (
            <button className="btn btn-ghost" onClick={() => download(project.id, "csv")} title="CSV">
              <Icon name="file-text" size={13} /> CSV
            </button>
          )}
        </div>
      </div>

      {view !== "threads" && (
        <div className="filter-bar">
          {view === "traces" && (
            <input type="number" placeholder={t("filter.minLatency")} value={draft.min_latency} onChange={setF("min_latency")} style={{ width: 130 }} />
          )}
          <input placeholder={t("filter.model")} value={draft.model} onChange={setF("model")} style={{ width: 200 }} />
          <select value={draft.span_type} onChange={setF("span_type")}>
            {SPAN_TYPES.map(([v, key]) => <option key={v} value={v}>{key ? t(key) : t("filter.allTypes")}</option>)}
          </select>
          <button className="btn" onClick={applyFilters}><Icon name="search" size={13} /> {t("filter.apply")}</button>
          <button className="btn btn-ghost" onClick={resetFilters}>{t("filter.reset")}</button>
        </div>
      )}

      {view === "threads" && (
        <div className="table-wrap">
          <table className="table threads-table">
            <thead>
              <tr>
                <th>{t("th.session")}</th>
                <th className="num">{t("th.traceCount")}</th>
                <th className="num">{t("th.tokens")}</th>
                <th className="num">{t("th.cost")}</th>
                <th className="num">{t("th.avgLatency")}</th>
                <th>{t("th.lastSeen")}</th>
              </tr>
            </thead>
            <tbody>
              {threads.filter((s) => !q || (s.session_id || "").toLowerCase().includes(q.toLowerCase())).map((s) => (
                <tr key={s.session_id}>
                  <td><Link className="trace-name-link mono" to={"/sessions/" + encodeURIComponent(s.session_id)}>{s.session_id}</Link></td>
                  <td className="num">{s.trace_count}</td>
                  <td className="num">{fmtTokens(s.total_tokens)}</td>
                  <td className="num">${s.total_cost.toFixed(5)}</td>
                  <td className="num">{fmtLatency(s.avg_latency_ms)}</td>
                  <td className="muted">{new Date(s.last_seen).toLocaleString("zh-CN")}</td>
                </tr>
              ))}
              {!threads.length && (
                <tr><td colSpan={6}><div className="empty"><Icon name="inbox" size={22} />{t("empty.noSessions")}</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {view === "traces" && (
        <div className="table-wrap">
          <table className="table traces-table">
            <thead>
              <tr>
                <th style={{ width: 34 }}></th>
                <th style={{ width: 120 }}>{t("th.name")}</th>
                <th>{t("th.input")}</th>
                <th>{t("th.output")}</th>
                <th style={{ width: 150 }}>{t("th.error")}</th>
                <th style={{ width: 120 }}>{t("th.startTime")}</th>
                <th className="num" style={{ width: 120 }}>{t("th.latency")}</th>
                <th className="num" style={{ width: 70 }}>{t("th.tokens")}</th>
                <th className="num" style={{ width: 80 }}>{t("th.cost")}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((t) => (
                <tr key={t.id}>
                  <td><StatusIcon status={t.status} /></td>
                  <td><Link to={"/traces/" + t.id} className="trace-name-link" title={t.name}>{t.name}</Link></td>
                  <td><span className="io-preview mono" title={preview(t.input, 200)}>{preview(t.input)}</span></td>
                  <td><span className="io-preview mono" title={preview(t.output, 200)}>{preview(t.output)}</span></td>
                  <td>{t.status === "error" ? <span className="io-error" title={errText(t.error || (t.output && t.output.error))}>{errText(t.error || (t.output && t.output.error))}</span> : <span className="muted">—</span>}</td>
                  <td className="muted" title={new Date(t.start_time).toLocaleString("zh-CN")}>{timeAgo(t.start_time)}</td>
                  <td className="num"><span className={"lat-chip " + latClass(t.latency_ms)}><Icon name="clock" size={10} /> {fmtLatency(t.latency_ms)}</span></td>
                  <td className="num">{fmtTokens(t.total_tokens)}</td>
                  <td className="num">${t.cost.toFixed(5)}</td>
                </tr>
              ))}
              {!shown.length && (
                <tr><td colSpan={9}><div className="empty"><Icon name="inbox" size={22} />{t("empty.noTraces")}</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {view === "runs" && (
        <div className="table-wrap">
          <table className="table traces-table">
            <thead>
              <tr>
                <th style={{ width: 34 }}></th>
                <th style={{ width: 140 }}>{t("th.run")}</th>
                <th style={{ width: 130 }}>{t("th.trace")}</th>
                <th>{t("th.input")}</th>
                <th>{t("th.output")}</th>
                <th style={{ width: 130 }}>{t("th.startTime")}</th>
                <th className="num" style={{ width: 120 }}>{t("th.latency")}</th>
                <th className="num" style={{ width: 70 }}>{t("th.tokens")}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id}>
                  <td><StatusIcon status={r.status} /></td>
                  <td>
                    <Link to={"/traces/" + r.trace_id} className="trace-name-link">{r.name}</Link>
                    {r.model && <div><span className="model-chip">{r.model}</span></div>}
                  </td>
                  <td className="muted small">{r.trace_name}</td>
                  <td><span className="io-preview mono" title={preview(r.input, 200)}>{preview(r.input)}</span></td>
                  <td><span className="io-preview mono" title={preview(r.output, 200)}>{preview(r.output)}</span></td>
                  <td className="muted" title={new Date(r.start_time).toLocaleString("zh-CN")}>{timeAgo(r.start_time)}</td>
                  <td className="num"><span className={"lat-chip " + latClass(r.latency_ms)}><Icon name="clock" size={10} /> {fmtLatency(r.latency_ms)}</span></td>
                  <td className="num">{fmtTokens((r.prompt_tokens || 0) + (r.completion_tokens || 0))}</td>
                </tr>
              ))}
              {!shown.length && (
                <tr><td colSpan={8}><div className="empty"><Icon name="inbox" size={22} />{t("empty.noRuns")}</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {view !== "threads" && (
        <div className="pager">
          <span className="muted small">{t("pager.info", { total: total.toLocaleString(), page, pages: totalPages })}</span>
          <button className="btn btn-ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>{t("pager.prev")}</button>
          <button className="btn btn-ghost" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>{t("pager.next")}</button>
        </div>
      )}
    </div>
  );
}
