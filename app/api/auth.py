from typing import Annotated
import logging

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
from app.config import settings

from app.schemas.email import MessageResponse, ResendVerificationRequest, VerifyEmailResponse
from app.services.email_verification import(
    build_verification_url,
    create_and_store_verification_token,
    send_verification_email,
    verify_email_token,
    )

from app.core.deps import get_current_user
from app.schemas.user import UserResponse

from fastapi.security import OAuth2PasswordRequestForm

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth",tags=["auth"])

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> User:

    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        if not existing.is_verified:
            raw_token = create_and_store_verification_token(db, existing)
            verify_url = build_verification_url(raw_token)
            # HTTPException 시 BackgroundTasks가 실행되지 않으므로 여기서 직접 호출
            if settings.email_dev_mode:
                logger.warning(
                    "EMAIL DEV MODE (register-resend) | To=%s | verify_url=%s",
                    existing.email,
                    verify_url,
                )
            else:
                send_verification_email(existing.email, verify_url)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="이미 가입된 이메일입니다. 인증 메일을 다시 보냈습니다.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 가입된 이메일입니다. 로그인해 주세요.",
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
        if "email" in err:
            detail = "이미 가입된 이메일입니다."
        elif "nickname" in err:
            detail = "이미 사용 중인 닉네임입니다."
        else:
            detail = "이미 존재하는 정보입니다."
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        ) from exc

    db.refresh(user)

    raw_token = create_and_store_verification_token(db, user)
    verify_url = build_verification_url(raw_token)
    # BackgroundTasks는 응답 후에 실행됨. DEV면 요청 중에 바로 남겨 Render Logs에서 보이게 함.
    if settings.email_dev_mode:
        logger.warning(
            "EMAIL DEV MODE (register) | To=%s | verify_url=%s",
            user.email,
            verify_url,
        )
    background_tasks.add_task(send_verification_email, user.email, verify_url)

    return user




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
def read_me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
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
        # 보안: 존재 여부 노출 최소화
        return MessageResponse(message="If the account exists, a verification email has been sent.")

    if user.is_verified:
        return MessageResponse(message="Email is already verified.")

    raw_token = create_and_store_verification_token(db, user)
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