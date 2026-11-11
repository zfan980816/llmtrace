// LangSmith 式消息视图：角色气泡 + 工具调用结构化展示 + Markdown 渲染
import Icon from "./Icon";
import Markdown from "./Markdown";

const ROLE_META = {
  system: { icon: "layers", color: "#22c55e", label: "System" },
  user: { icon: "user", color: "#3b82f6", label: "User" },
  human: { icon: "user", color: "#3b82f6", label: "User" },
  assistant: { icon: "sparkle", color: "#f59e0b", label: "AI" },
  ai: { icon: "sparkle", color: "#f59e0b", label: "AI" },
  tool: { icon: "wrench", color: "#10b981", label: "Tool" },
};

function toolArgs(m) {
  try {
    const raw = m.tool_calls?.[0]?.function?.arguments;
    if (!raw) return null;
    return typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch { return null; }
}

export function normalizeMessages(input) {
  if (Array.isArray(input)) {
    return input.map((m) => (typeof m === "string" ? { role: "user", content: m } : m));
  }
  if (input && Array.isArray(input.messages)) return input.messages;
  if (input && typeof input === "object" && input.role) return [input];
  return null;
}

export function messagesOf(input, output) {
  const inMsgs = normalizeMessages(input);
  if (inMsgs && inMsgs.length) return inMsgs;
  const outMsgs = normalizeMessages(output);
  if (outMsgs && outMsgs.length) return outMsgs;
  return null;
}

function ToolCallCard({ tc, idx }) {
  let args = null;
  try {
    args = typeof tc.function?.arguments === "string" ? JSON.parse(tc.function.arguments) : tc.function?.arguments;
  } catch { /* raw string */ }
  return (
    <div className="tool-call-card">
      <div className="tc-head"><Icon name="wrench" size={13} /> <span className="tc-name">{tc.function?.name || "tool"}</span></div>
      {args && typeof args === "object" && (
        <div className="tc-args">
          {Object.entries(args).map(([k, v]) => (
            <div key={k} className="tc-arg"><span className="tc-key">{k}</span><span className="tc-val">{String(v)}</span></div>
          ))}
        </div>
      )}
      {args == null && tc.function?.arguments && <div className="tc-args mono">{String(tc.function.arguments)}</div>}
    </div>
  );
}

export default function MessagesView({ messages, outputMessage }) {
  // 消息列表；outputMessage 作为最后一条追加（LangSmith 的 Input tab 会把历史 + AI 回复连起来）
  const list = [...(messages || []), ...(outputMessage ? [outputMessage] : [])];
  // tool_call_id → 工具名映射，供 tool 消息标注
  const toolNames = {};
  for (const m of list) {
    for (const tc of m.tool_calls || []) toolNames[tc.id] = tc.function?.name;
  }
  return (
    <div className="messages">
      {list.map((m, i) => {
        const meta = ROLE_META[m.role] || ROLE_META.user;
        const content = typeof m.content === "string" ? m.content
          : Array.isArray(m.content) ? m.content.map((c) => c.text || JSON.stringify(c)).join("\n")
          : m.content ? JSON.stringify(m.content, null, 2) : "";
        if (m.role === "tool" || m.name) {
          return (
            <div key={i} className="msg-card tool-msg">
              <div className="msg-head" style={{ color: meta.color }}>
                <Icon name={meta.icon} size={13} />
                <span className="msg-role">{m.name || toolNames[m.tool_call_id] || "Tool"}</span>
              </div>
              <Markdown text={content} />
            </div>
          );
        }
        return (
          <div key={i} className="msg-card">
            <div className="msg-head" style={{ color: meta.color }}>
              <span className="msg-icon" style={{ background: meta.color }}><Icon name={meta.icon} size={11} /></span>
              <span className="msg-role">{meta.label}</span>
            </div>
            <Markdown text={content} />
            {(m.tool_calls || []).map((tc, n) => <ToolCallCard key={n} tc={tc} idx={n} />)}
          </div>
        );
      })}
    </div>
  );
}
