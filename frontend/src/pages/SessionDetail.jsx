import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api, { ensureProject } from "../api";
import Icon from "../components/Icon";
import StatusIcon from "../components/StatusIcon";

export default function SessionDetail() {
  const { sessionId } = useParams();
  const [project, setProject] = useState(null);
  const [traces, setTraces] = useState([]);

  useEffect(() => { ensureProject().then(setProject).catch(() => {}); }, []);

  useEffect(() => {
    if (!project) return;
    api.get("/sessions/" + encodeURIComponent(sessionId), { params: { project_id: project.id } })
      .then((r) => setTraces(r.data))
      .catch(() => setTraces([]));
  }, [project, sessionId]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <Link to="/sessions"><Icon name="arrow-left" size={12} /> 返回会话列表</Link>
          <h1 style={{ marginTop: 8 }}>会话 {sessionId}</h1>
          <p className="muted small">{traces.length} 条调用</p>
        </div>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: 34 }}></th>
              <th>名称</th>
              <th>开始时间</th>
              <th className="num">延迟</th>
              <th className="num">Token</th>
              <th className="num">成本</th>
            </tr>
          </thead>
          <tbody>
            {traces.map((t) => (
              <tr key={t.id}>
                <td><StatusIcon status={t.status} /></td>
                <td><Link to={"/traces/" + t.id}>{t.name}</Link></td>
                <td className="muted">{new Date(t.start_time).toLocaleString("zh-CN")}</td>
                <td className="num">{t.latency_ms} ms</td>
                <td className="num">{t.total_tokens.toLocaleString()}</td>
                <td className="num">${t.cost.toFixed(5)}</td>
              </tr>
            ))}
            {!traces.length && (
              <tr>
                <td colSpan={6}>
                  <div className="empty"><Icon name="inbox" size={22} />加载中…</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

