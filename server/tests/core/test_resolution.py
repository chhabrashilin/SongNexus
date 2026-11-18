from songnexus.core.resolution import (
    Candidate,
    Decision,
    MatchPolicy,
    Resolution,
    ScoredCandidate,
    resolve,
)


def test_unique_exact_name_is_matched() -> None:
    result = resolve(
        "Kendrick Lamar",
        [Candidate("k", "Kendrick Lamar", prior=1.0), Candidate("x", "Kendrick", prior=0.5)],
    )
    assert result.decision is Decision.MATCHED
    assert result.entity_id == "k"
    assert result.method == "exact_name"


def test_identical_names_are_ambiguous_even_with_different_priors() -> None:
    # Several MusicBrainz artists are called "Drake": never guess.
    result = resolve(
        "Drake", [Candidate("a", "Drake", prior=1.0), Candidate("b", "Drake", prior=0.95)]
    )
    assert result.decision is Decision.AMBIGUOUS
    assert result.entity_id is None


def test_alias_match_resolves_renamed_artist() -> None:
    result = resolve(
        "Kanye West", [Candidate("ye", "Ye", aliases=("Kanye West", "Yeezy"), prior=1.0)]
    )
    assert result.decision is Decision.MATCHED
    assert result.best is not None
    assert result.best.matched_name == "Kanye West"


def test_non_latin_alias_resolves() -> None:
    result = resolve(
        "방탄소년단", [Candidate("bts", "BTS", aliases=("방탄소년단", "Bangtan Boys"))]
    )
    assert result.entity_id == "bts"


def test_close_typo_matches_when_unambiguous() -> None:
    result = resolve("Kendrik Lamar", [Candidate("k", "Kendrick Lamar", prior=0.9)])
    assert result.decision is Decision.MATCHED
    assert result.method == "fuzzy_name"


def test_near_duplicates_are_ambiguous() -> None:
    result = resolve(
        "Paul McCartney",
        [
            Candidate("a", "Paul McCartney", prior=1.0),
            Candidate("b", "Paul MacCartney", prior=0.95),
        ],
    )
    assert result.decision is Decision.AMBIGUOUS


def test_unrelated_names_do_not_match() -> None:
    assert (
        resolve("Herbie", [Candidate("h", "Herbie Hancock", prior=1.0)]).decision
        is Decision.NO_MATCH
    )


def test_empty_inputs() -> None:
    assert resolve("", [Candidate("a", "A")]).decision is Decision.NO_MATCH
    assert resolve("Someone", []).decision is Decision.NO_MATCH


def test_policy_thresholds_are_respected() -> None:
    strict = MatchPolicy(
        accept_threshold=0.999, review_threshold=0.5, min_margin=0.0, prior_weight=0.0
    )
    assert (
        resolve("Kendrik Lamar", [Candidate("k", "Kendrick Lamar")], strict).decision
        is Decision.AMBIGUOUS
    )


def test_ranking_is_deterministic_on_ties() -> None:
    candidates = [Candidate("b", "Same"), Candidate("a", "Same")]
    assert resolve("Same", candidates).ranked[0].candidate.entity_id == "a"


def test_resolve_batch_uses_the_index_and_keeps_order() -> None:
    from songnexus.core.resolution import resolve_batch
    from songnexus.core.search import EntityType, SearchDoc, SearchIndex

    index = SearchIndex()
    index.add(SearchDoc(EntityType.ARTIST, "bts", "BTS", prior=0.9), ["BTS"], ["방탄소년단"])
    index.add(SearchDoc(EntityType.ARTIST, "d1", "Drake", prior=1.0), ["Drake"])
    index.add(SearchDoc(EntityType.ARTIST, "d2", "Drake", prior=0.2), ["Drake"])
    index.add(SearchDoc(EntityType.RELEASE, "r", "BTS", prior=1.0), ["BTS"])
    index.freeze()

    results = resolve_batch(index, ["방탄소년단", "Drake", "bts", "Nobody Here"])
    assert [r.mention for r in results] == ["방탄소년단", "Drake", "bts", "Nobody Here"]
    assert results[0].entity_id == "bts"
    assert results[1].decision is Decision.AMBIGUOUS  # two artists called Drake
    assert results[2].entity_id == "bts"  # releases are not artist candidates
    assert results[3].decision is Decision.NO_MATCH


def test_evaluate_matches() -> None:
    from songnexus.core.resolution import evaluate_matches

    def res(mention: str, entity: str | None) -> Resolution:
        decision = Decision.MATCHED if entity else Decision.NO_MATCH
        best = ScoredCandidate(Candidate(entity, entity), 1.0, entity, 1.0) if entity else None
        return Resolution(mention, decision, "exact_name", 1.0, best)

    report = evaluate_matches(
        [res("a", "A"), res("b", "X"), res("c", None), res("d", "D")],
        ["A", "B", "C", None],
        ["exact", "exact", "typo", "absent"],
    )
    assert (report.matched, report.correct, report.positives) == (3, 1, 3)
    assert report.precision == 1 / 3
    assert report.recall == 1 / 3
    assert report.errors == (("b", "X", "B"), ("d", "D", None))
    assert report.by_category == {"absent": (0, 1, 0), "exact": (1, 2, 2), "typo": (0, 0, 1)}
