import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
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

// 输入/输出分区（LangSmith 式可折叠 section）
function IoSection({ label, children }) {
  return (
    <details className="io-sec" open>
      <summary>{label}</summary>
      <div className="io-sec-body">{children}</div>
    </details>
  );
}

export default function TraceDetail() {
  const lang = useLang();
  const navigate = useNavigate();
  const location = useLocation();
  const { id } = useParams();
  const [trace, setTrace] = useState(null);
  const [selected, setSelected] = useState(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState("input");
  const [showWrappers, setShowWrappers] = useState(false);
  const [error, setError] = useState(null);
  const [collapsed, setCollapsed] = useState(() => new Set());
  const [fbs, setFbs] = useState([]);

  const [fbBusy, setFbBusy] = useState(false);
  const [fbFormOpen, setFbFormOpen] = useState(false);
  const [fbScore, setFbScore] = useState(1);
  const [shareHint, setShareHint] = useState(null);
  const [fbDraft, setFbDraft] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/traces/" + id);
        setTrace(r.data);
        const root = r.data.spans.find((s) => !s.parent_span_id);
        // 支持用 ?span=<id> 直接打开某个环节，方便把链接发给同事
        const wanted = searchParams.get("span");
        const first = (wanted && r.data.spans.find((s) => s.id === wanted)) || root || r.data.spans[0] || {};
        setSelected(first.id || null);
        const sel0 = first;
        const hasMsgs = sel0 && (normalizeMessages(sel0.input) || normalizeMessages(sel0.output));
        setTab(hasMsgs && hasMsgs.length ? "input" : sel0?.input != null ? "input" : "feedback");
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

  // 单条请求的耗时构成：独占时间 = 自身时长 - 子节点时长，避免包装层重复计数
  const traceBreakdown = useMemo(() => {
    if (!trace) return null;
    const childSum = {};
    for (const s of trace.spans) {
      if (s.parent_span_id && s.latency_ms) {
        childSum[s.parent_span_id] = (childSum[s.parent_span_id] || 0) + s.latency_ms;
      }
    }
    const tot = { llm: 0, tool: 0, other: 0 };
    for (const s of trace.spans) {
      const own = Math.max(0, (s.latency_ms || 0) - (childSum[s.id] || 0));
      if (s.span_type === "llm" || s.span_type === "embedding") tot.llm += own;
      else if (s.span_type === "tool" || s.span_type === "retrieval") tot.tool += own;
      else tot.other += own;
    }
    const total = tot.llm + tot.tool + tot.other;
    return {
      total,
      parts: ["llm", "tool", "other"].map((k) => ({ key: k, ms: tot[k], pct: total ? (tot[k] / total) * 100 : 0 })),
    };
  }, [trace]);

  const selectSpan = (sid) => {
    setSelected(sid);
    // 用 replace 而不是 push：切换环节不产生历史记录，返回键仍然回到列表
    setSearchParams({ span: sid }, { replace: true });
  };

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
  // 输出区只显示 output 里新增的消息：root span 的 output.messages 是完整最终 state
  // （以 input 为前缀），去掉前缀避免和输入区重复
  const outOnly = (() => {
    if (!hasOutMsgs) return null;
    if (!hasInMsgs) return outMsgs;
    const sig = (m) => {
      const r = m.role || m.type;
      const norm = r === "human" ? "user" : r === "ai" ? "assistant" : r;
      return JSON.stringify([norm, m.content]);
    };
    if (outMsgs.length >= inMsgs.length) {
      const inSigs = inMsgs.map(sig);
      const head = outMsgs.slice(0, inMsgs.length).map(sig);
      if (head.every((s, i) => s === inSigs[i])) return outMsgs.slice(inMsgs.length);
    }
    return outMsgs;
  })();
  // 工具返回值去壳：{output:{content,...}} / {content:...} 直接取 content 文本
  const outDisplay = (() => {
    if (sel.span_type !== "tool") return sel.output;
    let o = sel.output;
    if (o && typeof o === "object" && "output" in o) o = o.output;
    if (o && typeof o === "object" && o !== null && typeof o.content === "string") return o.content;
    return o;
  })();
  const chatText = sel.input != null && typeof sel.input !== "object";
  const inPreview = (v, max = 34) => {
    if (v == null) return null;
    // tools 节点的 input 是 tool_calls 数组：直接显示被调用的工具名
    const callList = Array.isArray(v) ? v
      : (typeof v === "object" && Object.keys(v).length === 1 && Array.isArray(Object.values(v)[0]) ? Object.values(v)[0] : null);
    if (callList) {
      const names = callList.map((x) => x?.name || x?.function?.name).filter(Boolean);
      if (names.length) return names.join(", ");
    }
    if (typeof v !== "object") return null;
    const parts = Object.entries(v).slice(0, 2).map(([k, val]) => {
      const s = typeof val === "string" ? val : JSON.stringify(val);
      return k + "=" + (s.length > 18 ? s.slice(0, 18) + "…" : s);
    });
    if (!parts.length) return null;
    const s = parts.join(" ");
    return s.length > max ? s.slice(0, max) + "…" : s;
  };
  const selTotalTokens = (sel.prompt_tokens || 0) + (sel.completion_tokens || 0);

  const TABS = [
    ["feedback", t("tab.feedback")],
    ["input", t("tab.input")],
    ["output", t("tab.output")],
    ["meta", t("tab.meta")],
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
          {traceBreakdown && traceBreakdown.total > 0 && (
            <div className="trace-lat">
              <span className="trace-lat-bar">
                {traceBreakdown.parts.filter((p) => p.pct > 0).map((p) => (
                  <span key={p.key} className={"lat-seg " + p.key} style={{ width: p.pct + "%" }} />
                ))}
              </span>
              {traceBreakdown.parts.map((p) => (
                <span key={p.key} className="trace-lat-part">
                  <span className={"lat-dot " + p.key} />
                  {t("dash.part." + p.key)} {fmtLatency(p.ms)}
                </span>
              ))}
            </div>
          )}
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
                onClick={() => selectSpan(s.id)}
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
            {sel.span_type === "tool" && TOOL_DOCS[sel.name] && (
              <p className="detail-desc">{TOOL_DOCS[sel.name][lang === "en" ? 1 : 0]}</p>
            )}

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
            )}
            <div className="detail-body" style={tab === "feedback" ? { display: "none" } : undefined}>
              {tab === "input" && (
                <div>
                  <IoSection label={t("io.input")}>
                    {hasInMsgs ? <MessagesView messages={inMsgs} /> :
                      chatText ? <div className="chat-block"><Markdown text={asObjectText(sel.input)} /></div> :
                      <JsonBlock title={null} icon="terminal" value={sel.input} />}
                  </IoSection>
                  <IoSection label={t("io.output")}>
                    {looksLikeError(sel.output) ? <JsonBlock title={null} icon="alert-triangle" value={sel.output} /> :
                      hasOutMsgs ? <MessagesView messages={outOnly && outOnly.length ? outOnly : outMsgs} /> :
                      typeof outDisplay === "string" ? <div className="chat-block"><Markdown text={outDisplay} /></div> :
                      <JsonBlock title={null} icon="message-square" value={outDisplay} />}
                  </IoSection>
                </div>
              )}
              {tab === "output" && (
                looksLikeError(sel.output) ? <JsonBlock title={null} icon="alert-triangle" value={sel.output} /> :
                hasOutMsgs ? <MessagesView messages={outMsgs} /> :
                typeof outDisplay === "string" ? <div className="chat-block"><Markdown text={outDisplay} /></div> :
                <JsonBlock title={null} icon="message-square" value={outDisplay} />
              )}
              {tab === "meta" && (
                <div className="attr-list">
                  {[
                    ["类型", selMeta.label],
                    ["状态", sel.status],
                    ["延迟", fmtLatency(effLatency.get(sel.id) ?? sel.latency_ms)],
                    sel.model ? ["模型", sel.model] : null,
                    selTotalTokens > 0 ? ["Tokens", selTotalTokens.toLocaleString()] : null,
                    sel.cost > 0 ? ["费用", "$" + sel.cost.toFixed(5)] : null,
                    ...(() => {
                      // 嵌套对象/JSON 字符串展开成 a.b 键，便于阅读
                      const rows = [];
                      const walk = (prefix, v) => {
                        if (typeof v === "string" && /^\s*[\[{]/.test(v)) {
                          try { v = JSON.parse(v); } catch { /* keep string */ }
                        }
                        if (v && typeof v === "object" && !Array.isArray(v)) {
                          for (const [k2, v2] of Object.entries(v)) walk(prefix + "." + k2, v2);
                        } else {
                          rows.push([prefix, typeof v === "object" ? JSON.stringify(v) : String(v)]);
                        }
                      };
                      for (const [k, v] of Object.entries(sel.meta || {})) walk(k, v);
                      return rows;
                    })(),
                  ].filter(Boolean).map(([k, v]) => (
                    <div key={k} className="kv-row">
                      <span className="kv-k mono">{k}</span>
                      <span className="kv-v mono">{v}</span>
                    </div>
                  ))}
                </div>
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
