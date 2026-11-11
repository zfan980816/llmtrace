import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api from "../api";
import { addFeedback, listFeedback, deleteFeedback } from "../feedbackApi";
import Icon from "../components/Icon";
import JsonBlock from "../components/JsonBlock";
import StatusIcon from "../components/StatusIcon";
import Markdown from "../components/Markdown";
import MessagesView, { messagesOf, normalizeMessages } from "../components/MessagesView";
import { t, useLang } from "../i18n";

const TYPE_META = {
  llm: { icon: "sparkle", color: "#a78bfa", label: "LLM" },
  tool: { icon: "wrench", color: "#34d399", label: "工具" },
  retrieval: { icon: "search", color: "#818cf8", label: "检索" },
  agent: { icon: "bot", color: "#fbbf24", label: "Agent" },
  chain: { icon: "git-branch", color: "#64748b", label: "链" },
};

function fmtLatency(ms) {
  if (ms == null) return "—";
  return ms >= 1000 ? (ms / 1000).toFixed(2) + " s" : ms + " ms";
}

function fmtTokens(n) {
  if (!n) return null;
  return n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 3).replace(/\.?0+$/, "") + "K" : String(n);
}

export function latClass(ms) {
  if (ms == null) return "";
  if (ms < 3000) return "fast";
  if (ms < 10000) return "mid";
  return "slow";
}

function asObjectText(v) {
  if (v == null) return "";
  if (typeof v === "string") return v;
  try { return JSON.stringify(v, null, 2); } catch { return String(v); }
}

function looksLikeError(output) {
  return output && typeof output === "object" && "error" in output;
}

