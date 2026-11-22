import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import api, { createShareLink } from "../api";
import { addFeedback, listFeedback, deleteFeedback } from "../feedbackApi";
import Icon from "../components/Icon";
import JsonBlock from "../components/JsonBlock";
import StatusIcon from "../components/StatusIcon";
import Markdown from "../components/Markdown";
import MessagesView, { messagesOf, normalizeMessages } from "../components/MessagesView";
import { t, useLang } from "../i18n";

// deepagents / LangGraph 的包装层 span：对排查无信息量，默认折叠隐藏
const WRAPPER_RE = /Middleware\.|wrap_model_call|wrap_tool_call|before_agent|after_agent|after_model|_ParentNotifier|PromptCaching|UnsupportedContent|ModelRefusal|Summarization/i;
const isWrapperSpan = (s) => WRAPPER_RE.test(s.name || "");

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
  const navigate = useNavigate();
  const location = useLocation();
  const { id } = useParams();
  const [trace, setTrace] = useState(null);
  const [selected, setSelected] = useState(null);
  const [tab, setTab] = useState("input");
  const [showWrappers, setShowWrappers] = useState(false);
  const [error, setError] = useState(null);
  const [collapsed, setCollapsed] = useState(() => new Set());
  const [fbs, setFbs] = useState([]);

  const [fbBusy, setFbBusy] = useState(false);
  const [shareHint, setShareHint] = useState(null);
  const [fbDraft, setFbDraft] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/traces/" + id);
        setTrace(r.data);
        const root = r.data.spans.find((s) => !s.parent_span_id);
        setSelected((root || r.data.spans[0] || {}).id || null);
        const sel0 = root || r.data.spans[0];
        const hasMsgs = sel0 && (normalizeMessages(sel0.input) || normalizeMessages(sel0.output));
        setTab(hasMsgs && hasMsgs.length ? "messages" : sel0?.input != null ? "input" : "feedback");
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

  const { tree, effLatency } = useMemo(() => {
    if (!trace) return { tree: [], effLatency: new Map() };
    const spans = trace.spans;
    const byId = new Map(spans.map((s) => [s.id, s]));
    const isWrapper = (s) => !showWrappers && isWrapperSpan(s);

    // 有效父级：包装层的子节点上提到最近的非包装祖先
    const effParent = new Map();
    for (const s of spans) {
      let p = s.parent_span_id || null;
      while (p) {
        const ps = byId.get(p);
        if (!ps) { p = null; break; }
        if (!isWrapper(ps)) break;
        p = ps.parent_span_id || null;
      }
      effParent.set(s.id, p);
    }
    // 根节点本身是包装层时，提升它的父级（无父级则保持根）
    const rootsRaw = spans.filter((s) => !effParent.get(s.id));

    const byParent = {};
    const hasKids = new Set();
    for (const s of spans) {
      if (isWrapper(s)) continue;
      const key = effParent.get(s.id) || "__root__";
      (byParent[key] = byParent[key] || []).push(s);
      if (key !== "__root__") hasKids.add(key);
    }

    // 时长兜底：span 自己 latency 为 0/缺失时，取直接子节点的 max(end)-min(start)
    const effLatency = new Map();
    const kidsOf = {};
    for (const s of spans) (kidsOf[s.parent_span_id || "__root__"] = kidsOf[s.parent_span_id || "__root__"] || []).push(s);
    const t = (v) => (v ? Date.parse(v) : NaN);
    for (const s of spans) {
      if (s.latency_ms) { effLatency.set(s.id, s.latency_ms); continue; }
      const kids = kidsOf[s.id] || [];
      let mn = Infinity, mx = -Infinity;
      for (const k of kids) {
        const a = t(k.start_time), b = t(k.end_time);
        if (!isNaN(a) && a < mn) mn = a;
        if (!isNaN(b) && b > mx) mx = b;
      }
      if (mx > mn) effLatency.set(s.id, Math.round(mx - mn));
    }

    const rows = [];
    const seen = new Set();
    const walk = (list, depth) => {
      for (const s of list) {
        if (seen.has(s.id)) continue;
        seen.add(s.id);
        rows.push({ span: s, depth, expandable: hasKids.has(s.id) });
        if (!collapsed.has(s.id)) walk(byParent[s.id] || [], depth + 1);
      }
    };
    walk(byParent["__root__"] || [], 0);
    return { tree: rows, effLatency };
  }, [trace, collapsed, showWrappers]);

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
  // 任何 span（不只是 llm）只要能解析出消息就用消息卡片渲染——LangSmith 式对话视图
  const hasInMsgs = !!(inMsgs && inMsgs.length);
  const hasOutMsgs = !!(outMsgs && outMsgs.length);
  const llmPair = hasInMsgs;
  // 对话视图：LangGraph 根 span 的 output.messages 通常是完整最终 state（以 input 为前缀），
  // 直接用；否则 input+output 拼接，避免重复显示历史
  const fullMsgs = (() => {
    if (!hasOutMsgs) return inMsgs;
    if (!hasInMsgs) return outMsgs;
    // 角色归一化：human/user、ai/assistant 视为同一角色，避免前缀比对失败导致历史重复
    const sig = (m) => {
      const r = m.role || m.type;
      const norm = r === "human" ? "user" : r === "ai" ? "assistant" : r;
      return JSON.stringify([norm, m.content]);
    };
    if (outMsgs.length >= inMsgs.length) {
      const inSigs = inMsgs.map(sig);
      const head = outMsgs.slice(0, inMsgs.length).map(sig);
      if (head.every((s, i) => s === inSigs[i])) return outMsgs;
    }
    return [...inMsgs, ...outMsgs];
  })();
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

  const onShare = async () => {
    setShareHint(null);
    try {
      const { share_token } = await createShareLink(id);
      const url = window.location.origin + "/share/" + share_token;
      await navigator.clipboard.writeText(url);
      setShareHint("链接已复制");
      setTimeout(() => setShareHint(null), 2500);
    } catch (e) {
      setShareHint(e.response?.data?.detail || "复制失败");
      setTimeout(() => setShareHint(null), 3000);
    }
  };

  return (
    <div className="page trace-page">
      <div className="page-head">
        <div>
          <Link to="/traces" onClick={(e) => {
              e.preventDefault();
              if (location.key !== "default") navigate(-1); else navigate("/traces");
            }}><Icon name="arrow-left" size={12} /> {t("detail.backToList")}</Link>
          <h1 style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
            <StatusIcon status={trace.status} />
            {trace.name}
          </h1>
          <p className="muted small">
            {new Date(trace.start_time).toLocaleString("zh-CN")} · {fmtLatency(trace.latency_ms || effLatency.get(trace.spans.find((s) => !s.parent_span_id)?.id) || 0)} ·{" "}
            {trace.total_tokens.toLocaleString()} tokens · ${trace.cost.toFixed(5)}
            {trace.session_id && (
              <>
                {" · " + t("detail.session") + " "}
                <Link to={"/sessions/" + encodeURIComponent(trace.session_id)}>{trace.session_id}</Link>
              </>
            )}
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, position: "relative" }}>
          {shareHint && <span style={{ fontSize: 12, color: "var(--muted)" }}>{shareHint}</span>}
          <button className="btn" onClick={onShare} title="生成只读分享链接">
            <Icon name="link" size={13} /> 分享
          </button>
        </div>
      </div>

      <div className="split">
        <div className="tree">
          <label className="wrapper-toggle" title="deepagents/LangGraph 的包装层 span，排查时通常无用">
            <input type="checkbox" checked={showWrappers}
              onChange={(e) => setShowWrappers(e.target.checked)} />
            显示中间件包装层
          </label>
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
                    <span className={"lat-chip " + latClass(s.latency_ms)}><Icon name="clock" size={10} /> {fmtLatency(effLatency.get(s.id) ?? s.latency_ms)}</span>
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
              <span className={"chip lat-chip " + latClass(sel.latency_ms)}>{fmtLatency(effLatency.get(sel.id) ?? sel.latency_ms)}</span>
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
                hasInMsgs || hasOutMsgs ? <MessagesView
                  messages={sel.span_type === "llm" ? (inMsgs || []) : (fullMsgs || [])}
                  outputMessage={sel.span_type === "llm" && hasOutMsgs ? outMsgs[outMsgs.length - 1] : null} /> :
                chatText ? <div className="chat-block"><Markdown text={asObjectText(sel.input)} /></div> :
                <JsonBlock title={null} icon="terminal" value={sel.input} />
              )}
              {tab === "output" && (
                looksLikeError(sel.output) ? <JsonBlock title={null} icon="alert-triangle" value={sel.output} /> :
                hasOutMsgs ? <MessagesView messages={outMsgs} /> :
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
