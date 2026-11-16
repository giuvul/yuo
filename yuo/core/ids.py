"""Identifiers: uuid7 everywhere, stored as 36-char lowercase text."""

import uuid


def new_id() -> str:
    return str(uuid.uuid7())


def is_uuid7(value: str) -> bool:
    return len(value) == 36 and value[14] == "7" and value == value.lower()