export default function TraceDetail() {
  const lang = useLang();
  const { id } = useParams();
  const [trace, setTrace] = useState(null);
  const [selected, setSelected] = useState(null);
  const [tab, setTab] = useState("input");
  const [error, setError] = useState(null);
  const [collapsed, setCollapsed] = useState(() => new Set());
  const [fbs, setFbs] = useState([]);

  const [fbBusy, setFbBusy] = useState(false);
  const [fbDraft, setFbDraft] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/traces/" + id);
        setTrace(r.data);
        const root = r.data.spans.find((s) => !s.parent_span_id);
        setSelected((root || r.data.spans[0] || {}).id || null);
      } catch (e) {
        setError(String(e.response?.data?.detail || e.message));
        return;
      }
      try {
        const r = await listFeedback(id);
        setFbs(r.data);
      } catch { /* feedback optional */ }
    })();
  }, [id]);

  const submitFeedback = async (score) => {
    setFbBusy(true);
    try {
      await addFeedback({ trace_id: id, score, comment: fbDraft || null });
      setFbDraft("");
      const r = await listFeedback(id);
      setFbs(r.data);
    } catch { /* ignore */ }
    setFbBusy(false);
  };

  const removeFeedback = async (fid) => {
    try {
      await deleteFeedback(fid);
      setFbs((prev) => prev.filter((f) => f.id !== fid));
    } catch { /* ignore */ }
  };

  const tree = useMemo(() => {
    if (!trace) return [];
    const byParent = {};
    const hasKids = new Set();
    for (const s of trace.spans) {
      if (s.parent_span_id) hasKids.add(s.parent_span_id);
      const key = s.parent_span_id || "__root__";
      (byParent[key] = byParent[key] || []).push(s);
    }
    const rows = [];
    const walk = (list, depth) => {
      for (const s of list) {
        rows.push({ span: s, depth, expandable: hasKids.has(s.id) });
        if (!collapsed.has(s.id)) walk(byParent[s.id] || [], depth + 1);
      }
    };
    walk(byParent["__root__"] || [], 0);
    return rows;
  }, [trace, collapsed]);

  const toggleNode = (id) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  if (error) return <div className="empty"><Icon name="alert-triangle" size={22} />{t("common.loadFailed")}: {error}</div>;
  if (!trace) return <div className="empty">{t("common.loadingShort")}</div>;

  const sel = trace.spans.find((s) => s.id === selected) || trace.spans[0];
  const selMeta = TYPE_META[sel.span_type] || TYPE_META.chain;
  const inMsgs = normalizeMessages(sel.input);
  const outMsgs = normalizeMessages(sel.output);
  const llmPair = sel.span_type === "llm" && inMsgs;
  const chatText = sel.input != null && typeof sel.input !== "object";
  const selTotalTokens = (sel.prompt_tokens || 0) + (sel.completion_tokens || 0);

  const TABS = [
    ["feedback", t("tab.feedback")],
    ["input", t("tab.input")],
    ["output", t("tab.output")],
    ["raw", t("tab.raw")],
  ];
  const upCount = fbs.filter((f) => f.score === 1).length;
  const downCount = fbs.filter((f) => f.score === -1).length;

  return (
    <div className="page trace-page">
      <div className="page-head">
        <div>
          <Link to="/traces"><Icon name="arrow-left" size={12} /> {t("detail.backToList")}</Link>
          <h1 style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
            <StatusIcon status={trace.status} />
            {trace.name}
          </h1>
          <p className="muted small">
            {new Date(trace.start_time).toLocaleString("zh-CN")} · {fmtLatency(trace.latency_ms)} ·{" "}
            {trace.total_tokens.toLocaleString()} tokens · ${trace.cost.toFixed(5)}
            {trace.session_id && (
              <>
                {" · " + t("detail.session") + " "}
                <Link to={"/sessions/" + encodeURIComponent(trace.session_id)}>{trace.session_id}</Link>
              </>
            )}
          </p>
        </div>
      </div>

      <div className="split">
        <div className="tree">
          {tree.map(({ span: s, depth, expandable }) => {
            const meta = TYPE_META[s.span_type] || TYPE_META.chain;
            const tk = fmtTokens((s.prompt_tokens || 0) + (s.completion_tokens || 0));
            const isOpen = !collapsed.has(s.id);
            return (
              <div
                key={s.id}
                className={"tree-row two-line" + (s.id === selected ? " selected" : "") + (s.status === "error" ? " errored" : "")}
                style={{ paddingLeft: 8 + depth * 18 }}
                onClick={() => setSelected(s.id)}
              >
                <button
                  className={"tree-caret" + (expandable ? "" : " invisible")}
                  onClick={(e) => { e.stopPropagation(); if (expandable) toggleNode(s.id); }}
                  title={isOpen ? "折叠" : "展开"}
                >
                  <Icon name={isOpen ? "arrow-left" : "arrow-left"} size={11}
                    style={{ transform: isOpen ? "rotate(-90deg)" : "none", transition: "transform .15s" }} />
                </button>
                <div className="tree-main">
                  <div className="tree-line1">
                    <span className="icon" style={{ color: meta.color }} title={meta.label}>
                      <Icon name={meta.icon} size={13} />
                    </span>
                    <span className="tree-name" title={s.name}>{s.name}</span>
                  </div>
                  <div className="tree-line2">
                    <span className={"lat-chip " + latClass(s.latency_ms)}><Icon name="clock" size={10} /> {fmtLatency(s.latency_ms)}</span>
                    {tk && <span className="tok-chip"><Icon name="zap" size={10} /> {tk}</span>}
                    {s.model && <span className="model-chip">{s.model}</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {sel && (
          <div className="detail-panel">
            <div className="detail-title">
              <span className="icon" style={{ color: selMeta.color }}><Icon name={selMeta.icon} size={17} /></span>
              {sel.name}
              <span className="detail-title-id mono">ID {sel.id.slice(0, 8)}</span>
            </div>
            <div className="detail-chips">
              <span className="chip">{selMeta.label}</span>
              {sel.model && <span className="chip">{sel.model}</span>}
              <span className={"chip " + sel.status}>{sel.status}</span>
              <span className={"chip lat-chip " + latClass(sel.latency_ms)}>{fmtLatency(sel.latency_ms)}</span>
              {selTotalTokens > 0 && <span className="chip">tokens {selTotalTokens.toLocaleString()}</span>}
              {sel.cost > 0 && <span className="chip">${sel.cost.toFixed(5)}</span>}
            </div>

            {sel.error && (
              <div className="error-banner">
                <Icon name="alert-triangle" size={14} />
                <span className="mono">{sel.error}</span>
              </div>
            )}

            <div className="detail-tabs">
              {TABS.map(([v, label]) => (
                <button key={v} className={tab === v ? "active" : ""} onClick={() => setTab(v)}>{label}</button>
              ))}
            </div>

            {tab === "feedback" && (
              <div className="feedback-pane">
                <div className="fb-actions">
                  <button className="fb-btn up" disabled={fbBusy} onClick={() => submitFeedback(1)}>
                    <Icon name="check" size={13} /> {t("fb.accurate")} ({upCount})
                  </button>
                  <button className="fb-btn down" disabled={fbBusy} onClick={() => submitFeedback(-1)}>
                    <Icon name="x" size={13} /> {t("fb.wrong")} ({downCount})
                  </button>
                </div>
                <textarea
                  placeholder={t("fb.placeholder")}
                  value={fbDraft}
                  onChange={(e) => setFbDraft(e.target.value)}
                  rows={2}
                />
                <div className="fb-list">
                  {fbs.map((f) => (
                    <div key={f.id} className={"fb-item " + (f.score === 1 ? "fb-up" : "fb-down")}>
                      <span className="fb-score">{f.score === 1 ? "👍" : "👎"}</span>
                      <div className="fb-main">
                        <div className="fb-meta">
                          {f.user_name || "匿名"} · {new Date(f.created_at).toLocaleString("zh-CN")}
                        </div>
                        {f.comment && <div className="fb-comment">{f.comment}</div>}
                      </div>
                      <button className="fb-del" title="删除" onClick={() => removeFeedback(f.id)}>
                        <Icon name="trash" size={12} />
                      </button>
                    </div>
                  ))}
                  {!fbs.length && <div className="muted small" style={{ padding: "6px 2px" }}>{t("fb.empty")}</div>}
                </div>
              </div>
            )}
            <div className="detail-body" style={tab === "feedback" ? { display: "none" } : undefined}>
              {tab === "input" && (
                llmPair ? <MessagesView messages={inMsgs} outputMessage={outMsgs ? outMsgs[outMsgs.length - 1] : null} /> :
                chatText ? <div className="chat-block"><Markdown text={asObjectText(sel.input)} /></div> :
                <JsonBlock title={null} icon="terminal" value={sel.input} />
              )}
              {tab === "output" && (
                looksLikeError(sel.output) ? <JsonBlock title={null} icon="alert-triangle" value={sel.output} /> :
                llmPair && outMsgs ? <MessagesView messages={outMsgs} /> :
                chatText || (sel.output != null && typeof sel.output === "string") ? <div className="chat-block"><Markdown text={asObjectText(sel.output)} /></div> :
                <JsonBlock title={null} icon="message-square" value={sel.output} />
              )}
              {tab === "raw" && (
                <div className="raw-json">
                  <JsonBlock title="Input" icon="terminal" value={sel.input} />
                  <JsonBlock title="Output" icon="message-square" value={sel.output} />
                  {sel.meta && (
                    <details className="raw-meta">
                      <summary>Metadata</summary>
                      <JsonBlock title={null} icon="layers" value={sel.meta} />
                    </details>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
