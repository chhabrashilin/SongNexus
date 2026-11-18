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
        "labelMates": True,  # the LABELS category; off by default in filters
        "play": True,
        "stories": True,
        "community": True,  # Around you: campus and city charts
        "ask": True,  # questions in the search bar (ADR 0008); works without a model
        "browse": True,  # home shelves and genre pages
        "recommendations": True,  # explained recommendations on artist pages
        "tasteProfile": True,  # Your Nexus: taste profiles from listening or a playlist
        "playlistImport": True,
        "signIn": True,
        "linkedAccounts": True,
        "linkResolver": True,  # open links shared from other music apps
        "friends": True,
        "leaderboards": True,  # opt-in game scores and campus leaderboards (ADR 0010)
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
