from hypothesis import example, given, settings
from hypothesis import strategies as st

from songnexus.core.search import (
    EntityType,
    EvalCase,
    MatchType,
    SearchDoc,
    SearchIndex,
    evaluate,
)

A, R, T = EntityType.ARTIST, EntityType.RELEASE, EntityType.RECORDING


def index() -> SearchIndex:
    idx = SearchIndex()
    idx.add(SearchDoc(A, "beyonce", "Beyoncé", prior=0.5), ["Beyoncé"])
    idx.add(
        SearchDoc(R, "beyonce-album", "BEYONCÉ", prior=1.0, artist_ids=("beyonce",)), ["BEYONCÉ"]
    )
    idx.add(SearchDoc(A, "paul", "Paul McCartney", prior=0.9), ["Paul McCartney"])
    idx.add(SearchDoc(R, "mccartney", "McCartney", prior=0.8, artist_ids=("paul",)), ["McCartney"])
    idx.add(SearchDoc(A, "bts", "BTS", prior=0.9), ["BTS"], ["방탄소년단", "Bangtan Boys"])
    idx.add(SearchDoc(A, "utada", "宇多田ヒカル", prior=0.7), ["宇多田ヒカル"], ["Hikaru Utada"])
    idx.add(SearchDoc(A, "fairuz", "فيروز", prior=0.6), ["فيروز"], ["Fairuz"])
    idx.add(SearchDoc(A, "kendrick", "Kendrick Lamar", prior=1.0), ["Kendrick Lamar"])
    idx.add(SearchDoc(T, "humble", "HUMBLE.", prior=0.4, artist_ids=("kendrick",)), ["HUMBLE."])
    idx.add(SearchDoc(A, "same-a", "Echo", prior=0.0), ["Echo"])
    idx.add(SearchDoc(R, "same-r", "Echo", prior=0.0), ["Echo"])
    return idx.freeze()


def top(idx: SearchIndex, query: str, **kwargs: object) -> list[str]:
    return [h.entity_id for h in idx.search(query, **kwargs)]  # type: ignore[arg-type]


def test_non_latin_names_and_aliases_are_searchable() -> None:
    idx = index()
    assert top(idx, "방탄소년단")[0] == "bts"
    assert top(idx, "宇多田ヒカル")[0] == "utada"
    assert top(idx, "宇多田")[0] == "utada"  # prefix in a script without spaces
    assert top(idx, "فيروز")[0] == "fairuz"
    assert top(idx, "hikaru utada")[0] == "utada"


def test_diacritics_case_and_typos() -> None:
    idx = index()
    assert top(idx, "beyonce")[0] == "beyonce"
    assert top(idx, "BEYONSE")[0] == "beyonce"
    assert top(idx, "kendrik lamar")[0] == "kendrick"
    assert top(idx, "lamar")[0] == "kendrick"  # token prefix


def test_eponymous_release_ranks_below_its_artist() -> None:
    idx = index()
    hits = idx.search("beyonce")
    assert [h.entity_id for h in hits[:2]] == ["beyonce", "beyonce-album"]


def test_eponymous_lift_adds_an_unmatched_artist() -> None:
    idx = index()
    hits = idx.search("mccartney")
    assert hits[0].entity_id == "paul"
    assert hits[1].entity_id == "mccartney"


def test_non_eponymous_work_does_not_lift_its_artist() -> None:
    hits = index().search("humble")
    assert [h.entity_id for h in hits] == ["humble"]


def test_equal_scores_prefer_artists() -> None:
    assert top(index(), "echo")[:2] == ["same-a", "same-r"]


def test_type_filter_and_exclusion() -> None:
    idx = index()
    assert top(idx, "beyonce", entity_types=frozenset({R})) == ["beyonce-album"]
    excluded = top(idx, "beyonce", exclude=frozenset({"beyonce"}))
    assert "beyonce" not in excluded
    assert excluded[0] == "beyonce-album"
    lifted = idx.search("mccartney", exclude=frozenset({"paul"}))
    assert all(h.entity_id != "paul" for h in lifted)


def test_empty_and_punctuation_queries() -> None:
    assert index().search("") == []
    assert index().search("!!!") == []


def test_exact_lookup() -> None:
    idx = index()
    assert [d.entity_id for d in idx.exact("Bangtan Boys")] == ["bts"]
    assert idx.exact("Echo", A)[0].entity_id == "same-a"


def test_frozen_index_rejects_additions() -> None:
    idx = index()
    try:
        idx.add(SearchDoc(A, "x", "X"), ["X"])
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError")


def test_match_types() -> None:
    idx = index()
    assert idx.search("BTS")[0].match_type is MatchType.EXACT
    assert idx.search("kendr")[0].match_type is MatchType.PREFIX
    # A lifted artist that matched directly keeps its own match type.
    assert idx.search("mccartney")[0].match_type is MatchType.TOKEN_PREFIX


def test_eponymous_lift_adds_an_artist_the_query_missed() -> None:
    idx = SearchIndex()
    idx.add(SearchDoc(A, "band", "Paul McCartney and Wings"), ["Paul McCartney and Wings"])
    idx.add(SearchDoc(R, "wings", "Wings", artist_ids=("band",)), ["Wings"])
    idx.freeze()
    hits = idx.search("wngs")  # a typo close to the title, far from the full name
    assert [(h.entity_id, h.match_type) for h in hits] == [
        ("band", MatchType.EPONYMOUS),
        ("wings", MatchType.FUZZY),
    ]


def test_evaluate_metrics() -> None:
    cases = [
        EvalCase("beyonce", "exact", frozenset({"beyonce"})),
        EvalCase("echo", "exact", frozenset({"same-r"})),  # rank 2
        EvalCase("zzzz", "missing", frozenset({"kendrick"})),  # not found
    ]
    report = evaluate(index(), cases)
    assert report.cases == 3
    assert report.mrr == (1 + 0.5 + 0) / 3
    assert report.precision_at_1 == 1 / 3
    assert report.misses == ("echo", "zzzz")
    assert report.by_category == {"exact": 0.75, "missing": 0.0}


@settings(max_examples=300, deadline=None)
@given(
    st.lists(st.text(alphabet="abcde xy", min_size=1, max_size=30), min_size=1, max_size=25),
    st.text(alphabet="abcde xy", min_size=1, max_size=30),
    st.sampled_from([0.5, 0.69, 0.8]),
)
# Adjacent transpositions destroy 4 trigrams; these only qualify under the 4k bound.
@example(names=["cfdc"], query="cdfc", floor=0.69)
@example(names=["abggccfbg"], query="agbgccfbg", floor=0.8)
def test_similar_docs_is_complete(names: list[str], query: str, floor: float) -> None:
    """The filtered lookup returns exactly what brute force over every key returns."""
    from songnexus.core.text import name_keys, normalize, string_similarity

    idx = SearchIndex()
    for i, name in enumerate(names):
        idx.add(SearchDoc(A, f"a{i}", name), [name])
    idx.freeze()
    q = normalize(query)
    if not q:
        return
    expected = {
        f"a{i}"
        for i, name in enumerate(names)
        if any(string_similarity(q, key) >= floor for key in name_keys(name))
    }
    assert {d.entity_id for d in idx.similar_docs(q, A, floor)} == expected
