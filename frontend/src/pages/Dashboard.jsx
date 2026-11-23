import { useCallback, useEffect, useState } from "react";
import {
  Area, AreaChart, CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import api, { ensureProject } from "../api";
import { Link } from "react-router-dom";
import Icon from "../components/Icon";
import { t, useLang } from "../i18n";

const RANGES = [["1h", 1], ["6h", 6], ["24h", 24], ["7d", 168], ["30d", 720]];

const CARD_DEFS = [
  { key: "total_traces", label: "dash.totalCalls", icon: "activity", color: "#4d8dff", spark: "calls", fmt: (v) => v.toLocaleString() },
  { key: "error_rate", label: "dash.errorRate", icon: "alert-triangle", color: "#f87171", spark: "errors", fmt: (v) => (v * 100).toFixed(1) + "%" },
  { key: "avg_latency_ms", label: "dash.avgLatency", icon: "clock", color: "#a78bfa", spark: "avg_latency_ms", fmt: (v) => fmtMs(v) },
  { key: "p95_latency_ms", label: "dash.p95", icon: "gauge", color: "#fbbf24", spark: null, fmt: (v) => fmtMs(v) },
  { key: "total_tokens", label: "dash.totalTokens", icon: "zap", color: "#38bdf8", spark: "tokens", fmt: (v) => v.toLocaleString() },
  { key: "total_cost", label: "dash.totalCost", icon: "dollar-sign", color: "#34d399", spark: "cost", fmt: (v) => "$" + v.toFixed(4) },
];

const AXIS = { stroke: "transparent", tick: { fill: "#5a6478", fontSize: 11 }, tickLine: false };

function Spark({ data, color }) {
  const w = 84, h = 26;
  if (!data || data.length < 2) return null;
  const vals = data.map((v) => (typeof v === "number" && isFinite(v) ? v : 0));
  const max = Math.max(...vals, 1);
  const step = w / (vals.length - 1);
  const pts = vals.map((v, i) =>
    (i * step).toFixed(1) + "," + (h - (v / max) * (h - 4) - 2).toFixed(1)
  );
  return (
    <svg width={w} height={h} className="spark" aria-hidden="true">
      <polygon points={`0,${h} ${pts.join(" ")} ${w},${h}`} fill={color} opacity="0.09" />
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth="1.5"
        strokeLinecap="round" strokeLinejoin="round" opacity="0.95" />
    </svg>
  );
}

const fmtMs = (ms) => (ms == null ? "—" : ms >= 1000 ? (ms / 1000).toFixed(1) + " s" : Math.round(ms) + " ms");
const latTone = (ms) => (ms < 3000 ? "fast" : ms < 10000 ? "mid" : "slow");

function ChartTip({ active, payload, label, fmt }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tip">
      <div className="chart-tip-label">{label}</div>
      {payload.filter((p) => p.value != null).map((p) => (
        <div key={p.dataKey} className="chart-tip-row">
          <span className="dot" style={{ background: p.color }} />
          <span>{p.name}</span>
          <b>{fmt ? fmt(p.value) : typeof p.value === "number" ? p.value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : p.value}</b>
        </div>
      ))}
    </div>
  );
}

