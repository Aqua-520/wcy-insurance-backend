"""
客户侧工单路由: 我的工单列表/详情/发起/补充/重新打开
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_session
from app.modules.auth.dependencies import CurrentUser, get_current_user

from .schemas import (
    CreateTicketRequest,
    CustomerMessageRequest,
    TicketDetail,
    TicketListResponse,
    TicketMessageItem,
    TicketSummary,
)
from .service import TicketService

router = APIRouter(prefix="/api/v1/tickets", tags=["工单-客户侧"])


def init_service(session: AsyncSession = Depends(get_session)) -> TicketService:
    return TicketService(session)


@router.get("", response_model=TicketListResponse, summary="我的工单列表")
async def list_my_tickets(
    current: CurrentUser = Depends(get_current_user),
    service: TicketService = Depends(init_service),
):
    tickets = await service.list_by_user(current.user_id)
    return TicketListResponse(
        items=[TicketSummary.model_validate(t) for t in tickets], total=len(tickets)
    )


@router.post("", response_model=TicketSummary, status_code=201, summary="发起工单(投诉/理赔咨询)")
async def create_ticket(
    body: CreateTicketRequest,
    current: CurrentUser = Depends(get_current_user),
    service: TicketService = Depends(init_service),
):
    ticket = await service.create_from_user(current.user_id, body.ticket_type, body.summary)
    return TicketSummary.model_validate(ticket)


@router.get("/{ticket_id}", response_model=TicketDetail, summary="工单详情")
async def get_ticket(
    ticket_id: int,
    current: CurrentUser = Depends(get_current_user),
    service: TicketService = Depends(init_service),
):
    ticket = await service.get_owned_by_user(ticket_id, current.user_id)
    detail = await service.get_detail(ticket.id)
    data = TicketSummary.model_validate(detail).model_dump()
    data["messages"] = [TicketMessageItem.model_validate(m) for m in detail.messages]
    return TicketDetail(**data)


@router.post("/{ticket_id}/messages", response_model=TicketDetail, summary="补充说明")
async def add_message(
    ticket_id: int,
    body: CustomerMessageRequest,
    current: CurrentUser = Depends(get_current_user),
    service: TicketService = Depends(init_service),
):
    ticket = await service.get_owned_by_user(ticket_id, current.user_id)
    await service.add_customer_message(ticket, body.content)
    detail = await service.get_detail(ticket.id)
    data = TicketSummary.model_validate(detail).model_dump()
    data["messages"] = [TicketMessageItem.model_validate(m) for m in detail.messages]
    return TicketDetail(**data)


@router.post("/{ticket_id}/reopen", response_model=TicketSummary, summary="重新打开工单")
async def reopen_ticket(
    ticket_id: int,
    current: CurrentUser = Depends(get_current_user),
    service: TicketService = Depends(init_service),
):
    ticket = await service.get_owned_by_user(ticket_id, current.user_id)
    await service.reopen(ticket)
    return TicketSummary.model_validate(ticket)
