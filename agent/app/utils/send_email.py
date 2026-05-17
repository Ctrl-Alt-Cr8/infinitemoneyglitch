import os
import resend


def send_email(to_email: str, subject: str, body: str):
    resend.api_key = os.getenv("RESEND_API_KEY")
    if not resend.api_key:
        raise ValueError("RESEND_API_KEY is not set")

    sender = os.getenv("SENDER_EMAIL", "Readymade.hire <noreply@gugul.xyz>")

    resend.Emails.send({
        "from": sender,
        "to": [to_email],
        "subject": subject,
        "text": body,
    })

    print(f"✅ Email sent to {to_email}")
    return "Email sent"
