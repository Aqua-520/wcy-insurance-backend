"""
投保意向单请求/响应模型
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class IntentCreateRequest(BaseModel):
    """客户提交投保意向"""
    product_id: int
    plan_id: Optional[str] = Field(default=None, max_length=64)
    plan_item_id: Optional[str] = Field(default=None, max_length=64)
    customer_name: str = Field(..., min_length=1, max_length=100)
    customer_phone: str = Field(..., min_length=5, max_length=30)
    remark: str = Field(default="", max_length=1000)


class IntentSummary(BaseModel):
    """意向单摘要"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    intent_no: str
    user_id: Optional[int] = None
    product_id: Optional[int] = None
    customer_name: str
    customer_phone: str
    remark: str
    status: str
    handle_note: str
    # ---- 跟进过程管理 ----
    last_result: Optional[str] = None
    follow_count: int = 0
    next_follow_at: Optional[datetime] = None
    overdue: bool = False  # 超时未跟进(SLA 预警), 由服务层计算
    # datetime 由 pydantic 自动序列化为 ISO 字符串返回给前端
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class IntentListResponse(BaseModel):
    items: list[IntentSummary]
    total: int


class IntentHandleRequest(BaseModel):
    """客服更新跟进状态"""
    status: str = Field(..., pattern="^(contacted|converted|closed)$")
    handle_note: str = Field(default="", max_length=1000)


class IntentFollowCreate(BaseModel):
    """仅记录一次跟进(不改状态), 如"电话未接通, 约定明天再联系" """
    note: str = Field(..., min_length=1, max_length=1000)
    method: Optional[str] = Field(
        default=None, pattern="^(phone|wechat|meeting|other)$", description="跟进方式"
    )
    result: Optional[str] = Field(
        default=None,
        pattern="^(interested|waiting|budget|unreachable|competitor|other)$",
        description="结果标签: interested 有意向 / waiting 待考虑 / budget 预算不足 / unreachable 联系不上 / competitor 已买别家 / other 其他",
    )
    next_follow_at: Optional[datetime] = Field(default=None, description="下次跟进时间(SLA 依据)")


class IntentFollowItem(BaseModel):
    """跟进记录时间线条目"""
    id: int
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    note: str
    method: Optional[str] = None
    result: Optional[str] = None
    admin_id: Optional[int] = None
    admin_name: Optional[str] = None
    created_at: Optional[datetime] = None


class IntentFollowListResponse(BaseModel):
    items: list[IntentFollowItem]
    total: int


class PolicyRegisterRequest(BaseModel):
    """保单登记(线下完成投保手续后记账, 非出单)"""
    policy_number: str = Field(..., min_length=1, max_length=60, description="保单号(线下保司出具)")
    effective_at: datetime = Field(..., description="保障起期")
    expires_at: Optional[datetime] = Field(default=None, description="保障止期(续期提醒依据)")
    holder_name: Optional[str] = Field(default=None, max_length=100, description="投保人")
    insured_name: Optional[str] = Field(default=None, max_length=100, description="被保人")
    insured_phone: Optional[str] = Field(default=None, max_length=30, description="被保人电话")
    coverage_amount: Optional[Decimal] = Field(default=None, ge=0, description="保额")
    premium_amount: Optional[Decimal] = Field(default=None, ge=0, description="保费")
    payment_frequency: Optional[str] = Field(
        default=None, pattern="^(annual|semi_annual|quarterly|monthly)$", description="缴费频率"
    )
    beneficiary: Optional[dict] = Field(default=None, description="受益人信息")


class PolicyItem(BaseModel):
    """保单摘要(客户/后台共用)"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    policy_number: str
    status: str
    product_id: int
    application_no: Optional[str] = None
    holder_name: Optional[str] = None
    insured_name: Optional[str] = None
    effective_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    coverage_amount: Optional[Decimal] = None
    premium_amount: Optional[Decimal] = None
    payment_frequency: Optional[str] = None
