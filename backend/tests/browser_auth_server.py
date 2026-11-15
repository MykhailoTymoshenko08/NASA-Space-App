"""Isolated real API for browser auth tests, with captured mail and a disposable database.

Run from backend: uv run python -m tests.browser_auth_server
Use AUTH_FRONTEND_ORIGIN, AUTH_API_PORT and AUTH_AUDIT_DIR to override local defaults.
No outbound email is sent. Mail capture contains bearer secrets: keep it outside the repository.
"""

import json
import os
import uuid
from pathlib import Path

import psycopg
import uvicorn

from app.auth.mail import PasswordResetMailer
from app.core.config import Settings
from app.core.ratelimit import RateLimiter
from app.main import create_app
from tests.fixture_data import build, load_fields


def main() -> None:
    root = Path(os.environ.get("AUTH_AUDIT_DIR", "/tmp/fieldshift-auth-audit"))
    root.mkdir(parents=True, exist_ok=True)
    mail_file = root / "mail.jsonl"
    mail_file.write_text("")
    mail_file.chmod(0o600)
    name = f"fieldshift_browser_auth_{uuid.uuid4().hex[:8]}"
    admin_url = os.environ.get(
        "TEST_DATABASE_ADMIN_URL", "postgresql://fieldshift:fieldshift@localhost:5433/postgres"
    )
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
        try:
            database_url = admin_url.rsplit("/", 1)[0] + "/" + name
            with psycopg.connect(database_url, autocommit=True) as connection:
                load_fields(connection)
            settings = Settings(
                _env_file=None,
                database_url=database_url,
                data_dir=build(root / "data"),
                cache_dir=root / "cache",
                frontend_origin=os.environ.get("AUTH_FRONTEND_ORIGIN", "http://localhost:5174"),
                analysis_engine="stub",
                smtp_username="local-capture",
                smtp_password="local-capture",
                smtp_from_email="audit@example.com",
                rate_limit_requests=1000,
                log_level="WARNING",
            )

            def capture_mail(_mailer: PasswordResetMailer, email: str, token: str) -> None:
                with mail_file.open("a") as stream:
                    stream.write(json.dumps({
                        "email": email,
                        "url": f"{settings.frontend_origin}/reset-password?token={token}",
                    }) + "\n")

            PasswordResetMailer.send_reset = capture_mail
            app = create_app(settings)
            # The suite deliberately exercises many password failures from one local IP.
            # Production limits stay unchanged and are covered by backend tests.
            app.state.limiters["password"] = RateLimiter(1000, 60)
            uvicorn.run(
                app, host="127.0.0.1", port=int(os.environ.get("AUTH_API_PORT", "8002"))
            )
        finally:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


if __name__ == "__main__":
    main()
