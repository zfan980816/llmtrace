import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  emailLogin, fetchMe, forgotSendCode, login,
  register, registerSendCode, requestEmailCode,
  resetPassword, setToken,
} from "../api";
import Icon from "../components/Icon";
import { t, useLang } from "../i18n";

export default function Login({ onLogin }) {
  const lang = useLang();
  const [mode, setMode] = useState("password");  // password | email | register | forgot
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
  const go = (m) => { setMode(m); setError(null); setNotice(null); setDevCode(null); setCode(""); };

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

  const sendRegisterCode = async () => {
    setBusy(true); setError(null); setNotice(null);
    try {
      const r = await registerSendCode(email);
      if (r.dev_code) setDevCode(r.dev_code);
      else setNotice(t("login.codeSent"));
      setCooldown(60);
    } catch (err) {
      setError(err.response?.data?.detail || "发送失败，请稍后重试");
    } finally { setBusy(false); }
  };

  const submitRegister = async (e) => {
    e.preventDefault();
    if (password.length < 8) { setError(t("login.setPassword")); return; }
    setBusy(true); setError(null);
    try {
      finishLogin(await register(email, code, password));
    } catch (err) {
      setError(err.response?.data?.detail || "注册失败，请稍后重试");
    } finally { setBusy(false); }
  };

  const sendForgotCode = async () => {
    setBusy(true); setError(null); setNotice(null);
    try {
      const r = await forgotSendCode(email);
      if (r.dev_code) setDevCode(r.dev_code);
      else setNotice(t("login.codeSent"));
      setCooldown(60);
    } catch (err) {
      setError(err.response?.data?.detail || "发送失败，请稍后重试");
    } finally { setBusy(false); }
  };

  const submitReset = async (e) => {
    e.preventDefault();
    if (password.length < 8) { setError(t("login.newPassword")); return; }
    setBusy(true); setError(null);
    try {
      await resetPassword(email, code, password);
      setNotice(null);
      go("password");
      setNotice(t("login.resetOk"));
    } catch (err) {
      setError(err.response?.data?.detail || "重置失败，请稍后重试");
    } finally { setBusy(false); }
  };

  const codeRow = (
    <div className="code-row">
      <input placeholder={t("login.code")} value={code} inputMode="numeric" maxLength={6}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
      <button type="button" className="btn btn-outline" disabled={busy || cooldown > 0 || !email}
        onClick={mode === "register" ? sendRegisterCode : mode === "forgot" ? sendForgotCode : sendCode}>
        {cooldown > 0 ? cooldown + "s" : t("login.sendCode")}
      </button>
    </div>
  );

  const backLink = (
    <button type="button" className="link-btn" onClick={() => go("password")}>
      {t("login.back")}
    </button>
  );

  const onSubmit = mode === "password" ? submitPassword
    : mode === "register" ? submitRegister
    : mode === "forgot" ? submitReset : submitEmail;

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={onSubmit}>
        <div className="logo" style={{ justifyContent: "center" }}>
          <span className="logo-mark"><Icon name="radar" size={16} /></span>
          <span className="logo-name">LLMTrace</span>
        </div>
        <p className="login-sub">
          {mode === "register" ? t("login.registerTitle")
            : mode === "forgot" ? t("login.forgotTitle")
            : t("login.subtitle")}
        </p>

        {mode === "password" && (
          <>
            <input placeholder={t("login.username")} value={username} autoFocus
              onChange={(e) => setUsername(e.target.value)} />
            <input placeholder={t("login.password")} type="password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
            {error && <div className="error-text">{error}</div>}
            {notice && <div className="error-text" style={{ color: "#34d399" }}>{notice}</div>}
            <button className="btn" disabled={busy || !username || !password}>
              <Icon name="arrow-left" size={13} style={{ transform: "rotate(180deg)" }} />
              {busy ? t("login.submitting") : t("login.submit")}
            </button>
            <button type="button" className="link-btn" onClick={() => go("email")}>
              {t("login.useEmail")}
            </button>
            <button type="button" className="link-btn" onClick={() => go("register")}>
              {t("login.toRegister")}
            </button>
            <button type="button" className="link-btn" onClick={() => go("forgot")}>
              {t("login.forgot")}
            </button>
          </>
        )}

        {(mode === "email" || mode === "register" || mode === "forgot") && (
          <>
            <input placeholder={t("login.email")} type="email" value={email} autoFocus
              onChange={(e) => setEmail(e.target.value)} />
            {codeRow}
            {(mode === "register" || mode === "forgot") && (
              <input placeholder={t("login.setPassword")} type="password" value={password}
                onChange={(e) => setPassword(e.target.value)} />
            )}
            {devCode && <div className="error-text">内网试用模式，验证码：{devCode}</div>}
            {notice && <div className="error-text" style={{ color: "#34d399" }}>{notice}</div>}
            {error && <div className="error-text">{error}</div>}
            <button className="btn" disabled={busy || !email || code.length !== 6
                || (mode !== "email" && password.length < 8)}>
              <Icon name="arrow-left" size={13} style={{ transform: "rotate(180deg)" }} />
              {busy ? (mode === "register" ? t("login.registering") : mode === "forgot" ? t("login.resetting") : t("login.submitting"))
                : mode === "register" ? t("login.registerSubmit")
                : mode === "forgot" ? t("login.resetSubmit") : t("login.submit")}
            </button>
            {mode === "email" && (
              <>
                <button type="button" className="link-btn" onClick={() => go("password")}>
                  {t("login.usePassword")}
                </button>
                <button type="button" className="link-btn" onClick={() => go("register")}>
                  {t("login.toRegister")}
                </button>
              </>
            )}
            {(mode === "register" || mode === "forgot") && backLink}
          </>
        )}

        {mode === "register" && <p className="login-hint">{t("login.registerNote")}</p>}
        {mode === "password" && <p className="login-hint">{t("login.hint")}</p>}
      </form>
    </div>
  );
}
