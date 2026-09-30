"""Deterministic, template-based sentences for graph evidence.

These sentences are generated from structured facts only, so they are always
true to the data. They are used by the path endpoint, the agent's
deterministic mode, and as the evidence the LLM mode must stay consistent with.
"""

from __future__ import annotations

from songnexus.graph.projection import KIND_WEIGHTS, ArtistGraph, Edge, Evidence

KIND_LABELS = {
    "performed_with": "performed together",
    "produced_for": "production",
    "co_produced": "co-production",
    "contributed_to": "contribution",
    "sampled": "sample",
    "engineered": "engineering",
    "member_of": "membership",
    "collaboration": "collaboration project",
    "supported": "supporting musician",
    "taught": "teacher",
}


def _q(title: str) -> str:
    return f"“{title}”"


def evidence_sentence(graph: ArtistGraph, edge: Edge, ev: Evidence) -> str:
    names = {edge.a: graph.nodes[edge.a].name, edge.b: graph.nodes[edge.b].name}
    title = graph.subject_titles.get(ev.subject_id, "an untitled work")
    work = f"the album {_q(title)}" if ev.subject_type == "album" else _q(title)
    a, b = names[edge.a], names[edge.b]
    ra, rb = ev.a_role, ev.b_role

    if ev.kind == "performed_with":
        if ra == "featured" and rb == "primary":
            return f"{a} is featured on {b}'s {work}"
        if rb == "featured" and ra == "primary":
            return f"{b} is featured on {a}'s {work}"
        return f"{a} and {b} are both credited performers on {work}"
    if ev.kind in {"produced_for", "contributed_to", "engineered", "sampled"}:
        # Exactly one side is the performer; orient the sentence around it.
        performer_is_b = rb in {"primary", "featured"}
        other, performer = (a, b) if performer_is_b else (b, a)
        other_role = ra if performer_is_b else rb
        performer_role = rb if performer_is_b else ra
        # Only a primary artist "owns" the work; a featured one appears on it.
        owned = f"{performer}'s {work}" if performer_role == "primary" else f"{work} (featuring {performer})"
        if ev.kind == "produced_for":
            return f"{other} produced {owned}"
        if ev.kind == "contributed_to":
            return f"{other} is credited ({other_role}) on {owned}"
        if ev.kind == "engineered":
            return f"{other} engineered {owned}"
        return f"{owned} samples {other}"
    if ev.kind == "co_produced":
        return f"{a} and {b} co-produced {work}"

    # Artist-to-artist relationships: roles say which side is which.
    subject, obj = (
        (a, b) if ra in {"member", "subgroup", "persona", "collaborator", "supporting musician", "teacher"} else (b, a)
    )
    if ev.kind == "member_of":
        if "persona" in (ra, rb):
            return f"{subject} is a performing name of {obj}"
        if "subgroup" in (ra, rb):
            return f"{subject} is a subgroup of {obj}"
        return f"{subject} is a member of {obj}"
    if ev.kind == "collaboration":
        return f"{subject} is part of the collaboration {obj}"
    if ev.kind == "supported":
        return f"{subject} has been a supporting musician for {obj}"
    if ev.kind == "taught":
        return f"{subject} was a teacher of {obj}"
    return f"{a} and {b} are connected ({ev.kind})"


def rank_evidence(graph: ArtistGraph, evidence: list[Evidence], kinds: frozenset[str]) -> list[Evidence]:
    """Most informative first: heavier kinds, then album/track title order."""
    usable = [ev for ev in evidence if ev.kind in kinds]
    return sorted(
        usable,
        key=lambda ev: (-KIND_WEIGHTS[ev.kind], graph.subject_titles.get(ev.subject_id, ""), ev.subject_id),
    )
