// 轻量 i18n：字典 + t() + useLang()。默认跟随浏览器语言，localStorage 持久化。
import { useEffect, useState } from "react";

const DICT = {
  // ---- 导航 ----
  "nav.dashboard": ["监控概览", "Dashboard"],
  "nav.traces": ["Trace 列表", "Traces"],
  "nav.sessions": ["会话", "Sessions"],
  "nav.alerts": ["告警", "Alerts"],
  "nav.users": ["成员管理", "Members"],
  "nav.newProject": ["新建项目", "New project"],
  "nav.newProjectPrompt": ["新项目名称：", "New project name:"],
  "nav.logout": ["退出登录", "Log out"],
  "nav.themeLight": ["切换亮色主题", "Switch to light"],
  "nav.themeDark": ["切换暗色主题", "Switch to dark"],
  "role.admin": ["管理员", "Admin"],
  "role.member": ["成员", "Member"],
  "role.viewer": ["只读", "Viewer"],
  "common.loading": ["加载中…", "Loading..."],

  // ---- 登录 ----
  "login.subtitle": ["LLM 监控平台 · 团队登录", "LLM Observability · Team sign-in"],
  "login.useEmail": ["使用邮箱验证码登录", "Log in with email code"],
  "login.usePassword": ["使用密码登录", "Log in with password"],
  "login.email": ["邮箱", "Email"],
  "login.code": ["验证码", "Verification code"],
  "login.sendCode": ["发送验证码", "Send code"],
  "login.codeSent": ["验证码已发送，请查收邮件", "Code sent, check your inbox"],
  "login.emailNote": ["首次登录自动创建账号，默认可查看监控", "First login creates an account with view access"],
  "login.username": ["用户名", "Username"],
  "login.password": ["密码", "Password"],
  "login.submit": ["登录", "Sign in"],
  "login.submitting": ["登录中…", "Signing in..."],
  "login.or": ["或", "or"],
  "login.hint": ["默认管理员 admin / admin123，首次登录后请修改密码",
    "Default admin: admin / admin123 — change it after first sign-in"],

  // ---- Traces 页 ----
  "traces.title": ["Traces", "Traces"],
  "view.traces": ["Traces", "Traces"],
  "view.threads": ["Threads", "Threads"],
  "view.runs": ["Runs", "Runs"],
  "status.all": ["全部", "All"],
  "status.ok": ["成功", "Success"],
  "status.error": ["失败", "Failed"],
  "search.placeholder": ["搜索名称 / 内容 / 错误…", "Search name / content / error..."],
  "filter.model": ["模型（如 gpt-4o-mini）", "Model (e.g. gpt-4o-mini)"],
  "filter.allTypes": ["全部类型", "All types"],
  "filter.minLatency": ["最小延迟 ms", "Min latency ms"],
  "filter.maxLatency": ["最大延迟 ms", "Max latency ms"],
  "filter.apply": ["筛选", "Filter"],
  "filter.reset": ["重置", "Reset"],
  "export.csv": ["CSV", "CSV"],
  "th.name": ["名称", "Name"],
  "th.input": ["输入", "Input"],
  "th.output": ["输出", "Output"],
  "th.error": ["错误", "Error"],
  "th.startTime": ["开始时间", "Start time"],
  "th.latency": ["延迟", "Latency"],
  "th.tokens": ["Token", "Tokens"],
  "th.cost": ["成本", "Cost"],
  "th.run": ["Run", "Run"],
  "th.trace": ["Trace", "Trace"],
  "th.session": ["会话 ID", "Session"],
  "th.traceCount": ["Trace 数", "Traces"],
  "th.avgLatency": ["平均延迟", "Avg latency"],
  "th.lastSeen": ["最后活跃", "Last seen"],
  "pager.prev": ["上一页", "Prev"],
  "pager.next": ["下一页", "Next"],
  "pager.info": ["共 {total} 条 · 第 {page}/{pages} 页", "{total} total · page {page}/{pages}"],
  "empty.noTraces": ["没有匹配的 trace", "No matching traces"],
  "empty.noRuns": ["没有匹配的 run", "No matching runs"],
  "empty.noSessions": ["暂无会话", "No sessions"],
  "spanType.llm": ["LLM", "LLM"],
  "spanType.tool": ["工具", "Tool"],
  "spanType.retrieval": ["检索", "Retrieval"],
  "spanType.agent": ["Agent", "Agent"],
  "spanType.chain": ["链", "Chain"],
  // ---- Dashboard ----
  "dash.refresh": ["刷新", "Refresh"],
  "dash.totalCalls": ["总调用数", "Total calls"],
  "dash.errorRate": ["错误率", "Error rate"],
  "dash.avgLatency": ["平均延迟", "Avg latency"],
  "dash.p95": ["P95 延迟", "P95 latency"],
  "dash.totalTokens": ["总 Token", "Total tokens"],
  "dash.totalCost": ["总成本", "Total cost"],
  "dash.callsErrors": ["调用量与错误", "Calls & errors"],
  "dash.callsErrorsSub": ["每小时调用次数与失败次数", "Calls and failures per hour"],
  "dash.calls": ["调用", "Calls"],
  "dash.errors": ["错误", "Errors"],
  "dash.tokensCost": ["Token 与成本", "Tokens & cost"],
  "dash.tokensCostSub": ["每小时 token 消耗与美元成本", "Tokens and USD cost per hour"],
  "dash.costUsd": ["成本 ($)", "Cost ($)"],
  "dash.errorAnalysis": ["错误分析", "Error analysis"],
  "dash.errorAnalysisSub": ["按错误内容聚类 · 最近", "Clustered by error content · last"],
  "dash.noErrorsInRange": ["所选时间范围外无错误", "No errors outside the selected range"],
  "dash.noErrors": ["无错误，运行平稳", "No errors — all healthy"],
  "dash.modelUsage": ["模型用量", "Model usage"],
  "dash.modelUsageSub": ["按模型统计调用 / Token / 成本", "Calls / tokens / cost by model"],
  "dash.model": ["模型", "Model"],
  "dash.costShare": ["成本占比", "Cost share"],
  "dash.latencyDist": ["延迟分布", "Latency distribution"],
  "dash.latencyDistSub": ["Trace 延迟直方图", "Trace latency histogram"],
  "dash.backendError": ["无法连接后端", "Cannot reach backend"],

  // ---- TraceDetail ----
  "detail.backToList": ["← 返回列表", "← Back to list"],
  "detail.session": ["会话", "Session"],
  "tab.feedback": ["Feedback", "Feedback"],
  "tab.input": ["对话", "Chat"],
  "tab.output": ["Output", "Output"],
  "tab.raw": ["Raw JSON", "Raw JSON"],
  "fb.accurate": ["👍 准确", "👍 Accurate"],
  "fb.wrong": ["👎 有问题", "👎 Wrong"],
  "fb.placeholder": ["补充说明（可选）：哪里好/哪里不对…", "Optional note: what was right / wrong..."],
  "fb.empty": ["还没有反馈，第一个标记吧", "No feedback yet — be the first"],
  "common.loadFailed": ["加载失败", "Failed to load"],
  "common.loadingShort": ["加载中…", "Loading..."],
  // ---- Sessions ----
  "sess.title": ["会话", "Sessions"],
  "sess.id": ["会话 ID", "Session"],
  "sess.calls": ["调用数", "Traces"],
  "sess.lastActivity": ["最近活动", "Last activity"],
  "sess.empty": ["暂无会话 — SDK 上报时带 session_id 即可自动聚合",
    "No sessions yet — pass session_id from the SDK to group automatically"],

  // ---- Users ----
  "users.title": ["成员管理", "Members"],
  "users.addUser": ["添加成员", "Add member"],
  "users.empty": ["暂无成员", "No members"],

  // ---- Alerts ----
  "alerts.title": ["告警", "Alerts"],
};

let lang = localStorage.getItem("llmtrace_lang")
  || (navigator.language && navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en");

const listeners = new Set();

export function getLang() {
  return lang;
}

export function setLang(next) {
  lang = next === "en" ? "en" : "zh";
  localStorage.setItem("llmtrace_lang", lang);
  for (const fn of listeners) fn(lang);
}

/** 取文案；t("pager.info", {total, page, pages}) 支持简单 {name} 插值 */
export function t(key, vars) {
  const entry = DICT[key];
  if (!entry) return key;
  let text = lang === "en" ? entry[1] : entry[0];
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      text = text.replaceAll("{" + k + "}", String(v));
    }
  }
  return text;
}

/** 订阅语言变化触发组件重渲染 */
export function useLang() {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((n) => n + 1);
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  }, []);
  return lang;
}
