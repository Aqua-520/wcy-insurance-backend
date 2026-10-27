"""
后台产品管理请求/响应模型
"""
from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ProductCategory = Literal["medical", "critical_illness", "accident", "life"]


def _normalize_highlights(value: Optional[List[str]]) -> Optional[List[str]]:
    if value is None:
        return None
    result: list[str] = []
    for item in value:
        text = item.strip()
        if not text:
            continue
        if len(text) > 100:
            raise ValueError("单个亮点不能超过 100 个字符")
        if text not in result:
            result.append(text)
    if len(result) > 20:
        raise ValueError("产品亮点最多 20 项")
    return result


class ProductAdminCreate(BaseModel):
    """新建产品(默认保存为草稿)"""
    name: str = Field(..., min_length=1, max_length=200)
    category: ProductCategory
    insurer: str = Field(..., min_length=1, max_length=120)
    image_url: Optional[str] = Field(default=None, max_length=1000)
    description: Optional[str] = Field(default=None, max_length=5000)
    min_premium: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    max_premium: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    target_group: Optional[str] = Field(default=None, max_length=300)
    highlights: Optional[List[str]] = None
    document_id: Optional[UUID] = Field(default=None, description="绑定已有的知识库文档")

    @field_validator("name", "insurer")
    @classmethod
    def strip_required(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("该字段不能为空")
        return text

    @field_validator("image_url")
    @classmethod
    def check_image_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        text = value.strip()
        if not (text.startswith("http://") or text.startswith("https://")):
            raise ValueError("图片地址必须以 http:// 或 https:// 开头")
        return text

    @field_validator("highlights")
    @classmethod
    def check_highlights(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return _normalize_highlights(value)

    @model_validator(mode="after")
    def check_premium_range(self) -> "ProductAdminCreate":
        if (
            self.min_premium is not None
            and self.max_premium is not None
            and self.min_premium > self.max_premium
        ):
            raise ValueError("最低保费不能大于最高保费")
        return self


class ProductAdminUpdate(BaseModel):
    """编辑产品基础字段(未传字段保持不变)"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    category: Optional[ProductCategory] = None
    insurer: Optional[str] = Field(default=None, min_length=1, max_length=120)
    image_url: Optional[str] = Field(default=None, max_length=1000)
    description: Optional[str] = Field(default=None, max_length=5000)
    min_premium: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    max_premium: Optional[Decimal] = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    target_group: Optional[str] = Field(default=None, max_length=300)
    highlights: Optional[List[str]] = None
    document_id: Optional[UUID] = Field(default=None, description="换绑知识库文档")

    @field_validator("name", "insurer")
    @classmethod
    def strip_optional_required(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("该字段不能为空")
        return text

    @field_validator("image_url")
    @classmethod
    def check_image_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        text = value.strip()
        if not (text.startswith("http://") or text.startswith("https://")):
            raise ValueError("图片地址必须以 http:// 或 https:// 开头")
        return text

    @field_validator("highlights")
    @classmethod
    def check_highlights(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return _normalize_highlights(value)

    @model_validator(mode="after")
    def check_premium_range(self) -> "ProductAdminUpdate":
        if (
            self.min_premium is not None
            and self.max_premium is not None
            and self.min_premium > self.max_premium
        ):
            raise ValueError("最低保费不能大于最高保费")
        return self


class ProductAdminItem(BaseModel):
    """产品列表项"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    clause_name: Optional[str] = None
    category: str
    insurer: str
    image_url: Optional[str] = None
    description: Optional[str] = None
    min_premium: Optional[Decimal] = None
    max_premium: Optional[Decimal] = None
    target_group: Optional[str] = None
    highlights: Optional[List[str]] = None
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    chunk_count: int = 0
    active_job_id: Optional[UUID] = None


class ProductAdminDetail(ProductAdminItem):
    """产品详情, 额外带知识库状态"""
    has_markdown: bool = False
    table_count: int = 0
    document_id: Optional[UUID] = None
    document_status: Optional[str] = None
    needs_reingest: bool = False


class ProductAdminListResponse(BaseModel):
    items: List[ProductAdminItem]
    total: int
    page: int
    page_size: int


class ProductActivateRequest(BaseModel):
    allow_empty: bool = False


class ProductDeleteResponse(BaseModel):
    deleted: bool
    deleted_chunks: int
    deleted_vectors: bool
    vector_error: Optional[str] = None
    deleted_files: int = 0
