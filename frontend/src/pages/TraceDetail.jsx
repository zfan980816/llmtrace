import { useEffect, useMemo, useRef, useState } from "react";
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

// 常见工具说明：让 trace 里的 ls / glob 等工具名一眼可读
const TOOL_DOCS = {
  ls: ["列出目录下的文件", "List files in a directory"],
  glob: ["按模式匹配查找文件，如 *.py", "Find files matching a glob pattern"],
  grep: ["在文件内容中搜索文本", "Search text in file contents"],
  read_file: ["读取文件内容", "Read a file"],
  write_file: ["写入文件", "Write a file"],
  edit_file: ["编辑文件内容", "Edit a file"],
  task: ["派发子任务给子代理执行", "Dispatch a subtask to a sub-agent"],
  write_todos: ["维护任务清单", "Maintain a todo list"],
  web_search: ["搜索网页", "Search the web"],
  python_repl: ["执行 Python 代码", "Run Python code"],
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
  const [showWrappers, setShowWrappers] = useState(false);
  const [error, setError] = useState(null);
  const [collapsed, setCollapsed] = useState(() => new Set());
  const [fbs, setFbs] = useState([]);

  const [fbBusy, setFbBusy] = useState(false);
  const [fbFormOpen, setFbFormOpen] = useState(false);
  const [fbScore, setFbScore] = useState(1);
  const panelRef = useRef(null);

  useEffect(() => {
    setFbFormOpen(false);
    if (panelRef.current) panelRef.current.scrollTop = 0;
  }, [selected]);
  const [shareHint, setShareHint] = useState(null);
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

  const submitFeedback = async () => {
    setFbBusy(true);
    try {
      await addFeedback({ trace_id: id, score: fbScore, comment: fbDraft || null });
      setFbDraft("");
      setFbFormOpen(false);
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
  const llmPair = sel.span_type === "llm" && inMsgs;
  const chatText = sel.input != null && typeof sel.input !== "object";
  const selTotalTokens = (sel.prompt_tokens || 0) + (sel.completion_tokens || 0);

  const upCount = fbs.filter((f) => f.score === 1).length;
  const downCount = fbs.filter((f) => f.score === -1).length;

  const inPreview = (v, max = 30) => {
    if (v == null || typeof v !== "object") return null;
    const parts = Object.entries(v).slice(0, 2).map(([k, val]) => {
      const s = typeof val === "string" ? val : JSON.stringify(val);
      return k + "=" + (s.length > 16 ? s.slice(0, 16) + "…" : s);
    });
    if (!parts.length) return null;
    const s = parts.join(" ");
    return s.length > max ? s.slice(0, max) + "…" : s;
  };

  const isToolSpan = sel.span_type === "tool";
  const renderIO = (value, which) => {
    if (value == null) return <div className="muted small" style={{ padding: "4px 2px" }}>—</div>;
    // 工具的入参/返回值不是对话，不要误渲染成消息气泡
    const msgs = isToolSpan ? null : normalizeMessages(value);
    if (isToolSpan && Array.isArray(value) && value.every((x) => typeof x === "string")) {
      return (
        <div className="tool-out-list mono">
          {value.map((s, i) => <div key={i} className="tool-out-item">{s}</div>)}
        </div>
      );
    }
    if (looksLikeError(value)) return <JsonBlock title={null} icon="alert-triangle" value={value} />;
    if (msgs && msgs.length) return <MessagesView messages={msgs} />;
    if (typeof value === "string") return <div className="chat-block"><Markdown text={value} /></div>;
    if (typeof value === "object") {
      const keys = Object.keys(value);
      if (keys.length && keys.length <= 8 && keys.every((k) => typeof value[k] !== "object" || value[k] === null)) {
        return (
          <div className="kv-table">
            {keys.map((k) => (
              <div key={k} className="kv-row">
                <div className="kv-k mono">{k}</div>
                <div className="kv-v mono">{String(value[k])}</div>
              </div>
            ))}
          </div>
        );
      }
    }
    return <JsonBlock title={null} icon={which === "input" ? "terminal" : "message-square"} value={value} />;
  };

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
                    {s.span_type === "tool" && (() => {
                      const pv = inPreview(s.input);
                      return pv ? <span className="tree-io-preview">{pv}</span> : null;
                    })()}
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
          <div className="detail-panel" ref={panelRef}>
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
            {sel.span_type === "tool" && TOOL_DOCS[sel.name] && (
              <p className="detail-desc">{TOOL_DOCS[sel.name][lang === "en" ? 1 : 0]}</p>
            )}

            {sel.error && (
              <div className="error-banner">
                <Icon name="alert-triangle" size={14} />
                <span className="mono">{sel.error}</span>
              </div>
            )}

            <details className="detail-sec" open>
              <summary>Input</summary>
              <div className="sec-body">{renderIO(sel.input, "input")}</div>
            </details>

            <details className="detail-sec" open>
              <summary>Output</summary>
              <div className="sec-body">{renderIO(sel.output, "output")}</div>
            </details>

            {sel.meta && (
              <details className="detail-sec">
                <summary>Metadata</summary>
                <div className="sec-body"><JsonBlock title={null} icon="layers" value={sel.meta} /></div>
              </details>
            )}

            <details className="detail-sec fb-sec" open={fbs.length > 0}>
              <summary>
                {t("fb.section")}
                {fbs.length > 0 && <span className="sec-count">{fbs.length}</span>}
              </summary>
              <div className="sec-body">
                {!fbFormOpen ? (
                  <button className="fb-add" onClick={() => setFbFormOpen(true)}>
                    <Icon name="plus" size={13} /> {t("fb.add")}
                  </button>
                ) : (
                  <div className="fb-form">
                    <div className="fb-score-row">
                      <button type="button" className={"fb-pick up" + (fbScore === 1 ? " active" : "")} onClick={() => setFbScore(1)}>
                        <Icon name="check" size={13} /> {t("fb.correct")}
                      </button>
                      <button type="button" className={"fb-pick down" + (fbScore === -1 ? " active" : "")} onClick={() => setFbScore(-1)}>
                        <Icon name="x" size={13} /> {t("fb.incorrect")}
                      </button>
                    </div>
                    <textarea
                      placeholder={t("fb.placeholder")}
                      value={fbDraft}
                      onChange={(e) => setFbDraft(e.target.value)}
                      rows={2}
                    />
                    <div className="fb-form-actions">
                      <button className="btn sm" disabled={fbBusy} onClick={submitFeedback}>{t("fb.submit")}</button>
                      <button className="btn sm ghost" onClick={() => { setFbFormOpen(false); setFbDraft(""); }}>{t("fb.cancel")}</button>
                    </div>
                  </div>
                )}
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
                  {!fbs.length && !fbFormOpen && <div className="muted small" style={{ padding: "6px 2px" }}>{t("fb.empty")}</div>}
                </div>
              </div>
            </details>

            <details className="detail-sec">
              <summary>{t("detail.rawJson")}</summary>
              <div className="sec-body raw-json">
                <JsonBlock title="Input" icon="terminal" value={sel.input} />
                <JsonBlock title="Output" icon="message-square" value={sel.output} />
              </div>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}
