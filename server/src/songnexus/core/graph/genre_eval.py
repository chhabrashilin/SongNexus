"""How well two genre sources agree, and how many artists each covers (R2-1 evaluation).

Pure: takes two graphs built from the same catalog with different genre
sources. Agreement is measured on artists both sources describe:

* **top-1 agreement**: source A's top genre is among source B's genres, either
  exactly or through the hierarchy (one is a subgenre of the other). Sources
  differ in granularity (MusicBrainz "trap" vs Discogs "Hip Hop"), so exact
  matching alone would undercount real agreement; the exact rate is reported too.
* **weighted overlap**: the sum over genres of the smaller of the two shares,
  in [0, 1] (the same measure Compare uses between artists).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from songnexus.core.graph.model import ArtistGraph


@dataclass(frozen=True)
class GenreAgreement:
    """The evaluation report.

    Attributes:
        artists: Artists in the catalog.
        covered_a: Artists with genre data from source A, by detail level.
        covered_b: Artists with genre data from source B, by detail level.
        covered_either: Artists with genre data from either source.
        both: Artists described by both sources.
        top1_exact: Share of ``both`` whose A top genre B also carries.
        top1_hierarchy: Share of ``both`` whose A top genre B carries, or B
            carries a genre above or below it.
        mean_overlap: Mean weighted overlap over ``both``.
    """

    artists: int
    covered_a: dict[str, int]
    covered_b: dict[str, int]
    covered_either: int
    both: int
    top1_exact: float | None
    top1_hierarchy: float | None
    mean_overlap: float | None
    by_level_total: dict[str, int] = field(default_factory=dict)


def _related(graph: ArtistGraph, genre_id: str, others: set[str]) -> bool:
    return bool(graph.with_subgenres({genre_id}) & others) or any(
        genre_id in graph.with_subgenres({o}) for o in others
    )


def genre_agreement(a: ArtistGraph, b: ArtistGraph) -> GenreAgreement:
    """Compares the genres of two graphs over the same artists."""
    covered_a: Counter[str] = Counter()
    covered_b: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    either = both = exact = related = 0
    overlap_sum = 0.0
    for artist_id, node_a in a.nodes.items():
        node_b = b.nodes.get(artist_id)
        totals[node_a.detail_level] += 1
        has_a, has_b = bool(node_a.genres), bool(node_b and node_b.genres)
        covered_a[node_a.detail_level] += has_a
        covered_b[node_a.detail_level] += has_b
        either += has_a or has_b
        if not (has_a and has_b) or node_b is None:
            continue
        both += 1
        top = node_a.genres[0].genre_id
        genres_b = {g.genre_id for g in node_b.genres}
        exact += top in genres_b
        related += top in genres_b or _related(a, top, genres_b)
        shares_b = {g.genre_id: g.share for g in node_b.genres}
        overlap_sum += sum(min(g.share, shares_b.get(g.genre_id, 0.0)) for g in node_a.genres)
    return GenreAgreement(
        artists=len(a.nodes),
        covered_a=dict(sorted(covered_a.items())),
        covered_b=dict(sorted(covered_b.items())),
        covered_either=either,
        both=both,
        top1_exact=exact / both if both else None,
        top1_hierarchy=related / both if both else None,
        mean_overlap=overlap_sum / both if both else None,
        by_level_total=dict(sorted(totals.items())),
    )
