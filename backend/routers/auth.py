import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import User
from backend.schemas import UserCreate, TokenResponse, UserOut
from backend.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def _hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _create_token(data: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    return jwt.encode(
        {**data, "exp": expire},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub", "")
        if not user_id:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exc
    return user


@router.post("/register", response_model=UserOut, status_code=201)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")

    user = User(
        id=str(uuid.uuid4()),
        name=data.name,
        email=data.email,
        phone=data.phone,
        hashed_password=_hash_password(data.password),
        role=data.role,
        area_code=data.area_code,
        area_name=data.area_name,
        district=data.district,
        block=data.block,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/token", response_model=TokenResponse)
async def login(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Accept credentials either as:
      - application/x-www-form-urlencoded (OAuth2PasswordRequestForm compatible)
      - application/json: {"username": "...", "password": "..."}
    """
    content_type = request.headers.get("content-type", "")

    username: str | None = None
    password: str | None = None

    if "application/json" in content_type:
        payload = await request.json()
        username = payload.get("username")
        password = payload.get("password")
    else:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    result = await db.execute(select(User).where(User.email == username))
    user = result.scalar_one_or_none()
    if not user or not _verify_password(password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    token = _create_token({"sub": user.id, "role": user.role})
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        role=user.role,
        name=user.name,
    )


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
