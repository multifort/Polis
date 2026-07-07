"""邮件投递适配器。生产用 SMTP；dev/local 可写本地 outbox 便于联调。"""

from __future__ import annotations

import asyncio
import json
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from polis.config import Settings, get_settings


class MailDeliveryError(RuntimeError):
    """邮件投递失败或配置不完整。"""


@dataclass(frozen=True)
class MailMessage:
    to: str
    subject: str
    text: str


def password_reset_url(token: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return f"{s.public_app_url.rstrip('/')}/?reset_token={token}"


def password_reset_message(to: str, token: str, settings: Settings | None = None) -> MailMessage:
    s = settings or get_settings()
    url = password_reset_url(token, s)
    minutes = s.password_reset_ttl_minutes
    return MailMessage(
        to=to,
        subject="Polis 密码重置",
        text=(
            "你正在重置 Polis 账号密码。\n\n"
            f"请在 {minutes} 分钟内打开下面的链接完成重置：\n{url}\n\n"
            "如果不是你本人操作，可以忽略这封邮件。"
        ),
    )


async def send_mail(message: MailMessage, settings: Settings | None = None) -> None:
    s = settings or get_settings()
    backend = s.mail_backend.lower()
    if backend == "none":
        return
    if backend == "file":
        await asyncio.to_thread(_write_outbox, message, s)
        return
    if backend == "smtp":
        await asyncio.to_thread(_send_smtp, message, s)
        return
    raise MailDeliveryError(f"未知邮件后端：{s.mail_backend}")


def _write_outbox(message: MailMessage, settings: Settings) -> None:
    path = Path(settings.mail_outbox_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"to": message.to, "subject": message.subject, "text": message.text}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _send_smtp(message: MailMessage, settings: Settings) -> None:
    if not settings.mail_from:
        raise MailDeliveryError("POLIS_MAIL_FROM 未设置")
    if not settings.mail_smtp_host:
        raise MailDeliveryError("POLIS_MAIL_SMTP_HOST 未设置")

    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = message.to
    msg["Subject"] = message.subject
    msg.set_content(message.text)

    try:
        with smtplib.SMTP(settings.mail_smtp_host, settings.mail_smtp_port, timeout=10) as smtp:
            if settings.mail_smtp_starttls:
                smtp.starttls()
            if settings.mail_smtp_username or settings.mail_smtp_password:
                smtp.login(settings.mail_smtp_username, settings.mail_smtp_password)
            smtp.send_message(msg)
    except Exception as exc:  # noqa: BLE001 - 统一包装，避免泄露 SMTP 细节到 API
        raise MailDeliveryError("邮件发送失败") from exc
