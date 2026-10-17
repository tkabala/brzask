"""Declarative base and shared column types."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import Date, DateTime, Enum, MetaData, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Stable constraint names, so migrations can refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        str: Text(),
        datetime: DateTime(timezone=True),
        date: Date(),
        dict[str, Any]: JSONB(),
        list[str]: ARRAY(Text()),
    }


def text_enum(enum: type[StrEnum], name: str) -> Enum:
    """Store a StrEnum as text with a CHECK constraint.

    Native Postgres enums need a migration for every new value; a CHECK
    constraint is replaced in one statement.
    """
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=None,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
