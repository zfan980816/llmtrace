"""邮箱验证码邮件发送。未配置 SMTP 时记录到日志（内网试用模式）。"""
import logging
import smtplib
from email.header import Header
from email.mime.text import MIMEText

from ..config import settings

log = logging.getLogger(__name__)


def smtp_ready() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def send_email_code(email: str, code: str) -> bool:
    """发送验证码。返回 True=已发送；False=SMTP 未配置（验证码已写入日志）。"""
    body = f"你的 LLMTrace 登录验证码：{code}\n10 分钟内有效。如果不是你本人操作，请忽略本邮件。"
    if not smtp_ready():
        log.warning("[email-login] SMTP 未配置，验证码 %s -> %s（仅供内网试用）", code, email)
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header("LLMTrace 登录验证码", "utf-8")
    msg["From"] = settings.smtp_from
    msg["To"] = email
    port = settings.smtp_port
    if port == 465:
        srv = smtplib.SMTP_SSL(settings.smtp_host, port, timeout=15)
    else:
        srv = smtplib.SMTP(settings.smtp_host, port, timeout=15)
        try:
            srv.starttls()
        except smtplib.SMTPNotSupportedError:
            pass
    if settings.smtp_user:
        srv.login(settings.smtp_user, settings.smtp_password)
    srv.sendmail(settings.smtp_from, [email], msg.as_string())
    srv.quit()
    return True
