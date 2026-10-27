"""
后台产品管理路由
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session

from .dependencies import CurrentAdmin, get_current_admin
from .product_schemas import (
    ProductActivateRequest,
    ProductAdminCreate,
    ProductAdminDetail,
    ProductAdminListResponse,
    ProductAdminUpdate,
    ProductDeleteResponse,
)
from .product_service import AdminProductService

router = APIRouter(prefix="/api/v1/admin/products", tags=["后台管理-产品"])


async def init_product_service(session: AsyncSession = Depends(get_session)) -> AdminProductService:
    return AdminProductService(session)


@router.get("", response_model=ProductAdminListResponse, summary="管理端产品列表")
async def list_products(
    keyword: str | None = Query(None, description="按产品名称模糊搜索"),
    category: str | None = Query(None, description="险种分类"),
    status: str | None = Query(None, description="active / inactive / draft / all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _current: CurrentAdmin = Depends(get_current_admin),
    service: AdminProductService = Depends(init_product_service),
) -> ProductAdminListResponse:
    return await service.list_products(keyword, category, status, page, page_size)


@router.post("", response_model=ProductAdminDetail, status_code=201, summary="新建产品(草稿)")
async def create_product(
    body: ProductAdminCreate,
    _current: CurrentAdmin = Depends(get_current_admin),
    service: AdminProductService = Depends(init_product_service),
) -> ProductAdminDetail:
    return await service.create(body)


@router.get("/{product_id}", response_model=ProductAdminDetail, summary="产品详情")
async def get_product(
    product_id: int,
    _current: CurrentAdmin = Depends(get_current_admin),
    service: AdminProductService = Depends(init_product_service),
) -> ProductAdminDetail:
    return await service.get_detail(product_id)


@router.patch("/{product_id}", response_model=ProductAdminDetail, summary="编辑产品")
async def update_product(
    product_id: int,
    body: ProductAdminUpdate,
    _current: CurrentAdmin = Depends(get_current_admin),
    service: AdminProductService = Depends(init_product_service),
) -> ProductAdminDetail:
    return await service.update(product_id, body)


@router.post("/{product_id}/activate", response_model=ProductAdminDetail, summary="上架产品")
async def activate_product(
    product_id: int,
    body: ProductActivateRequest,
    _current: CurrentAdmin = Depends(get_current_admin),
    service: AdminProductService = Depends(init_product_service),
) -> ProductAdminDetail:
    return await service.activate(product_id, body.allow_empty)


@router.post("/{product_id}/deactivate", response_model=ProductAdminDetail, summary="下架产品")
async def deactivate_product(
    product_id: int,
    _current: CurrentAdmin = Depends(get_current_admin),
    service: AdminProductService = Depends(init_product_service),
) -> ProductAdminDetail:
    return await service.deactivate(product_id)


@router.delete("/{product_id}", response_model=ProductDeleteResponse, summary="删除产品")
async def delete_product(
    product_id: int,
    purge_kb: bool = Query(True, description="同时清理父块与向量"),
    purge_files: bool = Query(False, description="文档不再被其他产品绑定时删除源文件"),
    _current: CurrentAdmin = Depends(get_current_admin),
    service: AdminProductService = Depends(init_product_service),
) -> ProductDeleteResponse:
    return await service.delete(product_id, purge_kb=purge_kb, purge_files=purge_files)
