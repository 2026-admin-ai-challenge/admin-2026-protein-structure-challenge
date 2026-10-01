from datetime import datetime
from pydantic import BaseModel,EmailStr,Field,field_validator
class Login(BaseModel):
    email:EmailStr
    password:str=Field(min_length=10,max_length=128)
class Register(Login):
    display_name:str=Field(min_length=2,max_length=60)
    team_name:str=Field(min_length=2,max_length=60)
    @field_validator("display_name","team_name")
    @classmethod
    def clean_name(cls,v):
        v=v.strip()
        if len(v)<2 or any(ord(c)<32 for c in v): raise ValueError("이름은 공백을 제외하고 2자 이상이어야 합니다.")
        return v
class SettingsPatch(BaseModel):
    is_open:bool|None=None
    start_time:datetime|None=None
    end_time:datetime|None=None
    daily_limit:int|None=Field(default=None,ge=1,le=100)
    frozen:bool|None=None
    @field_validator("start_time","end_time")
    @classmethod
    def timezone_required(cls,v):
        if v and v.tzinfo is None: raise ValueError("Timezone offset is required")
        return v
class BanPatch(BaseModel): banned:bool
