import hashlib
import secrets
import smtplib
from datetime import UTC,datetime,timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User

def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

def create_and_store_verification_token(db: Session, user: User)-> str:

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.email_verify_token_expire_hours)

    old_tokens = db.scalars(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used_at.is_(None),
            )
        ).all()
    for old in old_tokens:
        db.delete(old)

    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash = token_hash,
            expires_at = expires_at,
            )
    )
    db.commit()
    return raw_token
        
def build_verification_url(raw_token: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}/auth/verify-email?token={raw_token}"

def send_verification_email(to_email: str, verification_url: str) -> None:
    subject = "[Game Match] 이메일 인증을 완료해 주세요"
    body = (
        "아래 링크를 클릭하면 이메일 인증이 완료됩니다.\n\n"
        f"{verification_url}\n\n"
        f"링크는 {settings.email_verify_token_expire_hours}시간 동안 유효합니다."
        )
    if settings.email_dev_mode:
        print("\n===== EMAIL DEV MODE =====")
        print(f"To: {to_email}")
        print(f"Subject: {subject}")
        print(body)
        print("==========================\n")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{settings.mail_from_name} <{settings.mail_from}>"
    msg["To"] = to_email
    msg.set_contect(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


def verify_email_token(db: Session, raw_token:str) -> User:
    token_hash = _hash_token(raw_token)
    now = datetime.now(UTC)

    record = db.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash)
        )
    if record is None:
        raise ValueError("Invalid token")
    if record.used_at is not None:
        raise ValueError("Token already used")
    if record.expires_at < now:
        raise ValueError("Token expired")

    user = db.get(User, record.user_id)
    if user is None:
        raise ValueError("User not found")

    user.is_verified = True
    user.verified_at = now
    record.used_at = now
    db.commit()
    db.refresh(user)
    return user