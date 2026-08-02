import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
NOTIFY_TO_EMAIL = os.environ.get("NOTIFY_TO_EMAIL", GMAIL_ADDRESS)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


class NotifyError(Exception):
    pass


def send_email(subject: str, body: str) -> None:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise NotifyError("GMAIL_ADDRESS and GMAIL_APP_PASSWORD must be set in .env")

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = NOTIFY_TO_EMAIL

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(msg)
