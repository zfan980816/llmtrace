import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { emailLogin, fetchMe, login, requestEmailCode, setToken } from "../api";
import Icon from "../components/Icon";
import { t, useLang } from "../i18n";

export default function Login({ onLogin }) {
  const lang = useLang();
  const [mode, setMode] = useState("password");  // password | email
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [cooldown, setCooldown] = useState(0);
  const [devCode, setDevCode] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const qp = new URLSearchParams(window.location.search);
    const tk = qp.get("token");
    if (tk) {
      setToken(tk);
      fetchMe().then(onLogin).catch(() => setToken(null));
      window.history.replaceState({}, "", window.location.pathname);
      return;
    }
  }, []);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setInterval(() => setCooldown((s) => s - 1), 1000);
    return () => clearInterval(timer);
  }, [cooldown]);

  const finishLogin = (user) => onLogin(user);

  const submitPassword = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      finishLogin(await login(username, password));
    } catch (err) {
      setError(err.response?.data?.detail || "登录失败，请稍后重试");
    } finally { setBusy(false); }
  };

  const sendCode = async () => {
    setBusy(true); setError(null); setNotice(null);
    try {
      const r = await requestEmailCode(email);
      if (r.dev_code) setDevCode(r.dev_code);
      else setNotice(t("login.codeSent"));
      setCooldown(60);
    } catch (err) {
      setError(err.response?.data?.detail || "发送失败，请稍后重试");
    } finally { setBusy(false); }
  };

  const submitEmail = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      finishLogin(await emailLogin(email, code));
    } catch (err) {
      setError(err.response?.data?.detail || "登录失败，请稍后重试");
    } finally { setBusy(false); }
  };

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={mode === "email" ? submitEmail : submitPassword}>
        <div className="logo" style={{ justifyContent: "center" }}>
          <span className="logo-mark"><Icon name="radar" size={16} /></span>
          <span className="logo-name">LLMTrace</span>
        </div>
        <p className="login-sub">{t("login.subtitle")}</p>

        {mode === "password" ? (
          <>
            <input placeholder={t("login.username")} value={username} autoFocus
              onChange={(e) => setUsername(e.target.value)} />
            <input placeholder={t("login.password")} type="password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
            {error && <div className="error-text">{error}</div>}
            <button className="btn" disabled={busy || !username || !password}>
              <Icon name="arrow-left" size={13} style={{ transform: "rotate(180deg)" }} />
              {busy ? t("login.submitting") : t("login.submit")}
            </button>
            <button type="button" className="link-btn" onClick={() => { setMode("email"); setError(null); }}>
              {t("login.useEmail")}
            </button>
          </>
        ) : (
          <>
            <input placeholder={t("login.email")} type="email" value={email} autoFocus
              onChange={(e) => setEmail(e.target.value)} />
            <div className="code-row">
              <input placeholder={t("login.code")} value={code} inputMode="numeric" maxLength={6}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
              <button type="button" className="btn btn-outline" disabled={busy || cooldown > 0 || !email}
                onClick={sendCode}>
                {cooldown > 0 ? cooldown + "s" : t("login.sendCode")}
              </button>
            </div>
            {devCode && <div className="error-text">内网试用模式，验证码：{devCode}</div>}
            {notice && <div className="error-text" style={{ color: "#34d399" }}>{notice}</div>}
            {error && <div className="error-text">{error}</div>}
            <button className="btn" disabled={busy || !email || code.length !== 6}>
              <Icon name="arrow-left" size={13} style={{ transform: "rotate(180deg)" }} />
              {busy ? t("login.submitting") : t("login.submit")}
            </button>
            <button type="button" className="link-btn" onClick={() => { setMode("password"); setError(null); }}>
              {t("login.usePassword")}
            </button>
          </>
        )}

        <p className="login-hint">{t("login.hint")}</p>
      </form>
    </div>
  );
}
