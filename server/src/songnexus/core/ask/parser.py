"""The deterministic question parser: common phrasings to intents, with no model.

It runs first on every question and is the whole interpreter when no model is
configured, so it covers the phrasings people actually type ("how is X
connected to Y", "X vs Y", "who produced HUMBLE.", "Kendrick's producers in
2015", "artists like Bjork"). Matching is case- and punctuation-insensitive;
quoted names are kept whole even when they contain "and", "to" or "vs".

The parser never resolves names: it returns them as written, and the resolver
decides what they refer to. It returns None when a question doesn't match any
known shape, so the caller can ask the model (or say it didn't understand).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from dataclasses import replace

from songnexus.core.ask.intents import (
    MAX_MENTION_LENGTH,
    CreditRole,
    Intent,
    Interpretation,
    SongRef,
)
from songnexus.core.graph.collaborations import CollaborationType, ProductionDirection
from songnexus.core.text import normalize

# Plain text with at most this many words and no question shape is a lookup.
MAX_LOOKUP_WORDS = 6
# "the 30s" to "the 90s" are 1900s; "the 00s", "the 10s" and "the 20s" are 2000s.
FIRST_20TH_CENTURY_DECADE = 3

_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "‘": "'", "’": "'"})
_WS = re.compile(r"\s+")
_QUOTED = re.compile(r'"([^"]+)"')
_PLACEHOLDER = re.compile(r"\x01(\d+)\x01")
_FILLER_PREFIXES = re.compile(
    r"^(?:(?:hey|hi|ok|okay|so|yo|um|please)\b[,!]?\s*"
    r"|(?:can|could|would|will) you (?:please )?(?:tell me|show me|find|look up|show)\s+"
    r"|(?:i want to know|i wonder|i'm curious|i am curious|tell me|show me|i'd like to know"
    r"|do you know|let me see|give me|find me|quick question)[,:]?\s+)",
    re.IGNORECASE,
)
_TRAILING = re.compile(r"[\s?!.,;:]+$")
_NAME_PREFIXES = re.compile(
    r"^(?:the (?:song|track|single|tune|artist|rapper|singer|producer|musician|group) "
    r"|(?:song|track|single|artist|rapper|singer|producer|musician) )",
    re.IGNORECASE,
)
_NAME_SUFFIXES = re.compile(
    r"(?: together| ever| before| at all| please| the most| most often| most| often)+$",
    re.IGNORECASE,
)
_PRONOUNS = frozenset(
    {"who", "what", "it", "them", "he", "she", "they", "him", "her", "me", "you", "i", "we", "us"}
)
_QUESTION_START = re.compile(
    r"^(?:who|whom|what|which|how|why|when|where|did|does|do|is|are|was|were|has|have|can"
    r"|could|should|would|will|list|show|tell|find|compare)\b",
    re.IGNORECASE,
)

_ARTISTS_WORD = r"(?:artists?|musicians?|people|singers?|rappers?|bands?|groups?|producers?|acts?)"
_WORKED = (
    r"(?:worked|work|collaborated|collaborate|recorded|record|performed|perform|made music"
    r"|make music|teamed up|team up|played|play)"
)
_ADJECTIVES = (
    r"(?:(?:most )?(?:frequent|top|main|best|closest|regular|usual|favorite|favourite|biggest"
    r"|key|common|all|notable) )*"
)
_WHAT = {
    "collaborators": None,
    "collaborations": None,
    "collabs": None,
    "collab": None,
    "co-stars": None,
    "partners": None,
    "features": CollaborationType.FEATURE,
    "featured artists": CollaborationType.FEATURE,
    "feature": CollaborationType.FEATURE,
    "guests": CollaborationType.FEATURE,
    "producers": CollaborationType.PRODUCTION,
    "producer": CollaborationType.PRODUCTION,
    "bands": CollaborationType.BAND,
    "groups": CollaborationType.BAND,
    "band members": CollaborationType.BAND,
    "members": CollaborationType.BAND,
    "side projects": CollaborationType.BAND,
    "samples": CollaborationType.CREDIT,
    "credits": CollaborationType.CREDIT,
}
_WEB_WORDS = (
    "connections",
    "connection web",
    "network",
    "circle",
    "web",
    "similar artists",
    "related artists",
    "neighbors",
    "neighbours",
    "orbit",
)
_WHAT_PATTERN = "|".join(re.escape(w) for w in sorted([*_WHAT, *_WEB_WORDS], key=len, reverse=True))
_WORKS = r"(?:songs?|tracks?|music|records?|albums?|work|discography|catalog(?:ue)?)"


def _cleanup(query: str) -> str:
    text = _WS.sub(" ", query.translate(_QUOTES)).strip()
    previous = None
    while previous != text:
        previous = text
        text = _FILLER_PREFIXES.sub("", text).strip()
    return _TRAILING.sub("", text)


class _Quoted:
    """Quoted segments, swapped for placeholders so "and" inside a title is not a separator."""

    def __init__(self, text: str) -> None:
        self.values: list[str] = []

        def keep(match: re.Match[str]) -> str:
            self.values.append(match.group(1).strip())
            return f"\x01{len(self.values) - 1}\x01"

        self.text = _QUOTED.sub(keep, text)

    def restore(self, text: str) -> str:
        return _PLACEHOLDER.sub(lambda m: self.values[int(m.group(1))], text)

    def is_quoted(self, text: str) -> bool:
        return bool(_PLACEHOLDER.fullmatch(text.strip()))


def _name(raw: str | None, quoted: _Quoted) -> str | None:
    """Tidies a captured name; None when it is empty, a pronoun or too long."""
    if raw is None:
        return None
    was_quoted = quoted.is_quoted(raw)
    text = quoted.restore(raw).strip().strip("\"'").strip()
    if not was_quoted:
        text = _NAME_PREFIXES.sub("", text)
        text = _NAME_SUFFIXES.sub("", text)
        text = re.sub(r"(?:'s|s')$", lambda m: "" if m.group(0) == "'s" else "s", text)
        text = _TRAILING.sub("", text).strip()
    if not text or text.casefold() in _PRONOUNS or len(text) > MAX_MENTION_LENGTH:
        return None
    return text


def _song(raw: str | None, quoted: _Quoted) -> SongRef | None:
    """A song mention: "Title", "Title by Artist", "Artist's Title" or a quoted title."""
    if raw is None:
        return None
    match = re.fullmatch(r"(?P<t>.+?) (?:by|from) (?P<a>.+)", raw, re.IGNORECASE)
    if match:
        title, artist = _name(match["t"], quoted), _name(match["a"], quoted)
        if title and artist:
            return SongRef(title, artist)
    match = re.fullmatch(r"(?P<a>[^\x01]+?)(?:'s|') (?P<t>\x01\d+\x01)", raw)
    if match:
        title, artist = _name(match["t"], quoted), _name(match["a"], quoted)
        if title and artist:
            return SongRef(title, artist)
    title = _name(raw, quoted)
    return SongRef(title) if title else None


def _years(text: str) -> tuple[str, int | None, int | None]:
    """Removes a year phrase ("in 2015", "from 2010 to 2015", "in the 90s", "since 2018")."""
    year = r"((?:19|20)\d{2})"
    rules: list[tuple[str, Callable[[re.Match[str]], tuple[int | None, int | None]]]] = [
        (
            rf"\b(?:between|from) {year} (?:and|to|through|until|-) {year}\b",
            lambda m: (int(m[1]), int(m[2])),
        ),
        (rf"\b(?:in )?{year} ?(?:-|to) ?{year}\b", lambda m: (int(m[1]), int(m[2]))),
        (
            r"\b(?:in |during |from )?(?:the )?((?:19|20)?\d)0'?s\b",
            lambda m: _decade(m[1]),
        ),
        (rf"\b(?:since|from|starting in) {year}\b", lambda m: (int(m[1]), None)),
        (rf"\bafter {year}\b", lambda m: (int(m[1]) + 1, None)),
        (rf"\bbefore {year}\b", lambda m: (None, int(m[1]) - 1)),
        (rf"\b(?:until|through|up to|by) {year}\b", lambda m: (None, int(m[1]))),
        (rf"\b(?:in|during) {year}\b", lambda m: (int(m[1]), int(m[1]))),
    ]
    for pattern, years in rules:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start, end = years(match)
            rest = _WS.sub(" ", text[: match.start()] + " " + text[match.end() :]).strip()
            return rest, start, end
    return text, None, None


def _decade(digits: str) -> tuple[int, int]:
    if len(digits) == 1:  # "the 90s"
        start = (1900 if int(digits) >= FIRST_20TH_CENTURY_DECADE else 2000) + int(digits) * 10
    else:  # "the 1990s", "the 2010s"
        start = int(digits) * 10
    return start, start + 9


def _split_genre(head: str, genres: Collection[str]) -> tuple[str, str | None]:
    """Splits "Kendrick Lamar's jazz" or "Kendrick Lamar jazz" into artist and genre."""
    possessive = re.fullmatch(r"(?P<a>.+?)(?:'s|') (?P<g>.+)", head)
    if possessive:
        return possessive["a"], possessive["g"]
    tokens = head.split()
    for size in (3, 2, 1):
        if len(tokens) > size and normalize(" ".join(tokens[-size:])) in genres:
            return " ".join(tokens[:-size]), " ".join(tokens[-size:])
    return head, None


Builder = Callable[[re.Match[str], _Quoted], Interpretation | None]


def _path(match: re.Match[str], quoted: _Quoted) -> Interpretation | None:
    a, b = _name(match["a"], quoted), _name(match["b"], quoted)
    if not a or not b:
        return None
    strongest = "strongest" in match.string.casefold()
    return Interpretation(Intent.FIND_PATH, artists=(a, b), strongest=strongest)


def _compare(match: re.Match[str], quoted: _Quoted) -> Interpretation | None:
    kind = (match.groupdict().get("kind") or "").casefold()
    raw_a, raw_b = match["a"], match["b"]
    songs_hint = kind.startswith(("song", "track")) or (
        quoted.is_quoted(raw_a) and quoted.is_quoted(raw_b)
    )
    by = re.compile(r".+ (?:by|from) .+", re.IGNORECASE)
    if songs_hint or (by.fullmatch(raw_a) and by.fullmatch(raw_b)):
        a, b = _song(raw_a, quoted), _song(raw_b, quoted)
        if a and b:
            return Interpretation(Intent.COMPARE_SONGS, songs=(a, b))
        return None
    names = _name(raw_a, quoted), _name(raw_b, quoted)
    if not names[0] or not names[1]:
        return None
    return Interpretation(Intent.COMPARE_ARTISTS, artists=(names[0], names[1]))


def _credits(role: CreditRole) -> Builder:
    def build(match: re.Match[str], quoted: _Quoted) -> Interpretation | None:
        raw = match["s"]
        # "who performed with X" is about an artist's collaborators.
        if raw.casefold().startswith(("with ", "alongside ")):
            artist = _name(raw.split(" ", 1)[1], quoted)
            if not artist:
                return None
            return Interpretation(
                Intent.COLLABORATORS,
                artists=(artist,),
                collaboration_type=CollaborationType.FEATURE,
            )
        # "who featured on Kendrick's songs" asks about an artist, not one song.
        works = re.fullmatch(rf"(?P<a>.+?)(?:'s|')? {_WORKS}", raw, re.IGNORECASE)
        if works and role in (CreditRole.PRODUCER, CreditRole.FEATURED):
            artist = _name(works["a"], quoted)
            if not artist:
                return None
            if role is CreditRole.PRODUCER:
                return Interpretation(
                    Intent.COLLABORATORS,
                    artists=(artist,),
                    collaboration_type=CollaborationType.PRODUCTION,
                    direction=ProductionDirection.PRODUCED_BY,
                )
            return Interpretation(
                Intent.COLLABORATORS,
                artists=(artist,),
                collaboration_type=CollaborationType.FEATURE,
            )
        song = _song(raw, quoted)
        return (
            Interpretation(Intent.SONG_CREDITS, songs=(song,), credit_role=role) if song else None
        )

    return build


def _collaborators(
    collaboration_type: CollaborationType | None, direction: ProductionDirection | None = None
) -> Builder:
    def build(match: re.Match[str], quoted: _Quoted) -> Interpretation | None:
        artist = _name(match["a"], quoted)
        if not artist:
            return None
        genre = _name(match.groupdict().get("g"), quoted)
        return Interpretation(
            Intent.COLLABORATORS,
            artists=(artist,),
            collaboration_type=collaboration_type,
            direction=direction,
            genre=genre,
        )

    return build


def _connections(match: re.Match[str], quoted: _Quoted) -> Interpretation | None:
    artist = _name(match["a"], quoted)
    return Interpretation(Intent.CONNECTIONS, artists=(artist,)) if artist else None


def _lookup(match: re.Match[str], quoted: _Quoted) -> Interpretation | None:
    text = _name(match["t"], quoted)
    return Interpretation(Intent.LOOKUP, text=text) if text else None


def _rules() -> list[tuple[re.Pattern[str], Builder]]:
    a, b = r"(?P<a>.+?)", r"(?P<b>.+?)"
    connected = r"(?:connected|linked|related|tied|connect|link)"
    path_noun = (
        r"(?:what(?:'s| is| are) )?(?:the )?(?:shortest |strongest |fastest |quickest )?"
        r"(?:path|connection|link|route|chain|way|degrees? of separation)s?"
    )
    rules: list[tuple[str, Builder]] = [
        # Production direction first: "who produced for X" is about an artist.
        (
            rf"who (?:has |have )?(?:produced|produces|prod\.?|made beats|makes beats) for {a}",
            _collaborators(CollaborationType.PRODUCTION, ProductionDirection.PRODUCED_BY),
        ),
        (
            rf"(?:who|what|which (?:artists|songs|tracks)) (?:has|did|does) {a} "
            rf"(?:produced?|made beats|make beats)(?: for)?",
            _collaborators(CollaborationType.PRODUCTION, ProductionDirection.PRODUCED_FOR),
        ),
        (
            rf"(?:who|which artists) (?:has|did|does) {a} (?:featured?|bring on|brought on)"
            rf"(?: on| with)?(?: {_WORKS})?",
            _collaborators(CollaborationType.FEATURE),
        ),
        # Paths.
        (rf"{a} ?(?:->|→|=>|⇒) ?{b}", _path),
        (rf"how (?:is|are|was|were|does|do|did) {a} {connected} (?:to|with) {b}", _path),
        (rf"how (?:is|are|was|were|do|does|did) {a} and {b} {connected}(?: together)?", _path),
        (rf"(?:is|are|was|were) {a} {connected} (?:to|with) {b}", _path),
        (rf"(?:is|are|was|were) {a} and {b} {connected}(?: together)?", _path),
        (rf"{path_noun} (?:from|between) {a} (?:to|and) {b}", _path),
        (
            rf"(?:six|6) degrees(?: of separation)?(?: (?:from|between|of))? {a} (?:to|and) {b}",
            _path,
        ),
        (
            rf"(?:how many )?(?:steps|degrees|hops|links)(?: of separation)? "
            rf"(?:from|between|separate) {a} (?:to|and|from) {b}",
            _path,
        ),
        (rf"how (?:far|close) (?:is|are) {a} (?:from|to) {b}", _path),
        (rf"how (?:far apart|close) are {a} and {b}", _path),
        (
            rf"(?:did|has|have|does|do) {a} (?:ever )?(?:{_WORKED}|featured?|appear|appeared)"
            rf"(?: on anything| on a song| on a track)? (?:with|on|alongside) {b}",
            _path,
        ),
        (rf"(?:did|have|has|do) {a} and {b} (?:ever )?{_WORKED}(?: together)?", _path),
        (rf"(?:connect|link|join) {a} (?:to|and|with) {b}", _path),
        (rf"from {a} to {b}", _path),
        # Comparisons.
        (
            rf"compare (?:the )?(?:(?P<kind>songs?|tracks?|artists?) )?{a} "
            rf"(?:and|vs\.?|versus|with|to|against|&) {b}",
            _compare,
        ),
        (
            rf"(?:what(?:'s| is| are) )?(?:the )?(?:differences?|similarit(?:y|ies)|overlap)"
            rf" between {a} and {b}",
            _compare,
        ),
        (rf"what do {a} and {b} have in common", _compare),
        (rf"how (?:does|do|is|are) {a} compare (?:to|with|against) {b}", _compare),
        (rf"{a} (?:vs\.?|versus|compared (?:to|with)) {b}", _compare),
        (rf"{a} and {b} compared", _compare),
        # Connection web (before "is X similar to Y" comparisons).
        (
            rf"(?:(?:similar |related |more )?{_ARTISTS_WORD}|music|more|anyone|someone|stuff)"
            rf" (?:like|similar to|connected to|related to|close to|linked to|around|associated"
            rf" with|in the orbit of|in the circle of) {a}",
            _connections,
        ),
        (
            rf"(?:who|what {_ARTISTS_WORD}|which {_ARTISTS_WORD}) (?:is|are) (?:similar to|like"
            rf"|connected to|related to|close to|linked to|associated with|around) {a}",
            _connections,
        ),
        (rf"who (?:is|are) {a} (?:connected|linked|related|close) (?:to|with)", _connections),
        (
            rf"(?:who|what) (?:else )?(?:should i|can i|to) (?:listen to|check out|try|hear) "
            rf"(?:if i like|if you like|after|for fans of) {a}",
            _connections,
        ),
        (
            rf"(?:explore|map|graph|web of|network of|connection web of|connections of"
            rf"|connections for|show (?:me )?(?:the )?(?:web|network|connections) (?:of|for|around)"
            rf"|similar to|if i like|for fans of|fans of) {a}",
            _connections,
        ),
        (rf"(?:is|are) {a} (?:similar|alike|comparable) to {b}", _compare),
        # Song credits.
        (
            r"who (?:produced|prod\.?|made the beat (?:for|on|of)|made the beat to|is behind the"
            r" beat (?:on|of|for)) (?P<s>.+)",
            _credits(CreditRole.PRODUCER),
        ),
        (
            r"(?:who(?:'s| is| was| are| were) )?(?:the )?producers? "
            r"(?:of|on|for|behind) (?P<s>.+)",
            _credits(CreditRole.PRODUCER),
        ),
        (
            r"who(?:'s| is| was| are| were) (?:the )?(?:featured|feature|features|guest|guests"
            r"|featured artists?|featured guests?) (?:on|in) (?P<s>.+)",
            _credits(CreditRole.FEATURED),
        ),
        (
            r"who (?:features|featured|is featured|was featured|appears|appeared|raps|rapped"
            r"|guested|has a verse|had a verse) (?:on|in) (?P<s>.+)",
            _credits(CreditRole.FEATURED),
        ),
        (
            r"(?:features?|featured artists?|guests?) (?:on|in) (?P<s>.+)",
            _credits(CreditRole.FEATURED),
        ),
        (
            r"who (?:sang|sings|performed|performs|recorded|released) (?P<s>.+)",
            _credits(CreditRole.PERFORMER),
        ),
        (
            r"(?:(?:full |all )?credits|who(?:'s| is| was| were) credited) (?:for|on|of) (?P<s>.+)",
            _credits(CreditRole.ALL),
        ),
        (
            r"who (?:worked on|made|wrote|is credited on|played on|was involved in|contributed to"
            r"|is on|was on|'s on) (?P<s>.+)",
            _credits(CreditRole.ALL),
        ),
        (r"(?P<s>.+?) (?:song )?credits", _credits(CreditRole.ALL)),
    ]
    return [(re.compile(pattern, re.IGNORECASE), build) for pattern, build in rules]


def _collaborator_rules() -> list[tuple[re.Pattern[str], Builder]]:
    a = r"(?P<a>.+?)"
    genre_tail = r"(?: in (?P<g>.+?))?"
    rules: list[tuple[str, Builder]] = [
        (
            rf"(?:who|which {_ARTISTS_WORD}) (?:has|have|did|does|do) {a} (?:ever )?{_WORKED}"
            rf" with(?: the most| most(?: often)?)?{genre_tail}",
            _collaborators(None),
        ),
        (
            rf"(?:which|what) (?P<g>.+?) {_ARTISTS_WORD} (?:has|have|did|does) {a} {_WORKED} with",
            _collaborators(None),
        ),
        (
            rf"(?:which|what) (?:bands|groups|projects) (?:is|was|has|have|were) {a} (?:been )?"
            rf"(?:in|a member of|part of|a part of)",
            _collaborators(CollaborationType.BAND),
        ),
        (rf"who (?:sampled|samples|has sampled) {a}", _collaborators(CollaborationType.CREDIT)),
    ]
    return [(re.compile(pattern, re.IGNORECASE), build) for pattern, build in rules]


_RULES = _rules()
_COLLABORATOR_RULES = _collaborator_rules()
_LOOKUP_RULE = re.compile(
    r"(?:who|what)(?:'s| is| was| are| were) (?P<t>.+)"
    r"|(?:search(?: for)?|look up|lookup|find|open|go to|show(?: me)?|play|tell me about"
    r"|info(?:rmation)? (?:on|about)|about) (?P<t2>.+)",
    re.IGNORECASE,
)
_WHAT_RULE = re.compile(
    rf"(?:(?:list|show|all|the|show me|list of)(?: the| all)? )?(?:(?:of|for) )?"
    rf"(?P<head>.+?) {_ADJECTIVES}(?P<what>{_WHAT_PATTERN})",
    re.IGNORECASE,
)
_WHAT_OF_RULE = re.compile(
    rf"(?:(?:the|all|list|show|show me)(?: the| all)? )?{_ADJECTIVES}(?P<what>{_WHAT_PATTERN})"
    rf" (?:of|for|with|by|from) (?P<head>.+)",
    re.IGNORECASE,
)


def _what(match: re.Match[str], quoted: _Quoted, genres: Collection[str]) -> Interpretation | None:
    what = match["what"].casefold()
    head = match["head"]
    if _QUESTION_START.match(head):  # "who is the best producer" names no artist
        return None
    if what in _WEB_WORDS:
        artist = _name(head, quoted)
        return Interpretation(Intent.CONNECTIONS, artists=(artist,)) if artist else None
    raw_artist, raw_genre = (
        _split_genre(head, genres) if not quoted.is_quoted(head) else (head, None)
    )
    artist = _name(raw_artist, quoted)
    if not artist:
        return None
    collaboration_type = _WHAT[what]
    direction = (
        ProductionDirection.PRODUCED_BY
        if collaboration_type is CollaborationType.PRODUCTION
        else None
    )
    return Interpretation(
        Intent.COLLABORATORS,
        artists=(artist,),
        collaboration_type=collaboration_type,
        direction=direction,
        genre=_name(raw_genre, quoted),
    )


def parse(query: str, genres: Collection[str] = frozenset()) -> Interpretation | None:
    """Interprets a question, or returns None when it matches no known shape.

    Args:
        query: What the person typed.
        genres: Normalized genre names, to split "Kendrick Lamar jazz collaborators".
    """
    text = _cleanup(query)
    if not text:
        return None
    quoted = _Quoted(text)
    body = quoted.text
    # A year phrase ("in 2015", "since 2018") narrows collaborators; read those first.
    if _years(body)[0] != body and (ranged := _parse_collaborators(body, quoted, genres)):
        return ranged
    for pattern, build in _RULES:
        match = pattern.fullmatch(body)
        if match and (found := build(match, quoted)):
            return found
    return _parse_collaborators(body, quoted, genres) or _parse_lookup(body, quoted)


def _parse_collaborators(
    body: str, quoted: _Quoted, genres: Collection[str]
) -> Interpretation | None:
    """Collaborator questions, which may carry a year range."""
    rest, start, end = _years(body)
    ranged: Interpretation | None = None
    for pattern, build in _COLLABORATOR_RULES:
        match = pattern.fullmatch(rest)
        if match and (ranged := build(match, quoted)):
            break
    if ranged is None and (start is not None or end is not None):
        # "who did Pharrell produce in 2013": a collaborator rule once the years are out.
        for pattern, build in _RULES:
            match = pattern.fullmatch(rest)
            found = build(match, quoted) if match else None
            if found is not None and found.intent is Intent.COLLABORATORS:
                ranged = found
                break
    if ranged is None:
        for rule in (_WHAT_RULE, _WHAT_OF_RULE):
            match = rule.fullmatch(rest)
            if match and (ranged := _what(match, quoted, genres)):
                break
    if ranged is None or (start is None and end is None):
        return ranged
    if ranged.intent is Intent.COLLABORATORS:
        return replace(ranged, start_year=start, end_year=end)
    # A year on anything else is part of a name ("Summer of 69").
    return None


def _parse_lookup(body: str, quoted: _Quoted) -> Interpretation | None:
    """A name to search for: "who is X", "find X", or a few plain words."""
    match = _LOOKUP_RULE.fullmatch(body)
    found = _name(match["t"] or match["t2"], quoted) if match else None
    if found:
        return Interpretation(Intent.LOOKUP, text=found)
    plain = _name(body, quoted)
    if plain and len(plain.split()) <= MAX_LOOKUP_WORDS and not _QUESTION_START.match(plain):
        return Interpretation(Intent.LOOKUP, text=plain)
    return None


def looks_like_question(query: str) -> bool:
    """Returns whether text reads as a question rather than a name (for the search box)."""
    text = _cleanup(query)
    return bool(_QUESTION_START.match(text)) or query.strip().endswith("?")
