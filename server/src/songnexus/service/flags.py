"""Feature flags: launch gates and kill switches, served at ``/v1/config``.

Flags are configuration, not code: set ``SONGNEXUS_FLAGS`` to a JSON object to
override the defaults per environment (e.g. ``{"play": false}`` as a kill
switch). Unknown names are rejected at startup so typos fail loudly. Remove a
flag within two weeks of a full launch (plan §18).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

DEFAULT_FLAGS: Mapping[str, bool] = MappingProxyType(
    {
        "explore": True,
        "sixDegrees": True,
        "collaborations": True,
        "compare": True,
        "labelMates": False,
        # Off until their screens ship (M7, M6): the client never offers a surface
        # that doesn't exist.
        "play": False,
        "playlistImport": False,
        "signIn": True,
    }
)


def resolve_flags(overrides: Mapping[str, bool]) -> dict[str, bool]:
    """Returns the defaults with ``overrides`` applied.

    Raises:
        ValueError: An override names an unknown flag.
    """
    unknown = sorted(set(overrides) - set(DEFAULT_FLAGS))
    if unknown:
        raise ValueError(f"unknown feature flags: {unknown}")
    return {**DEFAULT_FLAGS, **overrides}
