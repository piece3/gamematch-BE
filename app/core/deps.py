from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app. models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login/form")

def get_current_user(
    token: Annotated[str,Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
    ) -> User:
    credentials_exception = HTTPException(
        status_code = status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate":"Bearer"},
    )

    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise credentials_exception from exc

    if payload.sub is None:
        raise credentials_exception

    user = db.get(User, int(payload.sub))
    if user is None:
        raise credentials_exception

    return user