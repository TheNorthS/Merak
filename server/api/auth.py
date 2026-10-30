"""认证 API — JWT 令牌管理"""

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from jose import jwt
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from .access import current_principal
from ..services.access_identity import Principal, SESSION_COOKIE
from ..db.engine import get_db
from ..models.models import User
from ..services.authentication import AuthenticationError, authentication_service

router = APIRouter()


class UserLogin(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=10, max_length=1024)
    display_name: str = Field(default="", max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfo(BaseModel):
    id: str
    username: str
    email: str
    display_name: str


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """创建 JWT 令牌"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _user_info(user: User) -> UserInfo:
    return UserInfo(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
    )


async def get_current_user(principal: Principal = Depends(current_principal)) -> UserInfo:
    return UserInfo(id=principal.id, username=principal.username, email=principal.email,
                    display_name=principal.display_name)


def _session_response(user: User, response: Response, request: Request) -> TokenResponse:
    token = create_access_token(data={"sub": user.username})
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict",
                        secure=not settings.debug or request.url.scheme == "https",
                        max_age=settings.jwt_expire_minutes * 60,
                        path="/")
    return TokenResponse(access_token=token, expires_in=settings.jwt_expire_minutes * 60)


@router.post("/login", response_model=TokenResponse)
async def login(form: UserLogin, response: Response, request: Request, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """用户登录"""
    try:
        user = await authentication_service.authenticate(
            db,
            username=form.username,
            password=form.password,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        ) from exc
    return _session_response(user, response, request)


@router.post("/register", response_model=TokenResponse)
async def register(form: UserRegister, response: Response, request: Request, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """用户注册"""
    if not settings.allow_registration:
        raise HTTPException(403, "Registration is disabled; contact the operator")
    try:
        user = await authentication_service.register(
            db,
            username=form.username,
            email=form.email,
            password=form.password,
            display_name=form.display_name,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return _session_response(user, response, request)


@router.get("/me", response_model=UserInfo)
async def get_me(user: UserInfo = Depends(get_current_user)):
    """获取当前用户信息"""
    return user


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "signed_out"}
