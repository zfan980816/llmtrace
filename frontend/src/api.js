import axios from "axios";

const api = axios.create({ baseURL: "/api/v1" });
const authApi = axios.create({ baseURL: "/api" });

function attach(instance) {
  instance.interceptors.request.use((config) => {
    const token = localStorage.getItem("llmtrace_token");
    if (token) config.headers.Authorization = "Bearer " + token;
    return config;
  });
  instance.interceptors.response.use(
    (r) => r,
    (err) => {
      const url = err.config?.url || "";
      if (err.response?.status === 401 && !url.includes("/auth/login") && !url.includes("/auth/me")) {
        localStorage.removeItem("llmtrace_token");
        window.dispatchEvent(new Event("llmtrace:unauthorized"));
      }
      return Promise.reject(err);
    }
  );
}

attach(api);
attach(authApi);

/* ---------- auth ---------- */
export function setToken(token) {
  if (token) localStorage.setItem("llmtrace_token", token);
  else localStorage.removeItem("llmtrace_token");
}

export async function login(username, password) {
  const { data } = await authApi.post("/auth/login", { username, password });
  localStorage.setItem("llmtrace_token", data.token);
  return data.user;
}

export async function requestEmailCode(email) {
  return (await authApi.post("/auth/email-code", { email })).data;
}

export async function emailLogin(email, code) {
  const { data } = await authApi.post("/auth/email-login", { email, code });
  localStorage.setItem("llmtrace_token", data.token);
  return data.user;
}

export async function fetchMe() {
  const { data } = await authApi.get("/auth/me");
  return data;
}

export function logout() {
  localStorage.removeItem("llmtrace_token");
}

export async function createShareLink(traceId) {
  const { data } = await api.post(`/traces/${traceId}/share`);
  return data;
}

export async function fetchSharedTrace(token) {
  const { data } = await api.get(`/public/traces/${token}`);
  return data;
}

export async function changeOwnPassword(oldPassword, newPassword) {
  const { data } = await api.patch("/auth/me/password", {
    old_password: oldPassword,
    new_password: newPassword,
  });
  return data;
}

export async function adminListUsers() {
  return (await authApi.get("/auth/users")).data;
}

export async function adminCreateUser(payload) {
  return (await authApi.post("/auth/users", payload)).data;
}

export async function adminUpdateUser(id, payload) {
  return (await authApi.patch("/auth/users/" + id, payload)).data;
}

export async function adminListAudit(limit = 100) {
  return (await authApi.get("/auth/audit-logs", { params: { limit } })).data;
}

/* ---------- projects ---------- */
let currentProject = null;
const listeners = [];

function notify() {
  listeners.forEach((cb) => cb(currentProject));
}

export function onProjectChange(cb) {
  listeners.push(cb);
  return () => {
    const i = listeners.indexOf(cb);
    if (i >= 0) listeners.splice(i, 1);
  };
}

export async function ensureProject() {
  if (currentProject) return currentProject;
  const { data } = await api.get("/projects");
  const savedId = localStorage.getItem("llmtrace_project_id");
  currentProject = data.find((p) => p.id === savedId) || data[0] || null;
  return currentProject;  // 无项目时返回 null，由前端引导创建
}

export async function resetProject() {
  currentProject = null;
  localStorage.removeItem("llmtrace_project_id");
  notify();
}

/* ---------- team ---------- */
export async function getTeam() {
  return (await authApi.get("/team")).data;
}
export async function createTeam(name) {
  return (await authApi.post("/team", { name })).data;
}
export async function joinTeam(inviteCode) {
  return (await authApi.post("/team/join", { invite_code: inviteCode })).data;
}
export async function regenerateInviteCode() {
  return (await authApi.post("/team/invite-code")).data;
}

export async function createProject(name) {
  const { data } = await api.post("/projects", { name });
  return data;
}

export async function switchProject(id) {
  const { data } = await api.get("/projects");
  const p = data.find((x) => x.id === id);
  if (!p) return;
  currentProject = p;
  localStorage.setItem("llmtrace_project_id", id);
  notify();
}

export { api };
export default api;




