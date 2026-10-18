"""Parsing references people type: an ID or a name."""

# Largest value of a BIGINT identity column; larger numbers cannot be an ID.
MAX_ID = 2**63 - 1


def as_id(ref: str) -> int | None:
    """`ref` as a row ID when it is a plain number that fits the ID column, else None."""
    if not (ref.isascii() and ref.isdecimal()):
        return None
    value = int(ref)
    return value if value <= MAX_ID else None
