from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from typing import TypeVar

T = TypeVar("T")


def unique_preserving_order(
    values: Iterable[T],
    *,
    key: Callable[[T], Hashable] | None = None,
) -> list[T]:
    seen: set[Hashable] = set()
    unique: list[T] = []
    for value in values:
        marker = key(value) if key is not None else value
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(value)
    return unique
