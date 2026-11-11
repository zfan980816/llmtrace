import { useState } from "react";
import Icon from "./Icon";

const ROLE_COLORS = {
  system: "#c4b5fd",
  user: "#93c5fd",
  human: "#93c5fd",
  assistant: "#6ee7b7",
  ai: "#6ee7b7",
  tool: "#fbbf24",
};

const isPrimitive = (v) =>
  v === null || ["string", "number", "boolean"].includes(typeof v);

const isMsg = (m) => m && typeof m === "object" && ("role" in m || "content" in m);

const isMessages = (v) =>
  Array.isArray(v) && v.length > 0 && v.every(isMsg);

/* ---------- primitives ---------- */

function ClampedText({ text, limit = 400 }) {
  const [open, setOpen] = useState(false);
  const long = text.length > limit;
  return (
    <div className="v-text">
      {open ? text : text.slice(0, limit) + "…"}
      {long && (
        <button className="link-btn" style={{ marginLeft: 8 }} onClick={() => setOpen(!open)}>
          {open ? "收起" : "展开全部"}
        </button>
      )}
    </div>
  );
}

function highlightJSON(text) {
  const nodes = [];
  const re = /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g;
  let last = 0, m, i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(<span key={i++}>{text.slice(last, m.index)}</span>);
    if (m[2] !== undefined) nodes.push(<span key={i++} className="j-k">{m[1]}</span>);
    else if (m[1] !== undefined) nodes.push(<span key={i++} className="j-s">{m[1]}</span>);
    else if (/true|false|null/.test(m[0])) nodes.push(<span key={i++} className="j-b">{m[0]}</span>);
    else nodes.push(<span key={i++} className="j-n">{m[0]}</span>);
    last = re.lastIndex;
  }
  if (last < text.length) nodes.push(<span key={i++}>{text.slice(last)}</span>);
  return nodes;
}

function JsonPre({ value, clampLimit = 1500 }) {
  const [open, setOpen] = useState(false);
  const text = JSON.stringify(value, null, 2);
  const long = text.length > clampLimit;
  const shown = open || !long ? text : text.slice(0, clampLimit) + "\n…";
  return (
    <div>
      <pre className="json-pre">{highlightJSON(shown)}</pre>
      {long && (
        <button className="link-btn" style={{ marginTop: 6 }} onClick={() => setOpen(!open)}>
          {open ? "收起" : "展开全部"}
        </button>
      )}
    </div>
  );
}

/* ---------- value renderer ---------- */

function MessageBubble({ m }) {
  const role = String(m.role || "msg").toLowerCase();
  const color = ROLE_COLORS[role] || "#9aa3b8";
  return (
    <div className="msg" style={{ borderLeftColor: color }}>
      <div className="msg-head">
        <span className="msg-role" style={{ color }}>{role.toUpperCase()}</span>
        {m.name ? <span className="msg-name">{m.name}</span> : null}
      </div>
      <div className="msg-content">{ValueView({ value: m.content })}</div>
    </div>
  );
}

function KeyValueRows({ obj }) {
  return (
    <div className="kv">
      {Object.entries(obj).map(([k, v]) => (
        <div className="kv-row" key={k}>
          <span className="kv-k">{k}</span>
          <span className="kv-v">{v === null ? "null" : String(v)}</span>
        </div>
      ))}
    </div>
  );
}

export function ValueView({ value }) {
  if (value === null || value === undefined) {
    return <span className="muted">（空）</span>;
  }
  if (typeof value === "string") {
    const s = value.trim();
    if ((s.startsWith("{") && s.endsWith("}")) || (s.startsWith("[") && s.endsWith("]"))) {
      try {
        return ValueView({ value: JSON.parse(s) });
      } catch { /* plain string */ }
    }
    return value.length > 240 ? <ClampedText text={value} /> : <span className="v-text">{value}</span>;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return <span className="v-text">{String(value)}</span>;
  }
  if (isMessages(value)) {
    return <div>{value.map((m, i) => <MessageBubble key={i} m={m} />)}</div>;
  }
  if (!Array.isArray(value) && typeof value === "object") {
    if (isMsg(value)) return <MessageBubble m={value} />;
    const entries = Object.entries(value);
    if (entries.length && entries.length <= 8 && entries.every(([, v]) => isPrimitive(v))) {
      return <KeyValueRows obj={value} />;
    }
    return <JsonPre value={value} />;
  }
  if (Array.isArray(value)) {
    if (value.every(isPrimitive) && value.length <= 10) {
      return (
        <div className="v-text">
          [{value.map((v) => (typeof v === "string" ? `"${v}"` : String(v))).join(", ")}]
        </div>
      );
    }
    return <JsonPre value={value} />;
  }
  return <JsonPre value={value} />;
}

function typeLabel(value) {
  if (value == null) return "";
  if (isMessages(value)) return "消息 " + value.length;
  if (isMsg(value)) return "消息";
  if (typeof value === "string") return "文本";
  return "JSON";
}

export default function JsonBlock({ title, icon, value }) {
  const [copied, setCopied] = useState(false);
  if (value == null) return null;

  const copy = () => {
    const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  };

  const label = typeLabel(value);

  return (
    <div className="detail-section">
      <h4>
        {icon && <Icon name={icon} size={12} />}
        {title}
        {label && <span className="chip" style={{ marginLeft: 2 }}>{label}</span>}
        <button className="copy-btn" onClick={copy} title="复制">
          <Icon name={copied ? "check" : "copy"} size={12} />
        </button>
      </h4>
      <ValueView value={value} />
    </div>
  );
}
