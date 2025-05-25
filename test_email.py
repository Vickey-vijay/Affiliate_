from utils.email_sender import EmailSender

email_sender = EmailSender(config_path="config.json")
email_sender.send_email(
    subject="Test Email",
    body="This is a test email from Affiliate Product Monitor.",
    attachments=None
)

