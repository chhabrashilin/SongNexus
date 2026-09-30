import pytest

from songnexus.search.index import SearchDoc, SearchIndex


@pytest.fixture
def index() -> SearchIndex:
    idx = SearchIndex()
    idx.add(SearchDoc("artist", "k", "Kendrick Lamar", prior=1.0), names=["Kendrick Lamar"])
    idx.add(SearchDoc("artist", "kk", "Kevin Kendrick", prior=0.2), names=["Kevin Kendrick"])
    idx.add(SearchDoc("artist", "ye", "Ye", prior=1.0), names=["Ye"], aliases=["Kanye West", "Yeezy"])
    idx.add(SearchDoc("artist", "jz", "JAŸ-Z", prior=1.0), names=["JAŸ-Z"], aliases=["Hova"])
    idx.add(SearchDoc("artist", "w", "The Weeknd", prior=0.9), names=["The Weeknd"])
    idx.add(SearchDoc("track", "t1", "HUMBLE.", prior=0.5), names=["HUMBLE."])
    idx.add(SearchDoc("album", "a1", "DAMN.", prior=0.5), names=["DAMN."])
    return idx.freeze()


@pytest.mark.parametrize(
    ("query", "expected", "match_type"),
    [
        ("Kendrick Lamar", "k", "exact"),
        ("kendrick", "k", "prefix"),
        ("kendrik lamar", "k", "fuzzy"),
        ("lamar", "k", "token_prefix"),
        ("kanye west", "ye", "exact"),
        ("jay-z", "jz", "exact"),
        ("jayz", "jz", "exact"),
        ("hov", "jz", "prefix"),
        ("weeknd", "w", "exact"),
        ("humble", "t1", "exact"),
    ],
)
def test_top_hit(index: SearchIndex, query: str, expected: str, match_type: str) -> None:
    hits = index.search(query)
    assert hits[0].entity_id == expected
    assert hits[0].match_type == match_type


def test_primary_name_beats_alias_and_reports_what_matched(index: SearchIndex) -> None:
    hit = index.search("Yeezy")[0]
    assert hit.entity_id == "ye"
    assert hit.matched_on == "Yeezy"
    assert hit.score < index.search("Ye")[0].score


def test_type_filter(index: SearchIndex) -> None:
    assert [h.entity_type for h in index.search("damn", entity_types=frozenset({"album"}))] == ["album"]
    assert all(h.entity_type == "artist" for h in index.search("damn", entity_types=frozenset({"artist"})))


def test_empty_and_garbage_queries(index: SearchIndex) -> None:
    assert index.search("") == []
    assert index.search("!!!") == []
    assert index.search("zzzzqqqq") == []


def test_limit_and_deterministic_order(index: SearchIndex) -> None:
    first = index.search("k", limit=2)
    assert len(first) <= 2
    assert first == index.search("k", limit=2)


def test_frozen_index_rejects_writes(index: SearchIndex) -> None:
    with pytest.raises(RuntimeError):
        index.add(SearchDoc("artist", "x", "X"), names=["X"])
