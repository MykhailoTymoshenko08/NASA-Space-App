"""Password recovery mail through Brevo SMTP. No credentials or reset tokens are logged."""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import urlencode

from app.auth.store import UserStore
from app.auth.tokens import new_refresh_token
from app.core.config import Settings

log = logging.getLogger(__name__)


class PasswordResetMailer:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        s = self.settings
        return bool(s.smtp_username and s.smtp_password.get_secret_value() and s.smtp_from_email)

    def send_reset(self, email: str, token: str) -> None:
        s = self.settings
        # Use the configured frontend origin, never a client-controlled Host or redirect parameter.
        url = f"{s.frontend_origin.rstrip('/')}/reset-password?{urlencode({'token': token})}"
        message = EmailMessage()
        message["Subject"] = "Reset your Field Shift password"
        message["From"] = formataddr((s.smtp_from_name, str(s.smtp_from_email)))
        message["To"] = email
        message.set_content(
            "We received a request to reset your Field Shift password.\n\n"
            f"Choose a new password here:\n{url}\n\n"
            "This link expires in one hour and can be used once.\n"
            "If you did not request this, you can ignore this email. Your password has not changed.\n"
        )
        context = ssl.create_default_context()
        if s.smtp_port == 465:
            connection = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=10, context=context)
        else:
            connection = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10)
        with connection as smtp:
            if s.smtp_port != 465:
                smtp.starttls(context=context)
            smtp.login(s.smtp_username, s.smtp_password.get_secret_value())
            smtp.send_message(message)


def deliver_password_reset(store: UserStore, mailer: PasswordResetMailer, email: str) -> None:
    """Background task for every request, including unknown emails, to keep the response uniform."""
    token = new_refresh_token()
    try:
        user = store.create_password_reset(email, token)
        if user is not None:
            mailer.send_reset(user.email, token)
    except Exception as exc:  # noqa: BLE001 - a background failure must not expose account existence
        log.error("Password reset delivery failed (%s)", type(exc).__name__)
        try:
            # A failed send can be retried immediately; never discard a newer request's link.
            store.discard_password_reset(token)
        except Exception as cleanup_exc:  # noqa: BLE001 - report without logging tokens or SMTP secrets
            log.error("Password reset cleanup failed (%s)", type(cleanup_exc).__name__)
