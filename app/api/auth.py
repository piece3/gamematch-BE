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

from app.core.deps import get_current_user
from app.schemas.user import UserResponse

from fastapi.security import OAuth2PasswordRequestForm

router = APIRouter(prefix="/auth",tags=["auth"])

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> User:
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 아이디가 존재하는 이메일입니다.",
        ) from exc

    db.refresh(user)

    raw_token = create_and_store_verification_token(db, user)
    verify_url = build_verification_url(raw_token)
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