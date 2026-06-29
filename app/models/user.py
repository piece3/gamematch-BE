import string
from app.database import Base
from datetime import datetime
from sqlalchemy import DateTime, String, func, Boolean
from sqlalchemy.orm import Mapped, mapped_column


#User 테이블의 설계도

class User(Base):
    __tablename__="users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255),unique=True,index=True,nullable=False)
    nickname: Mapped[str] = mapped_column(String(50),unique=True,nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255),nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)

