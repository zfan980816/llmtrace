import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { fetchSharedTrace } from "../api";
import Icon from "../components/Icon";
import JsonBlock from "../components/JsonBlock";
import MessagesView, { messagesOf, normalizeMessages } from "../components/MessagesView";
import StatusIcon from "../components/StatusIcon";

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

export default function SharedTrace() {
  const { token } = useParams();
  const [trace, setTrace] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("input");

  useEffect(() => {
    fetchSharedTrace(token)
      .then((t) => {
        setTrace(t);
        const root = t.spans.find((s) => !s.parent_span_id);
        setSelected((root || t.spans[0] || {}).id || null);
      })
      .catch((e) => setError(e.response?.data?.detail || "分享链接无效或已撤销"));
  }, [token]);

  if (error) {
    return (
      <div className="login-wrap">
        <div className="login-card" style={{ textAlign: "center" }}>
          <p style={{ margin: 0, color: "var(--muted)" }}>{error}</p>
        </div>
      </div>
    );
  }
  if (!trace) {
    return <div className="empty" style={{ paddingTop: 140 }}>加载中…</div>;
  }

  const span = trace.spans.find((s) => s.id === selected) || trace.spans[0] || {};
  const msgs = normalizeMessages(messagesOf(span) || trace.input || trace.output || {});
  const hasMsgs = msgs && msgs.length > 0;
  const inputText = span.input != null ? JSON.stringify(span.input, null, 2) : "";
  const outputText = span.output != null ? JSON.stringify(span.output, null, 2) : "";

  const tabs = [
    ...(hasMsgs ? [["messages", "对话"]] : []),
    ...(inputText ? [["input", "输入"]] : []),
    ...(outputText ? [["output", "输出"]] : []),
    ["raw", "Raw JSON"],
  ];

  return (
    <div className="page trace-page">
      <div className="page-head">
        <div>
          <p className="muted small" style={{ margin: 0, display: "flex", alignItems: "center", gap: 6 }}>
            <span className="logo-mark" style={{ display: "inline-flex", width: 22, height: 22, borderRadius: 6 }}>
              <Icon name="radar" size={13} />
            </span>
            LLMTrace · 只读分享
          </p>
          <h1 style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
            <StatusIcon status={trace.status} />
            {trace.name}
          </h1>
          <p className="muted small">
            {new Date(trace.start_time).toLocaleString("zh-CN")} · {fmtLatency(trace.latency_ms)} ·{" "}
            {trace.total_tokens.toLocaleString()} tokens
          </p>
        </div>
      </div>

      <div className="split">
        <div className="tree">
          {trace.spans.map((s) => {
            const meta = TYPE_META[s.span_type] || TYPE_META.chain;
            return (
              <button
                key={s.id}
                className="tree-row"
                style={{ ["--depth"]: 0, fontWeight: s.id === selected ? 600 : 400 }}
                onClick={() => setSelected(s.id)}
              >
                <span style={{ color: meta.color }}><Icon name={meta.icon} size={13} /></span>
                <span className="tree-name" style={{ flex: 1, textAlign: "left" }}>{s.name}</span>
                <span className="muted small">{fmtLatency(s.latency_ms)}</span>
              </button>
            );
          })}
        </div>

        <div className="detail">
          <div className="detail-tabs">
            {tabs.map(([key, label]) => (
              <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>
            ))}
          </div>
          <div className="detail-body">
            {tab === "messages" && <MessagesView messages={msgs} />}
            {tab === "input" && <JsonBlock value={span.input} />}
            {tab === "output" && <JsonBlock value={span.output} />}
            {tab === "raw" && <JsonBlock value={{ span, trace: { name: trace.name, session_id: trace.session_id, metadata: trace.meta } }} />}
          </div>
        </div>
      </div>
    </div>
  );
}
