"""Agent CRUD. Every query is scoped to the current user, so other users' agents look like 404."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, DbDep
from app.core.errors import AgentNameConflictError, NotFoundError
from app.models.agent import Agent
from app.models.user import User
from app.schemas.agent import AgentCreate, AgentRead, AgentUpdate

router = APIRouter(prefix="/agents", tags=["agents"])


def _get_owned_agent(db: Session, agent_id: uuid.UUID, user: User) -> Agent:
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.owner_id == user.id))
    if agent is None:
        raise NotFoundError("Agent not found")
    return agent


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:  # unique (owner_id, name)
        db.rollback()
        raise AgentNameConflictError() from exc


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
def create_agent(payload: AgentCreate, db: DbDep, current_user: CurrentUser) -> Agent:
    agent = Agent(
        owner_id=current_user.id,
        **payload.model_dump(exclude={"voice_config"}),
        voice_config=payload.voice_config.model_dump(),
    )
    db.add(agent)
    _commit(db)
    db.refresh(agent)
    return agent


@router.get("", response_model=list[AgentRead])
def list_agents(
    db: DbDep,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Agent]:
    query = (
        select(Agent)
        .where(Agent.owner_id == current_user.id)
        .order_by(Agent.created_at.desc(), Agent.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(query))


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent(agent_id: uuid.UUID, db: DbDep, current_user: CurrentUser) -> Agent:
    return _get_owned_agent(db, agent_id, current_user)


@router.patch("/{agent_id}", response_model=AgentRead)
def update_agent(agent_id: uuid.UUID, payload: AgentUpdate, db: DbDep, current_user: CurrentUser) -> Agent:
    agent = _get_owned_agent(db, agent_id, current_user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    _commit(db)
    db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent_id: uuid.UUID, db: DbDep, current_user: CurrentUser) -> Response:
    agent = _get_owned_agent(db, agent_id, current_user)
    db.delete(agent)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
