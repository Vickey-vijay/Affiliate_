import smtplib
from email.mime.text import MIMEText

class EmailNotifier:
    def __init__(self, smtp_user, smtp_pass):
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass

    def send_email(self, recipient, subject, body):
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = self.smtp_user
        msg["To"] = recipient

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(self.smtp_user, self.smtp_pass)
            server.sendmail(self.smtp_user, recipient, msg.as_string())
