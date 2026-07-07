"""org/身份 模块的请求/响应 schema（Pydantic v2）。"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetRequestOut(BaseModel):
    accepted: bool = True
    reset_token: str | None = None


class PasswordResetConfirmIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str | None = None


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    description: str | None = None


class MeOut(BaseModel):
    user: UserOut
    orgs: list[OrgOut]


class OrgCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    charter: str | None = None


class OrgUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class InviteCreateIn(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(approver|member)$")


class InviteOut(BaseModel):
    id: uuid.UUID | None = None
    email: str
    role: str
    status: str
    invite_token: str | None = None


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None = None


class AgentAuthority(BaseModel):
    """Agent 权限声明（最小权限，M4）。allowed_tools 之外的工具型技能不加载。"""

    allowed_tools: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    """Agent 版本配置（声明式，入 agent_version.config）。T2.2 校验用，M2 精简版。"""

    prompt: str = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    executor: str = "lite-agent"
    model: str | None = None  # model_catalog.id；None 时由运行时取默认（M4）
    authority: AgentAuthority = Field(default_factory=AgentAuthority)  # 最小权限（M4）
    provenance: dict[str, Any] | None = None  # 生成出处（V2-A3 拼装记录：来自哪些 Skill）
    eval: dict[str, Any] | None = None  # 自动背书快照（V2-A4：judge 分/是否过/时间）


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    status: str
    source: str
    current_version: str | None = None
    role: str | None = None
    description: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    model: str | None = None


class ProvisionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)  # 公司名
    description: str | None = Field(default=None, max_length=500)  # 公司描述（缺省取预设描述）
    preset: str | None = None  # 预设名（精确选）
    keyword: str | None = None  # 关键词（确定性匹配预设）


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str | None = None
    role: str


class ProvisionedAgentOut(BaseModel):
    name: str
    role_name: str
    status: str
    capabilities: list[str]


class ProvisionOut(BaseModel):
    org: OrgOut
    preset: str
    agents: list[ProvisionedAgentOut]
