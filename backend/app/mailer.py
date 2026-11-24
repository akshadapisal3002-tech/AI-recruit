"""Every email is recorded in `outbox`; delivered via SMTP too when SMTP_HOST is configured."""
import smtplib
from email.message import EmailMessage
from . import config
from .db import db


def send_email(to: str, subject: str, body: str):
    sent, err = 0, None
    if config.SMTP_HOST and to:
        try:
            m = EmailMessage()
            m["From"], m["To"], m["Subject"] = config.SMTP_FROM, to, subject
            m.set_content(body)
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as s:
                s.starttls()
                if config.SMTP_USER:
                    s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.send_message(m)
            sent = 1
        except Exception as e:  
            err = str(e)
    with db() as c:
        c.execute("INSERT INTO outbox(to_email,subject,body,sent,error) VALUES(?,?,?,?,?)", (to, subject, body, sent, err))