function Legend({ items }) {
  return (
    <div className="legend-row">
      {items.map((i) => (
        <span key={i.label} className="legend-item">
          <span className="legend-dot" style={{ background: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  );
}

export default function Dashboard({ theme = "dark" }) {
  const lang = useLang();
  const [hours, setHours] = useState(24);
  const [auto, setAuto] = useState(() => localStorage.getItem("llmtrace_autorefresh") !== "0");
  const [updatedAt, setUpdatedAt] = useState(null);
  const [modelStats, setModelStats] = useState([]);
  const [slowest, setSlowest] = useState([]);
  const [breakdown, setBreakdown] = useState(null);
  const [overview, setOverview] = useState(null);
  const [series, setSeries] = useState([]);
  const [errClusters, setErrClusters] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const project = await ensureProject();
      const params = { hours, project_id: project.id };
      const [o, t, m, sl, lb, ec] = await Promise.all([
        api.get("/metrics/overview", { params }),
        api.get("/metrics/timeseries", { params }),
        api.get("/metrics/models", { params }),
        api.get("/metrics/slowest", { params }),
        api.get("/metrics/latency-breakdown", { params }),
        api.get("/metrics/errors", { params }),
      ]);
      setOverview(o.data);
      setModelStats(m.data);
      setSlowest(sl.data);
      setBreakdown(lb.data);
      setErrClusters(ec.data);
      setError(null);
      setUpdatedAt(Date.now());
      setSeries(t.data.map((p) => ({
        ...p,
        time: new Date(p.bucket).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
      })));
    } catch (e) {
      setError(String(e.response?.data?.detail || e.message));
    }
  }, [hours]);

  useEffect(() => { load(); }, [load]);

  // 自动刷新：每分钟拉一次；页面切到后台时暂停，避免无人看的时候白跑查询
  useEffect(() => {
    if (!auto) return undefined;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, 60000);
    return () => clearInterval(id);
  }, [auto, load]);

  const toggleAuto = () => {
    const next = !auto;
    localStorage.setItem("llmtrace_autorefresh", next ? "1" : "0");
    setAuto(next);
  };

  if (error) return <div className="empty"><Icon name="alert-triangle" size={22} />{t("dash.backendError")}: {error}</div>;

  const gridColor = theme === "light" ? "#e8ecf2" : "#151b26";
  const cursorColor = theme === "light" ? "#d7dce5" : "#273043";

  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("nav.dashboard")}</h1>
        <div className="head-actions">
          <div className="seg">
            {RANGES.map(([label, h]) => (
              <button key={h} className={hours === h ? "active" : ""} onClick={() => setHours(h)}>
                {label}
              </button>
            ))}
          </div>
          {updatedAt && (
            <span className="updated-at">
              {t("dash.updatedAt", { time: new Date(updatedAt).toLocaleTimeString("zh-CN") })}
            </span>
          )}
          <label className="wrapper-toggle auto-toggle" title={t("dash.autoRefreshHint")}>
            <input type="checkbox" checked={auto} onChange={toggleAuto} />
            {t("dash.autoRefresh")}
          </label>
          <button className="btn btn-ghost" onClick={load}>
            <Icon name="refresh" size={13} /> {t("dash.refresh")}
          </button>
        </div>
      </div>

      <div className="cards">
        {CARD_DEFS.map((c, idx) => (
          <div key={c.key} className="stat-card" style={{ "--i": idx }}>
            <div className="stat-top">
              <span className="stat-icon" style={{ color: c.color, background: c.color + "1c" }}>
                <Icon name={c.icon} size={14} />
              </span>
              <span className="stat-badge">{hours >= 24 ? hours / 24 + "d" : hours + "h"}</span>
            </div>
            <div className="stat-value">{overview ? c.fmt(overview[c.key]) : "—"}</div>
            <div className="stat-label-row">
              <span className="stat-label">{t(c.label)}</span>
              <Spark data={c.spark ? series.map((s) => s[c.spark]) : null} color={c.color} />
            </div>
          </div>
        ))}
      </div>

      <div className="charts">
        <div className="card chart-box glow-chart">
          <h3>{t("dash.callsErrors")}</h3>
          <div className="sub">{t("dash.callsErrorsSub")}</div>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={series} margin={{ top: 4, right: 10, bottom: 0, left: -22 }}>
              <CartesianGrid stroke={gridColor} strokeDasharray="4 6" vertical={false} />
              <XAxis dataKey="time" {...AXIS} tickMargin={8} />
              <YAxis {...AXIS} allowDecimals={false} />
              <Tooltip content={<ChartTip />} cursor={{ stroke: cursorColor, strokeDasharray: "4 4" }} />
              <Line type="monotone" dataKey="calls" name={t("dash.calls")} stroke="#4d8dff" strokeWidth={2} dot={false} activeDot={{ r: 3.5, strokeWidth: 0 }} />
              <Line type="monotone" dataKey="errors" name={t("dash.errors")} stroke="#f87171" strokeWidth={2} dot={false} activeDot={{ r: 3.5, strokeWidth: 0 }} />
            </LineChart>
          </ResponsiveContainer>
          <Legend items={[{ label: t("dash.calls"), color: "#4d8dff" }, { label: t("dash.errors"), color: "#f87171" }]} />
        </div>

        <div className="card chart-box">
          <h3>{t("dash.tokensCost")}</h3>
          <div className="sub">{t("dash.tokensCostSub")}</div>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={series} margin={{ top: 4, right: 10, bottom: 0, left: -22 }}>
              <defs>
                <linearGradient id="gTokens" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#a78bfa" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#a78bfa" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gCost" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#34d399" stopOpacity={0.32} />
                  <stop offset="100%" stopColor="#34d399" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={gridColor} strokeDasharray="4 6" vertical={false} />
              <XAxis dataKey="time" {...AXIS} tickMargin={8} />
              <YAxis yAxisId="l" {...AXIS} />
              <YAxis yAxisId="r" orientation="right" {...AXIS} />
              <Tooltip content={<ChartTip />} cursor={{ stroke: cursorColor, strokeDasharray: "4 4" }} />
              <Area yAxisId="l" type="monotone" dataKey="tokens" name="Token" stroke="#a78bfa" fill="url(#gTokens)" strokeWidth={2} activeDot={{ r: 3.5, strokeWidth: 0 }} />
              <Area yAxisId="r" type="monotone" dataKey="cost" name={t("dash.costUsd")} stroke="#34d399" fill="url(#gCost)" strokeWidth={2} activeDot={{ r: 3.5, strokeWidth: 0 }} />
            </AreaChart>
          </ResponsiveContainer>
          <Legend items={[{ label: "Token", color: "#a78bfa" }, { label: t("dash.costUsd"), color: "#34d399" }]} />
        </div>

        <div className="card chart-box">
          <div className="card-head-row">
            <div>
              <h3>{t("dash.latencyBreakdown")}</h3>
              <div className="sub">{t("dash.latencyBreakdownSub")}</div>
            </div>
            {overview && (
              <div className="lat-summ">
                <div>{t("dash.avgLatency")} <b className="mono">{fmtMs(overview.avg_latency_ms)}</b></div>
                <div>P95 <b className="mono">{fmtMs(overview.p95_latency_ms)}</b></div>
              </div>
            )}
          </div>
          {breakdown && breakdown.traces > 0 && breakdown.parts.some((p) => p.ms > 0) ? (
            <>
              <div className="lat-bar">
                {breakdown.parts.filter((p) => p.pct > 0).map((p) => (
                  <div key={p.key} className={"lat-seg " + p.key} style={{ width: p.pct + "%" }}
                    title={t("dash.part." + p.key) + " " + p.pct.toFixed(1) + "%"} />
                ))}
              </div>
              <div className="lat-legend">
                {breakdown.parts.map((p) => (
                  <div key={p.key} className="lat-row">
                    <span className={"lat-dot " + p.key} />
                    <span className="lat-name">{t("dash.part." + p.key)}</span>
                    <span className="lat-val mono">
                      {fmtMs(p.per_trace_ms)}<span className="lat-unit">{t("dash.perTrace")}</span>
                    </span>
                    <span className="lat-pct mono">{p.pct.toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="small-empty"><Icon name="clock" size={18} />{t("dash.noSlow")}</div>
          )}
        </div>

        <div className="card chart-box">
          <h3>{t("dash.slowest")}</h3>
          <div className="sub">{t("dash.slowestSub")} · {hours}h</div>
          {slowest.length ? (
            <div className="slow-list">
              {slowest.map((s) => (
                <Link key={s.id} to={"/traces/" + s.id} className="slow-row" title={s.name}>
                  <span className={"slow-lat " + latTone(s.latency_ms)}>
                    <Icon name="clock" size={11} />{fmtMs(s.latency_ms)}
                  </span>
                  <span className="slow-name">{s.name}</span>
                  <span className="slow-time">
                    {new Date(s.start_time).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
                  </span>
                </Link>
              ))}
            </div>
          ) : (
            <div className="small-empty"><Icon name="clock" size={18} />{t("dash.noSlow")}</div>
          )}
        </div>

        <div className="card chart-box">
          <h3>{t("dash.errorAnalysis")}</h3>
          <div className="sub">{t("dash.errorAnalysisSub")} · {hours}h</div>
          {errClusters.length ? (
            <div className="err-clusters">
              {errClusters.map((c, i) => (
                <Link key={i} to={"/traces?q=" + encodeURIComponent(c.search || c.error.slice(0, 60)) + "&status=error"}
                  className="err-cluster-row" title={c.error}>
                  <span className="err-count">{c.count}×</span>
                  <span className="err-text mono">{c.error.length > 90 ? c.error.slice(0, 90) + "…" : c.error}</span>
                  <span className="err-seen">{new Date(c.last_seen).toLocaleTimeString("zh-CN")}</span>
                </Link>
              ))}
            </div>
          ) : (
            <div className="small-empty">
              <Icon name="check" size={18} />
              {overview && overview.total_errors > 0 ? t("dash.noErrorsInRange") : t("dash.noErrors")}
            </div>
          )}
        </div>

        <div className="card chart-box">
          <h3>{t("dash.modelUsage")}</h3>
          <div className="sub">{t("dash.modelUsageSub")}</div>
          {modelStats.length ? (
            <table className="table model-table">
              <thead>
                <tr><th>{t("dash.model")}</th><th className="num">{t("dash.calls")}</th><th className="num">{t("th.tokens")}</th><th className="num">{t("dash.latencySpeed")}</th><th className="num">{t("th.cost")}</th><th style={{ width: "26%" }}>{t("dash.costShare")}</th></tr>
              </thead>
              <tbody>
                {modelStats.map((s) => {
                  const maxCost = Math.max(...modelStats.map((x) => x.cost), 1e-9);
                  return (
                    <tr key={s.model}>
                      <td style={{ fontWeight: 550 }}>{s.model}</td>
                      <td className="num">{s.calls}</td>
                      <td className="num">{s.total_tokens.toLocaleString()}</td>
                      <td className="num">
                        <div>{fmtMs(s.avg_latency_ms)}</div>
                        {s.output_tps > 0 && <div className="cell-sub">{Math.round(s.output_tps)} tok/s</div>}
                      </td>
                      <td className="num">${s.cost.toFixed(4)}</td>
                      <td>
                        <div style={{ background: "var(--bg-elevated)", borderRadius: 4, height: 8, overflow: "hidden" }}>
                          <div style={{ width: (s.cost / maxCost) * 100 + "%", height: "100%", background: "linear-gradient(90deg,#4d8dff,#7c5cff)" }} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <div className="empty"><Icon name="sparkle" size={22} />暂无 LLM 调用数据</div>
          )}
        </div>

      </div>
    </div>
  );
}
