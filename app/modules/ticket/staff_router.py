"""
客服侧工单路由: 列表/领取/回复/关闭; 仅客服(cs)与管理员(admin)岗位可访问
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session
from app.modules.admin.dependencies import CurrentAdmin, require_role

from .schemas import (
    StaffReplyRequest,
    StaffUpdateStatusRequest,
    TicketDetail,
    TicketListResponse,
    TicketMessageItem,
    TicketSummary,
)
from .service import TicketService

router = APIRouter(
    prefix="/api/v1/admin/tickets",
    tags=["后台管理-工单"],
    dependencies=[Depends(require_role("cs"))],
)


def init_service(session: AsyncSession = Depends(get_session)) -> TicketService:
    return TicketService(session)


@router.get("", response_model=TicketListResponse, summary="工单列表(可按状态/类型筛选)")
async def list_tickets(
    status: Optional[str] = Query(default=None),
    ticket_type: Optional[str] = Query(default=None),
    service: TicketService = Depends(init_service),
):
    tickets, total = await service.list_for_staff(status, ticket_type)
    return TicketListResponse(
        items=[TicketSummary.model_validate(t) for t in tickets], total=total
    )


@router.get("/{ticket_id}", response_model=TicketDetail, summary="工单详情")
async def get_ticket(
    ticket_id: int,
    service: TicketService = Depends(init_service),
):
    ticket = await service.get_for_staff(ticket_id)
    detail = await service.get_detail(ticket.id)
    data = TicketSummary.model_validate(detail).model_dump()
    data["messages"] = [TicketMessageItem.model_validate(m) for m in detail.messages]
    return TicketDetail(**data)


@router.post("/{ticket_id}/actions", response_model=TicketSummary, summary="领取/关闭工单")
async def update_status(
    ticket_id: int,
    body: StaffUpdateStatusRequest,
    current: CurrentAdmin = Depends(require_role("cs")),
    service: TicketService = Depends(init_service),
):
    ticket = await service.get_for_staff(ticket_id)
    if body.action == "claim":
        await service.claim(ticket, current.admin_id)
    else:
        await service.close(ticket, current.admin_id)
    return TicketSummary.model_validate(ticket)


@router.post("/{ticket_id}/reply", response_model=TicketDetail, summary="回复客户")
async def reply(
    ticket_id: int,
    body: StaffReplyRequest,
    current: CurrentAdmin = Depends(require_role("cs")),
    service: TicketService = Depends(init_service),
):
    ticket = await service.get_for_staff(ticket_id)
    await service.reply(ticket, current.admin_id, body.content)
    detail = await service.get_detail(ticket.id)
    data = TicketSummary.model_validate(detail).model_dump()
    data["messages"] = [TicketMessageItem.model_validate(m) for m in detail.messages]
    return TicketDetail(**data)
