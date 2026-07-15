import hashlib
import logging
import secrets
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User

logger = logging.getLogger(__name__)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_and_store_verification_token(
    db: Session,
    user: User,
    *,
    respect_cooldown: bool = False,
) -> str | None:
    locked_user = db.scalar(
        select(User).where(User.id == user.id).with_for_update()
    )
    if locked_user is None:
        raise ValueError("User not found")

    if respect_cooldown:
        latest_created_at = db.scalar(
            select(EmailVerificationToken.created_at)
            .where(EmailVerificationToken.user_id == locked_user.id)
            .order_by(EmailVerificationToken.created_at.desc())
            .limit(1)
        )
        if latest_created_at is not None:
            retry_at = latest_created_at + timedelta(
                seconds=settings.email_resend_cooldown_seconds
            )
            if datetime.now(UTC) < retry_at:
                return None

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.email_verify_token_expire_hours)

    old_tokens = db.scalars(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == locked_user.id,
            EmailVerificationToken.used_at.is_(None),
        )
    ).all()
    for old in old_tokens:
        db.delete(old)

    db.add(
        EmailVerificationToken(
            user_id=locked_user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    db.commit()
    return raw_token


def build_verification_url(raw_token: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}/auth/verify-email?token={raw_token}"


def send_verification_email(to_email: str, verification_url: str) -> bool:
    subject = "[Game Match] 이메일 인증을 완료해 주세요"
    body = (
        "아래 링크를 클릭하면 이메일 인증이 완료됩니다.\n\n"
        f"{verification_url}\n\n"
        f"링크는 {settings.email_verify_token_expire_hours}시간 동안 유효합니다."
    )

    # DEV 모드: Render Logs에도 보이도록 logging 사용 (print는 버퍼링 때문에 종종 안 보임)
    if settings.email_dev_mode:
        logger.warning(
            "EMAIL DEV MODE | To=%s | verify_url=%s",
            to_email,
            verification_url,
        )
        return True

    missing_settings = [
        name
        for name, value in (
            ("SMTP_HOST", settings.smtp_host),
            ("SMTP_USER", settings.smtp_user),
            ("SMTP_PASSWORD", settings.smtp_password),
            ("MAIL_FROM", settings.mail_from),
        )
        if not value
    ]
    if missing_settings:
        logger.error(
            "Verification email was not sent: missing settings %s",
            ", ".join(missing_settings),
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{settings.mail_from_name} <{settings.mail_from}>"
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        logger.info("Verification email sent to %s", to_email)
        return True
    except Exception:
        logger.exception("Failed to send verification email to %s", to_email)
        return False


def verify_email_token(db: Session, raw_token: str) -> User:
    token_hash = _hash_token(raw_token)
    now = datetime.now(UTC)

    record = db.scalar(
        select(EmailVerificationToken)
        .where(EmailVerificationToken.token_hash == token_hash)
        .with_for_update()
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
