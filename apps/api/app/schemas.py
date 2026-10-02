from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._@-]{2,63}$")


def clean_name(value):
    value = value.strip()
    if len(value) < 2 or any(ord(c) < 32 for c in value):
        raise ValueError("이름은 공백을 제외하고 2자 이상이어야 합니다.")
    return value


def clean_username(value):
    value = value.strip().lower()
    if not USERNAME_PATTERN.match(value):
        raise ValueError("아이디는 영문 소문자·숫자·._@- 3~64자여야 합니다.")
    return value


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=60)

    @field_validator("name")
    @classmethod
    def valid_name(cls, v):
        return clean_name(v)


class UserCreate(BaseModel):
    team_id: int
    # Omitted username: the server generates a random 10-character ID.
    username: str | None = Field(default=None, max_length=64)
    display_name: str | None = Field(default=None, max_length=60)

    @field_validator("username")
    @classmethod
    def valid_username(cls, v):
        return clean_username(v) if v else None

    @field_validator("display_name")
    @classmethod
    def valid_display_name(cls, v):
        return clean_name(v) if v and v.strip() else None


class SettingsPatch(BaseModel):
    is_open: bool | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    team_submission_limit: int | None = Field(default=None, ge=1, le=1000)
    count_failed: bool | None = None
    final_selection: Literal["best_public", "best_private"] | None = None
    frozen: bool | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def timezone_required(cls, v):
        if v and v.tzinfo is None:
            raise ValueError("Timezone offset is required")
        return v


class BanPatch(BaseModel):
    banned: bool


class CountedPatch(BaseModel):
    counted: bool


class LockPatch(BaseModel):
    locked: bool
