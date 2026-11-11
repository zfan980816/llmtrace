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

export async function fetchMe() {
  const { data } = await authApi.get("/auth/me");
  return data;
}

export function logout() {
  localStorage.removeItem("llmtrace_token");
}

export async function authConfig() {
  return (await authApi.get("/auth/config")).data;
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
  if (!currentProject) {
    currentProject = await createProject("default");
  }
  return currentProject;
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




