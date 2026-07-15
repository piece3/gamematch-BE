from fastapi import FastAPI


from contextlib import asynccontextmanager
from app.database import Base, engine
import app.models
from app.api.auth import router as auth_router
from app.api.profile import router as profile_router
from app.api.match import router as match_router
from app.api.ranking import router as ranking_router

from fastapi.middleware.cors import CORSMiddleware
from app.config import settings



@asynccontextmanager            #비동기를 쓰겠다

#앱을 실행할때 시작되는 명령어와 종료 직전에 명령어 = lifespan

async def lifespan(_: FastAPI):
    
    yield

app = FastAPI(lifespan=lifespan)      #lifespan == 위에 말한것

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(match_router)
app.include_router(ranking_router)

#서버 상태가 온라인인지 확인
@app.get("/health")
def health_check():
    return {"status": "ok"}
