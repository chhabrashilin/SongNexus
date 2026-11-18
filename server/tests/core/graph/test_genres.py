"""Genres from several sources, the genre hierarchy, and genre filtering (R2-1)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from songnexus.core.graph.filters import NodeFilter
from songnexus.core.graph.model import ArtistGraph
from songnexus.core.graph.projection import (
    ArtistFact,
    CatalogFacts,
    GenreFact,
    GenreInfo,
    build_graph,
)

MB = "musicbrainz-supplementary"
DISCOGS = "discogs"

VOCABULARY = [
    GenreInfo("g-hiphop", "hip hop"),
    GenreInfo("g-trap", "trap", ("g-hiphop",)),
    GenreInfo("g-drill", "drill", ("g-trap",)),
    GenreInfo("g-jazz", "jazz"),
    GenreInfo("g-bebop", "bebop", ("g-jazz",)),
    GenreInfo("g-funk", "funk"),
]


def _graph(genres: list[GenreFact], vocabulary: list[GenreInfo] = VOCABULARY) -> ArtistGraph:
    artists = sorted({g.artist_id for g in genres} | {"Unknown"})
    return build_graph(
        CatalogFacts(
            artists=[ArtistFact(a, a, "full") for a in artists],
            genres=genres,
            vocabulary=vocabulary,
        ),
        "test",
    )


def test_shares_are_averaged_per_source_not_summed_across_units() -> None:
    graph = _graph(
        [
            # MusicBrainz: 9 tag votes hip hop, 1 jazz.
            GenreFact("A", "g-hiphop", "hip hop", 9, MB),
            GenreFact("A", "g-jazz", "jazz", 1, MB),
            # Discogs: 1 master tagged jazz (a different unit; must not be outweighed by 9 votes).
            GenreFact("A", "g-jazz", "jazz", 1, DISCOGS),
        ]
    )
    node = graph.nodes["A"]
    assert node.genre_share("g-hiphop") == pytest.approx((0.9 + 0.0) / 2)
    assert node.genre_share("g-jazz") == pytest.approx((0.1 + 1.0) / 2)
    by_id = {g.genre_id: g for g in node.genres}
    assert by_id["g-jazz"].sources == (DISCOGS, MB)
    assert by_id["g-hiphop"].sources == (MB,)


def test_a_single_source_behaves_as_before() -> None:
    graph = _graph(
        [
            GenreFact("A", "g-hiphop", "hip hop", 8, DISCOGS),
            GenreFact("A", "g-jazz", "jazz", 2, DISCOGS),
        ]
    )
    assert graph.nodes["A"].genre_share("g-hiphop") == pytest.approx(0.8)


@given(
    st.lists(
        st.tuples(
            st.sampled_from(["g-hiphop", "g-trap", "g-jazz", "g-funk", "g-bebop"]),
            st.integers(1, 50),
            st.sampled_from([MB, DISCOGS]),
        ),
        min_size=1,
        max_size=10,
        unique_by=lambda t: (t[0], t[2]),
    )
)
def test_shares_never_exceed_one(facts: list[tuple[str, int, str]]) -> None:
    graph = _graph([GenreFact("A", g, g, votes, source) for g, votes, source in facts])
    total = sum(g.share for g in graph.nodes["A"].genres)
    assert 0 < total <= 1 + 1e-9


def test_with_subgenres_follows_the_hierarchy_transitively() -> None:
    graph = _graph([])
    assert graph.with_subgenres({"g-hiphop"}) == {"g-hiphop", "g-trap", "g-drill"}
    assert graph.with_subgenres({"g-trap"}) == {"g-trap", "g-drill"}
    assert graph.with_subgenres({"g-funk"}) == {"g-funk"}


def test_a_cycle_in_community_data_terminates() -> None:
    cyclic = [GenreInfo("g-a", "a", ("g-b",)), GenreInfo("g-b", "b", ("g-a",))]
    graph = _graph([], cyclic)
    assert graph.with_subgenres({"g-a"}) == {"g-a", "g-b"}
    assert graph.genre_artist_counts() == {}


def test_the_filter_counts_the_selection_combined() -> None:
    graph = _graph(
        [
            # 15% trap and 15% hip hop: 30% within hip hop including subgenres.
            GenreFact("A", "g-trap", "trap", 15, DISCOGS),
            GenreFact("A", "g-hiphop", "hip hop", 15, DISCOGS),
            GenreFact("A", "g-funk", "funk", 70, DISCOGS),
            GenreFact("B", "g-drill", "drill", 1, DISCOGS),
            GenreFact("C", "g-jazz", "jazz", 1, DISCOGS),
        ]
    )
    hip_hop = NodeFilter(genre_ids=graph.with_subgenres({"g-hiphop"}))
    assert hip_hop.allows(graph.nodes["A"])
    assert hip_hop.allows(graph.nodes["B"])  # drill is two levels below hip hop
    assert not hip_hop.allows(graph.nodes["C"])
    assert hip_hop.allows(graph.nodes["Unknown"])  # no genre data: kept by default
    # Without subgenres, A has only 15% hip hop: below the 20% threshold.
    assert not NodeFilter(genre_ids=frozenset({"g-hiphop"})).allows(graph.nodes["A"])


def test_genre_counts_include_artists_in_subgenres() -> None:
    graph = _graph(
        [
            GenreFact("A", "g-trap", "trap", 1, DISCOGS),
            GenreFact("B", "g-hiphop", "hip hop", 1, DISCOGS),
            GenreFact("C", "g-drill", "drill", 1, DISCOGS),
        ]
    )
    counts = graph.genre_artist_counts()
    assert counts["g-hiphop"] == (1, 3)
    assert counts["g-trap"] == (1, 2)
    assert counts["g-drill"] == (1, 1)
    assert "g-jazz" not in counts  # no artist at any level


def test_the_vocabulary_names_genres_no_artist_carries() -> None:
    graph = _graph([GenreFact("A", "g-drill", "drill", 1, DISCOGS)])
    assert graph.genre_names["g-hiphop"] == "hip hop"
    assert graph.genre_ids == {"g-drill"}  # carried genres only


def test_agreement_counts_hierarchy_matches_and_coverage() -> None:
    from songnexus.core.graph.genre_eval import genre_agreement

    a = _graph(
        [
            GenreFact("A", "g-trap", "trap", 1, MB),  # Discogs says hip hop: related
            GenreFact("B", "g-jazz", "jazz", 1, MB),  # Discogs says jazz: exact
            GenreFact("C", "g-funk", "funk", 1, MB),  # Discogs says bebop: disagree
        ]
    )
    b = _graph(
        [
            GenreFact("A", "g-hiphop", "hip hop", 1, DISCOGS),
            GenreFact("B", "g-jazz", "jazz", 1, DISCOGS),
            GenreFact("C", "g-bebop", "bebop", 1, DISCOGS),
        ]
    )
    report = genre_agreement(a, b)
    assert report.both == 3
    assert report.top1_exact == pytest.approx(1 / 3)
    assert report.top1_hierarchy == pytest.approx(2 / 3)
    assert report.mean_overlap == pytest.approx(1 / 3)
    assert report.covered_either == 3
