"""Email delivery for one-time passwords.

`console` backend logs the message (development only — the code is printed to
the server console so you can log in without an SMTP server). `smtp` sends via
any SMTP server, e.g. Mailpit from docker-compose (http://localhost:8025).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import get_settings

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if s.email_backend == "console":
        if s.environment == "production":
            raise RuntimeError("console email backend is not allowed in production")
        # Printed directly (bypassing the redacting logger) so devs can read the OTP.
        print(f"\n===== EMAIL to {to} =====\nSubject: {subject}\n\n{body}\n=========================\n", flush=True)
        return

    msg = EmailMessage()
    msg["From"] = s.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
        if s.smtp_use_tls:
            smtp.starttls(context=ssl.create_default_context())
        if s.smtp_username and s.smtp_password:
            smtp.login(s.smtp_username, s.smtp_password)
        smtp.send_message(msg)
    log.info("OTP email sent")


def send_otp_email(to: str, code: str, purpose: str, ttl_minutes: int) -> None:
    action = "sign in to" if purpose == "login" else "verify your email for"
    body = (
        f"Your TaxPilot verification code is: {code}\n\n"
        f"Use it to {action} TaxPilot. It expires in {ttl_minutes} minutes.\n\n"
        "If you didn't request this, someone may know your password — change it now.\n"
        "TaxPilot staff will never ask you for this code."
    )
    send_email(to, f"TaxPilot code: {code}", body)
