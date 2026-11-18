"""The deterministic parser: common phrasings, no model (ADR 0008)."""

import pytest

from songnexus.core.ask.intents import CreditRole, Intent, Interpretation, SongRef
from songnexus.core.ask.parser import looks_like_question, parse
from songnexus.core.graph.collaborations import CollaborationType, ProductionDirection

FEATURE = CollaborationType.FEATURE
PRODUCTION = CollaborationType.PRODUCTION
BAND = CollaborationType.BAND
BY = ProductionDirection.PRODUCED_BY
FOR = ProductionDirection.PRODUCED_FOR
GENRES = frozenset({"jazz", "hip hop", "r and b"})


def path(a: str, b: str, *, strongest: bool = False) -> Interpretation:
    return Interpretation(Intent.FIND_PATH, artists=(a, b), strongest=strongest)


def compare(a: str, b: str) -> Interpretation:
    return Interpretation(Intent.COMPARE_ARTISTS, artists=(a, b))


def songs(a: SongRef, b: SongRef) -> Interpretation:
    return Interpretation(Intent.COMPARE_SONGS, songs=(a, b))


def credits(title: str, role: CreditRole, artist: str | None = None) -> Interpretation:
    return Interpretation(Intent.SONG_CREDITS, songs=(SongRef(title, artist),), credit_role=role)


def collaborators(
    artist: str,
    kind: CollaborationType | None = None,
    direction: ProductionDirection | None = None,
    *,
    start: int | None = None,
    end: int | None = None,
    genre: str | None = None,
) -> Interpretation:
    return Interpretation(
        Intent.COLLABORATORS,
        artists=(artist,),
        collaboration_type=kind,
        direction=direction,
        start_year=start,
        end_year=end,
        genre=genre,
    )


def web(artist: str) -> Interpretation:
    return Interpretation(Intent.CONNECTIONS, artists=(artist,))


def lookup(text: str) -> Interpretation:
    return Interpretation(Intent.LOOKUP, text=text)


