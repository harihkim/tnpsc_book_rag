"""SQLAlchemy types that persist application enum values without duplicating them."""

from enum import StrEnum

from sqlalchemy import Enum as SqlEnum


def _enum_values[EnumT: StrEnum](enum_class: type[EnumT]) -> list[str]:
    return [member.value for member in enum_class]


def string_enum_type[EnumT: StrEnum](
    enum_class: type[EnumT],
    *,
    name: str,
    length: int,
) -> SqlEnum[EnumT]:
    """Store the stable lowercase values of an application ``StrEnum``."""
    return SqlEnum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=_enum_values,
        length=length,
    )
