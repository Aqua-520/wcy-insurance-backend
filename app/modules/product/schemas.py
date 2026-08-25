# 此模块来定义请求和响应模型进行数据类型的约束
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, ConfigDict

# 1,查询产品列表的响应模型类
class ProductResponse(BaseModel):
    """保险产品响应模型（对应 API 返回的单个产品）"""

    model_config = ConfigDict(from_attributes=True)  # 支持从 ORM 对象转换

    id: int
    name: str
    clause_name: str
    category: str
    insurer: str
    image_url: Optional[str] = None
    description: Optional[str] = None
    min_premium: Optional[Decimal] = None  # 自动序列化为字符串
    max_premium: Optional[Decimal] = None
    target_group: Optional[str] = None
    highlights: Optional[List[str]] = None
    status: str

class ProductsResponse(BaseModel):
    """产品列表响应（对应你提供的 JSON 结构）"""

    items: List[ProductResponse]