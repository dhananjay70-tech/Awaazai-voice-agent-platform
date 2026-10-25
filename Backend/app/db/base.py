"""Declarative base shared by all ORM models."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# All AwaazAI tables live in their own PostgreSQL schema, isolated from other projects sharing the database.
SCHEMA = "awaazai"

# Predictable constraint names keep Alembic migrations stable across databases.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)
