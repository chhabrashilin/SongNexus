from songnexus.resolution.matcher import Candidate, Decision, MatchPolicy, resolve


def test_unique_exact_name_is_matched() -> None:
    result = resolve(
        "Kendrick Lamar", [Candidate("k", "Kendrick Lamar", prior=1.0), Candidate("x", "Kendrick", prior=0.5)]
    )
    assert result.decision is Decision.MATCHED
    assert result.entity_id == "k"
    assert result.method == "exact_name"


def test_identical_names_are_ambiguous_even_with_different_priors() -> None:
    # Several MusicBrainz artists are called "Drake": never guess.
    result = resolve("Drake", [Candidate("a", "Drake", prior=1.0), Candidate("b", "Drake", prior=0.95)])
    assert result.decision is Decision.AMBIGUOUS
    assert result.entity_id is None


def test_alias_match_resolves_renamed_artist() -> None:
    result = resolve("Kanye West", [Candidate("ye", "Ye", aliases=("Kanye West", "Yeezy"), prior=1.0)])
    assert result.decision is Decision.MATCHED
    assert result.best is not None and result.best.matched_name == "Kanye West"


def test_close_typo_matches_when_unambiguous() -> None:
    result = resolve("Kendrik Lamar", [Candidate("k", "Kendrick Lamar", prior=0.9)])
    assert result.decision is Decision.MATCHED
    assert result.method == "fuzzy_name"


def test_near_duplicates_are_ambiguous() -> None:
    result = resolve(
        "Paul McCartney", [Candidate("a", "Paul McCartney", prior=1.0), Candidate("b", "Paul MacCartney", prior=0.95)]
    )
    assert result.decision is Decision.AMBIGUOUS


def test_unrelated_names_do_not_match() -> None:
    result = resolve("Herbie", [Candidate("h", "Herbie Hancock", prior=1.0)])
    assert result.decision is Decision.NO_MATCH


def test_empty_inputs() -> None:
    assert resolve("", [Candidate("a", "A")]).decision is Decision.NO_MATCH
    assert resolve("Someone", []).decision is Decision.NO_MATCH


def test_policy_thresholds_are_respected() -> None:
    strict = MatchPolicy(accept_threshold=0.999, review_threshold=0.5, min_margin=0.0, prior_weight=0.0)
    result = resolve("Kendrik Lamar", [Candidate("k", "Kendrick Lamar")], strict)
    assert result.decision is Decision.AMBIGUOUS


def test_ranking_is_deterministic_on_ties() -> None:
    candidates = [Candidate("b", "Same"), Candidate("a", "Same")]
    assert resolve("Same", candidates).ranked[0].candidate.entity_id == "a"
