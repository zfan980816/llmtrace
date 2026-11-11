// 轻量 Markdown 渲染器：标题 / 无序有序列表 / 代码块 / 行内代码 / 粗体 / 斜体 / 链接 / 分隔线
import React from "react";

function inline(text, keyBase) {
  // 行内解析：`code`、**bold**、*italic*、[text](url)
  const nodes = [];
  let rest = text, k = 0;
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\([^)]+\))/;
  while (rest) {
    const m = rest.match(pattern);
    if (!m) { nodes.push(rest); break; }
    if (m.index > 0) nodes.push(rest.slice(0, m.index));
    const tok = m[0];
    if (tok.startsWith("`")) nodes.push(<code key={keyBase + k} className="md-code">{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("**")) nodes.push(<strong key={keyBase + k}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("[")) {
      const mm = tok.match(/\[([^\]]+)\]\(([^)]+)\)/);
      nodes.push(<a key={keyBase + k} href={mm[2]} target="_blank" rel="noreferrer">{mm[1]}</a>);
    } else nodes.push(<em key={keyBase + k}>{tok.slice(1, -1)}</em>);
    rest = rest.slice(m.index + tok.length); k++;
  }
  return nodes;
}

export default function Markdown({ text }) {
  if (!text) return null;
  const lines = String(text).split("\n");
  const blocks = [];
  let i = 0, key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const buf = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) { buf.push(lines[i]); i++; }
      i++;
      blocks.push(<pre key={key++} className="md-pre"><code>{buf.join("\n")}</code></pre>);
      continue;
    }
    if (/^#{1,4}\s/.test(line)) {
      const level = line.match(/^#+/)[0].length;
      const Tag = "h" + Math.min(level + 2, 6);
      blocks.push(<Tag key={key++} className={"md-h md-h" + level}>{inline(line.replace(/^#+\s*/, ""), "h" + key)}</Tag>);
      i++; continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { blocks.push(<hr key={key++} />); i++; continue; }
    if (/^\s*[-*+]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*+]\s+/, "")); i++;
      }
      blocks.push(<ul key={key++}>{items.map((it, n) => <li key={n}>{inline(it, "li" + key + n)}</li>)}</ul>);
      continue;
    }
    if (/^\s*\d+[.、]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+[.、]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.、]\s+/, "")); i++;
      }
      blocks.push(<ol key={key++}>{items.map((it, n) => <li key={n}>{inline(it, "ol" + key + n)}</li>)}</ol>);
      continue;
    }
    if (line.trim() === "") { i++; continue; }
    const buf = [line]; i++;
    while (i < lines.length && lines[i].trim() !== "" && !/^(#{1,4}\s|```|\s*[-*+]\s|\s*\d+[.、]\s)/.test(lines[i])) { buf.push(lines[i]); i++; }
    blocks.push(<p key={key++}>{inline(buf.join(" "), "p" + key)}</p>);
  }
  return <div className="md">{blocks}</div>;
}
