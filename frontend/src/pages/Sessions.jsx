import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { ensureProject } from "../api";
import Icon from "../components/Icon";
import { t, useLang } from "../i18n";

export default function Sessions() {
  useLang();
  const [project, setProject] = useState(null);
  const [sessions, setSessions] = useState([]);

  useEffect(() => { ensureProject().then(setProject).catch(() => {}); }, []);

  useEffect(() => {
    if (!project) return;
    api.get("/sessions", { params: { project_id: project.id } })
      .then((r) => setSessions(r.data))
      .catch(() => setSessions([]));
  }, [project]);

  return (
    <div className="page">
      <h1 style={{ marginBottom: 18 }}>{t("sess.title")}</h1>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>{t("sess.id")}</th>
              <th className="num">{t("sess.calls")}</th>
              <th className="num">{t("th.avgLatency")}</th>
              <th className="num">{t("th.tokens")}</th>
              <th className="num">{t("th.cost")}</th>
              <th>{t("sess.lastActivity")}</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.session_id}>
                <td><Link to={"/sessions/" + encodeURIComponent(s.session_id)}>{s.session_id}</Link></td>
                <td className="num">{s.trace_count}</td>
                <td className="num">{Math.round(s.avg_latency_ms)} ms</td>
                <td className="num">{s.total_tokens.toLocaleString()}</td>
                <td className="num">${s.total_cost.toFixed(5)}</td>
                <td className="muted">{new Date(s.last_seen).toLocaleString("zh-CN")}</td>
              </tr>
            ))}
            {!sessions.length && (
              <tr>
                <td colSpan={6}>
                  <div className="empty"><Icon name="message-square" size={22} />{t("sess.empty")}</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