CASES: list[tuple[str, Interpretation | None]] = [
    # Paths: "to", "and", "between", arrows, questions about working together.
    ("How is Kendrick Lamar connected to Daft Punk?", path("Kendrick Lamar", "Daft Punk")),
    ("how are kendrick lamar and daft punk connected", path("kendrick lamar", "daft punk")),
    ("HOW ARE SZA AND DRAKE LINKED?!", path("SZA", "DRAKE")),
    ("Kendrick Lamar -> Daft Punk", path("Kendrick Lamar", "Daft Punk")),
    ("Bjork → Radiohead", path("Bjork", "Radiohead")),
    ("path between SZA and Drake", path("SZA", "Drake")),
    ("what's the connection between Rihanna and Coldplay", path("Rihanna", "Coldplay")),
    ("six degrees from Bjork to Radiohead", path("Bjork", "Radiohead")),
    ("how many steps between Drake and The Beatles", path("Drake", "The Beatles")),
    ("did Pharrell ever work with Daft Punk?", path("Pharrell", "Daft Punk")),
    ("have Jay-Z and Kanye West worked together", path("Jay-Z", "Kanye West")),
    ("is Drake connected to Rihanna", path("Drake", "Rihanna")),
    ("connect Kendrick to SZA", path("Kendrick", "SZA")),
    ("from Beyoncé to Bad Bunny", path("Beyoncé", "Bad Bunny")),
    (
        "strongest path from Kendrick Lamar to Daft Punk",
        path("Kendrick Lamar", "Daft Punk", strongest=True),
    ),
    ("hey, how is Thundercat related to Flying Lotus", path("Thundercat", "Flying Lotus")),
    (
        'how is "Earth, Wind & Fire" connected to "Simon & Garfunkel"',
        path("Earth, Wind & Fire", "Simon & Garfunkel"),
    ),
    # Comparisons: "vs", "and", "with", possessive-free, quoted songs.
    ("Kendrick Lamar vs Drake", compare("Kendrick Lamar", "Drake")),
    ("kendrick lamar VS. drake", compare("kendrick lamar", "drake")),
    ("compare Beyoncé and Rihanna", compare("Beyoncé", "Rihanna")),
    ("compare SZA with Frank Ocean", compare("SZA", "Frank Ocean")),
    ("Florence + the Machine vs Lorde", compare("Florence + the Machine", "Lorde")),
    ("what do SZA and Frank Ocean have in common", compare("SZA", "Frank Ocean")),
    ("difference between Blur and Oasis", compare("Blur", "Oasis")),
    ("how does Drake compare to J. Cole", compare("Drake", "J. Cole")),
    ("is Lorde similar to Lana Del Rey", compare("Lorde", "Lana Del Rey")),
    (
        "compare songs HUMBLE. and DNA.",
        songs(SongRef("HUMBLE"), SongRef("DNA")),
    ),
    ('"HUMBLE." vs "DNA."', songs(SongRef("HUMBLE."), SongRef("DNA."))),
    (
        "compare HUMBLE. by Kendrick Lamar and Alright by Kendrick Lamar",
        songs(SongRef("HUMBLE", "Kendrick Lamar"), SongRef("Alright", "Kendrick Lamar")),
    ),
    # Song credits.
    ("who produced HUMBLE.?", credits("HUMBLE", CreditRole.PRODUCER)),
    (
        'who produced "HUMBLE." by Kendrick Lamar',
        credits("HUMBLE.", CreditRole.PRODUCER, "Kendrick Lamar"),
    ),
    ("Who's the producer of Bad Guy", credits("Bad Guy", CreditRole.PRODUCER)),
    ("producers on Money Trees", credits("Money Trees", CreditRole.PRODUCER)),
    ("who is featured on Pray For Me", credits("Pray For Me", CreditRole.FEATURED)),
    ("who features on Money Trees", credits("Money Trees", CreditRole.FEATURED)),
    ("features on Money Trees", credits("Money Trees", CreditRole.FEATURED)),
    ("credits for Bad Guy", credits("Bad Guy", CreditRole.ALL)),
    ("who worked on Thriller", credits("Thriller", CreditRole.ALL)),
    ("who sang Bohemian Rhapsody", credits("Bohemian Rhapsody", CreditRole.PERFORMER)),
    ("who produced the song Alright", credits("Alright", CreditRole.PRODUCER)),
    # Collaborators: possessives, types, directions, years, genres.
    ("Who produced for Kendrick Lamar", collaborators("Kendrick Lamar", PRODUCTION, BY)),
    ("who has Metro Boomin produced for", collaborators("Metro Boomin", PRODUCTION, FOR)),
    ("Kendrick Lamar's producers", collaborators("Kendrick Lamar", PRODUCTION, BY)),
    (
        "Kendrick Lamar’s producers since 2018",
        collaborators("Kendrick Lamar", PRODUCTION, BY, start=2018),
    ),
    ("kendrick lamar collaborators", collaborators("kendrick lamar")),
    ("Kendrick's features in 2015", collaborators("Kendrick", FEATURE, start=2015, end=2015)),
    (
        "who did Kendrick Lamar work with in 2015",
        collaborators("Kendrick Lamar", start=2015, end=2015),
    ),
    (
        "who has Thundercat worked with from 2010 to 2015",
        collaborators("Thundercat", start=2010, end=2015),
    ),
    (
        "Mike WiLL Made-It's collaborators in the 2010s",
        collaborators("Mike WiLL Made-It", start=2010, end=2019),
    ),
    ("Prince collaborators in the 80s", collaborators("Prince", start=1980, end=1989)),
    ("Kendrick Lamar's jazz collaborators", collaborators("Kendrick Lamar", genre="jazz")),
    ("kendrick lamar hip hop collaborators", collaborators("kendrick lamar", genre="hip hop")),
    ("who did Kendrick Lamar work with in jazz", collaborators("Kendrick Lamar", genre="jazz")),
    ("who featured on Kendrick Lamar's songs", collaborators("Kendrick Lamar", FEATURE)),
    ("who has Kendrick Lamar featured", collaborators("Kendrick Lamar", FEATURE)),
    ("what bands was Thom Yorke in", collaborators("Thom Yorke", BAND)),
    (
        "who did Pharrell produce for in 2013",
        collaborators("Pharrell", PRODUCTION, FOR, start=2013, end=2013),
    ),
    (
        "who produced for Kendrick Lamar since 2016",
        collaborators("Kendrick Lamar", PRODUCTION, BY, start=2016),
    ),
    ("collaborators of Pharrell Williams", collaborators("Pharrell Williams")),
    ("Travis Scott's most frequent collaborators", collaborators("Travis Scott")),
    # Connection web.
    ("artists like Bjork", web("Bjork")),
    ("who is similar to Frank Ocean", web("Frank Ocean")),
    ("Kendrick Lamar's network", web("Kendrick Lamar")),
    ("explore Daft Punk", web("Daft Punk")),
    ("what should I listen to if I like Radiohead", web("Radiohead")),
    ("musicians connected to Questlove", web("Questlove")),
    # Lookups and nothing.
    ("who is Kendrick Lamar", lookup("Kendrick Lamar")),
    ("Kendrick Lamar", lookup("Kendrick Lamar")),
    ("humble", lookup("humble")),
    ("方大同", lookup("方大同")),
    ("find Bad Bunny", lookup("Bad Bunny")),
    # Question-shaped lookups go to the model when there is one (see test_interpreter).
    ("what's the meaning of life", lookup("the meaning of life")),
    ("which album won the most grammys in the history of the awards", None),
    ("", None),
    ("   ?  ", None),
]


@pytest.mark.parametrize(("query", "expected"), CASES, ids=[q or "<empty>" for q, _ in CASES])
def test_parser_reads_common_phrasings(query: str, expected: Interpretation | None) -> None:
    assert parse(query, GENRES) == expected


def test_the_table_is_large_enough() -> None:
    assert len(CASES) >= 40


@pytest.mark.parametrize(
    "query",
    [
        "who did Kendrick Lamar work with",
        "how is X connected to Y",
        "Kendrick Lamar?",
        "compare A and B",
    ],
)
def test_questions_are_recognized(query: str) -> None:
    assert looks_like_question(query)


@pytest.mark.parametrize("query", ["Kendrick Lamar", "humble", "Daft Punk"])
def test_names_are_not_questions(query: str) -> None:
    assert not looks_like_question(query)


def test_pronouns_are_not_names() -> None:
    # "who" must never become an artist to look up.
    assert parse("how is it connected to them") is None
