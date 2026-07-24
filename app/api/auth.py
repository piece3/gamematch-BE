from typing import Annotated

from sqlalchemy import select
from app.core.security import create_access_token, verify_password
from app.schemas.auth import Token
from app.schemas.user import UserLogin

from fastapi import APIRouter, Depends, HTTPException,status, BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse

from app.schemas.email import MessageResponse, ResendVerificationRequest, VerifyEmailResponse
from app.services.email_verification import(
    build_verification_url,
    create_and_store_verification_token,
    send_verification_email,
    verify_email_token,
    )

from app.core.deps import get_current_verified_user

from fastapi.security import OAuth2PasswordRequestForm

router = APIRouter(prefix="/auth",tags=["auth"])

GENERIC_VERIFICATION_MESSAGE = (
    "If the account can be registered, a verification email has been sent."
)


@router.post(
    "/register",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def register(
    payload: UserCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> MessageResponse:

    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        if existing.is_verified:
            # 이미 인증된 계정이면 메일을 보내지 않음 (응답은 동일하게 202)
            return MessageResponse(
                message=GENERIC_VERIFICATION_MESSAGE,
            )
        raw_token = create_and_store_verification_token(
            db,
            existing,
            respect_cooldown=True,
        )
        if raw_token is not None:
            verify_url = build_verification_url(raw_token)
            background_tasks.add_task(
                send_verification_email, existing.email, verify_url
            )
        return MessageResponse(
            message=GENERIC_VERIFICATION_MESSAGE,
        )

    nickname_taken = db.scalar(select(User).where(User.nickname == payload.nickname))
    if nickname_taken is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 닉네임입니다.",
        )

    user = User(
        email=payload.email.lower(),
        nickname=payload.nickname,
        hashed_password=hash_password(payload.password),
        is_verified=False,
        college=payload.college,
        department=payload.department,  
    )
    db.add(user)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        err = str(exc.orig).lower()
        if "nickname" in err:
            detail = "이미 사용 중인 닉네임입니다."
        elif "email" in err:
            return MessageResponse(message=GENERIC_VERIFICATION_MESSAGE)
        else:
            detail = "이미 존재하는 정보입니다."
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        ) from exc

    db.refresh(user)

    raw_token = create_and_store_verification_token(db, user)
    if raw_token is None:
        raise RuntimeError("Failed to create initial verification token")
    verify_url = build_verification_url(raw_token)
    background_tasks.add_task(send_verification_email, user.email, verify_url)

    return MessageResponse(message=GENERIC_VERIFICATION_MESSAGE)




@router.post("/login",response_model=Token)
def login(payload: UserLogin, db: Annotated[Session,Depends(get_db)]) -> Token:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호 불일치",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your inbox.",
        )

    access_token = create_access_token(subject=str(user.id))
    return Token(access_token=access_token)





@router.get("/me", response_model=UserResponse)
def read_me(
    current_user: Annotated[User, Depends(get_current_verified_user)],
) -> User:
    return current_user


@router.get("/verify-email", response_model=VerifyEmailResponse)
def verify_email(token: str, db: Annotated[Session, Depends(get_db)]) -> VerifyEmailResponse:
    try:
        user = verify_email_token(db, token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return VerifyEmailResponse(message="Email verified successfully", is_verified=user.is_verified)


@router.post("/resend-verification", response_model=MessageResponse)
def resend_verification(
    payload: ResendVerificationRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None:
        return MessageResponse(message="If the account exists, a verification email has been sent.")

    if user.is_verified:
        return MessageResponse(message="If the account exists, a verification email has been sent.")

    raw_token = create_and_store_verification_token(
        db,
        user,
        respect_cooldown=True,
    )
    if raw_token is not None:
        verify_url = build_verification_url(raw_token)
        background_tasks.add_task(send_verification_email, user.email, verify_url)

    return MessageResponse(message="If the account exists, a verification email has been sent.")



@router.post("/login/form", response_model=Token, include_in_schema=True)
def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
    ) -> Token:

    user = db.scalar(select(User).where(User.email == form_data.username.lower()))
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 혹은 비밀번호가 틀렸습니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your inbox.",
        )
    access_token = create_access_token(subject=str(user.id))
    return Token(access_token=access_token)