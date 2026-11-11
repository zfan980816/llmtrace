import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import api, { createProject, ensureProject, fetchMe, logout, onProjectChange, resetProject, setToken, switchProject } from "./api";
import { AuthContext } from "./auth";
import Icon from "./components/Icon";
import { t, setLang, useLang } from "./i18n";
import Alerts from "./pages/Alerts";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import SessionDetail from "./pages/SessionDetail";
import Sessions from "./pages/Sessions";
import TraceDetail from "./pages/TraceDetail";
import Traces from "./pages/Traces";
import Users from "./pages/Users";
import TeamGate from "./pages/TeamGate";

const ROLE_LABELS = { admin: "role.admin", member: "role.member", viewer: "role.viewer" };

export default function App() {
  const lang = useLang();
  const [user, setUser] = useState(undefined); // undefined=加载中, null=未登录
  const [theme, setTheme] = useState(() => localStorage.getItem("llmtrace_theme") || "light");
  const [projects, setProjects] = useState([]);
  const [current, setCurrent] = useState(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("llmtrace_theme", theme);
  }, [theme]);

  useEffect(() => {
    const token = localStorage.getItem("llmtrace_token");
    if (!token) {
      setUser(null);
      return;
    }
    fetchMe().then(setUser).catch(() => {
      setToken(null);
      setUser(null);
    });
    const onUnauthorized = () => {
      setToken(null);
      setUser(null);
    };
    window.addEventListener("llmtrace:unauthorized", onUnauthorized);
    return () => window.removeEventListener("llmtrace:unauthorized", onUnauthorized);
  }, []);

  useEffect(() => {
    if (!user) return;
    (async () => {
      try {
        const p = await ensureProject();
        setCurrent(p);
        const { data } = await api.get("/projects");
        setProjects(data);
      } catch {
        /* handled by 401 interceptor */
      }
    })();
    const unsubscribe = onProjectChange((p) => {
      setCurrent(p);
      setVersion((v) => v + 1);
    });
    return unsubscribe;
  }, [user]);

  const isAdmin = user?.role === "admin";

  const onSwitch = async (id) => {
    if (id && id !== current?.id) await switchProject(id);
  };

  const onNew = async () => {
    const name = window.prompt(t("nav.newProjectPrompt"));
    if (!name) return;
    const p = await createProject(name);
    await switchProject(p.id);
    const { data } = await api.get("/projects");
    setProjects(data);
  };

  const doLogout = () => {
    logout();
    setUser(null);
  };

  if (user === undefined) {
    return <div className="empty" style={{ paddingTop: 140 }}>{t("common.loading")}</div>;
  }

  if (user === null) {
    return <Login onLogin={setUser} />;
  }

  // 未加入任何团队：先创建或加入团队，之后才能看到监控数据
  if (user.team_id == null) {
    return (
      <AuthContext.Provider value={{ user, setUser }}>
        <TeamGate onDone={async () => {
          resetProject();
          const me = await fetchMe().catch(() => null);
          if (me) setUser(me);
        }} />
      </AuthContext.Provider>
    );
  }

  const noProjects = user.role !== "admin" && projects.length === 0;

  return (
    <AuthContext.Provider value={{ user, setUser }}>
      <div className="layout">
        {noProjects && (
          <div className="team-banner">
            <span>你的团队还没有监控项目。创建一个项目，用生成的 API Key 接入你的应用。</span>
            <button className="btn" onClick={onNew}>创建项目</button>
          </div>
        )}
        <aside className="sidebar">
          <div className="logo">
            <span className="logo-mark"><Icon name="radar" size={16} /></span>
            <span className="logo-name">LLMTrace</span>
          </div>

          <div className="project-box">
            <select value={current?.id || ""} onChange={(e) => onSwitch(e.target.value)}>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            {user.role !== "viewer" && (
              <button className="project-new" onClick={onNew}>
                <Icon name="plus" size={12} /> {t("nav.newProject")}
              </button>
            )}
          </div>

          <nav>
            <NavLink to="/" end><Icon name="activity" size={15} />{t("nav.dashboard")}</NavLink>
            <NavLink to="/traces"><Icon name="layers" size={15} />{t("nav.traces")}</NavLink>
            <NavLink to="/sessions"><Icon name="message-square" size={15} />{t("nav.sessions")}</NavLink>
            <NavLink to="/alerts"><Icon name="bell" size={15} />{t("nav.alerts")}</NavLink>
            {isAdmin && <NavLink to="/users"><Icon name="user" size={15} />{t("nav.users")}</NavLink>}
          </nav>

          <div className="sidebar-foot">
            <span className="status-dot" />
            <span className="user-name" title={user.username}>
              {user.display_name || user.username}
            </span>
            <span className={"role-chip " + user.role}>{t(ROLE_LABELS[user.role])}</span>
            <button className="theme-toggle" onClick={doLogout} title={t("nav.logout")}>
              <Icon name="logout" size={13} />
            </button>
            <button
              className="theme-toggle"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              title={theme === "dark" ? t("nav.themeLight") : t("nav.themeDark")}
            >
              <Icon name={theme === "dark" ? "sun" : "moon"} size={13} />
            </button>
            <button className="theme-toggle" onClick={() => setLang(lang === "zh" ? "en" : "zh")}
              title="中文 / English">
              <span style={{ fontSize: 11, fontWeight: 700 }}>{lang === "zh" ? "EN" : "中"}</span>
            </button>
          </div>
        </aside>

        <main className="content">
          <Routes key={version + user.id}>
            <Route path="/" element={<Dashboard theme={theme} />} />
            <Route path="/traces" element={<Traces />} />
            <Route path="/traces/:id" element={<TraceDetail />} />
            <Route path="/sessions" element={<Sessions />} />
            <Route path="/sessions/:sessionId" element={<SessionDetail />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/users" element={<Users />} />
          </Routes>
        </main>
      </div>
    </AuthContext.Provider>
  );
}

