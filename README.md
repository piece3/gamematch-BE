# study — 게임 매칭 API 공부용

## 폴더 구조

```
C:\Users\okm04\source\repos\study\   ← 이 폴더에서 터미널·Poetry·Docker 실행
├── app\                 ← FastAPI 애플리케이션 (지금은 main.py만)
│   └── main.py          ← 실제 서버 진입점 (/health)
├── examples\            ← 연습·튜토리얼 코드 (실행 안 함)
├── pyproject.toml       ← Poetry 의존성
├── .venv\               ← 가상환경
├── study.pyproj         ← Visual Studio 프로젝트
└── study.slnx           ← Visual Studio 솔루션
```

## 서버 실행

```powershell
cd C:\Users\okm04\source\repos\study
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

## 앞으로 파일이 늘어날 위치 (직접 추가)

| 단계 | 만들 파일 |
|------|-----------|
| 2단계 DB | `docker-compose.yml`, `.env`, `app/config.py`, `app/database.py` |
| 3단계 | `app/models/user.py` |
| 6단계 | `app/api/auth.py` |

**예전 `study\study\` 안쪽 폴더는 제거했습니다.** 코드는 위 `app\` 한 곳만 보면 됩니다.
