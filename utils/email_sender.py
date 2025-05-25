

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import os
import json

class EmailSender:
    def __init__(self, config_path="config.json"):
        self.config = self.load_config(config_path)

    def load_config(self, path):
        try:
            with open(path, "r") as f:
                return json.load(f).get("email", {})
        except Exception as e:
            print(f"⚠️ Failed to load email config: {e}")
            return {}

    def send_email(self, subject, body, attachments=None):
        sender_email = self.config.get("sender_email")
        smtp_server = self.config.get("smtp_server", "smtp.gmail.com")
        smtp_port = self.config.get("smtp_port", 587)
        smtp_password = self.config.get("smtp_password")
        recipients = self.config.get("recipients", [])

        print(f"📧 Debug: Sender Email: {sender_email}")
        print(f"📧 Debug: SMTP Server: {smtp_server}")
        print(f"📧 Debug: SMTP Port: {smtp_port}")
        print(f"📧 Debug: Recipients: {recipients}")

        if not all([sender_email, smtp_password, recipients]):
            print("❌ Email config incomplete. Check config.json.")
            return

        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if attachments:
            for file_path in attachments:
                try:
                    with open(file_path, "rb") as f:
                        part = MIMEApplication(f.read(), Name=os.path.basename(file_path))
                        part["Content-Disposition"] = f'attachment; filename="{os.path.basename(file_path)}"'
                        msg.attach(part)
                except Exception as e:
                    print(f"⚠️ Failed to attach file {file_path}: {e}")

        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(sender_email, smtp_password)
                server.send_message(msg)
                print("✅ Email sent successfully.")
        except Exception as e:
            print(f"❌ Failed to send email: {e}")
