# The connection web, v5: product plan

| | |
|---|---|
| **Status** | In build |
| **Audience** | College students (18–24), the launch niche in [product-strategy.md](product-strategy.md) |
| **Replaces** | The R2 starburst web (`/explore/:id`) |

## 1. What was wrong

We looked at the R2 web the way a first-time student would, on a phone, with Kendrick Lamar open.

1. **It was a starburst, not a map.** Every line ran to the center. There was no shape, so there was nothing to read.
2. **It ranked the wrong people.** Strength was credit count, so producers most listeners have never heard of
   outranked SZA, Drake and Taylor Swift. Someone who opens Kendrick wants Kendrick's *world*, not a credits ledger.
3. **A line said nothing.** "Kendrick and SZA: *All the Stars*" is the whole reason anyone cares. In R2 the
   song was three taps away.
4. **It was a dead end.** You couldn't play anything, and you couldn't share what you found.
5. **Faces were mostly letters.** Generated monograms were the same size as real photos, so the web looked
   unfinished.

## 2. What students want from it (our hypotheses)

Drawn from the strategy's segments (credits-curious students, social listeners) and how this age group uses
music apps. These are hypotheses to test in the campus pilot, not findings.

| They want to… | So the web must… |
|---|---|
| Recognize people instantly | Lead with faces they know: size and order by how widely known an artist is, not only by credit count |
| Get the "oh, *that's* how they know each other" moment | Put the song on the line: the top shared song is visible on hover, tap and in the panel |
| Listen right away | Every song has "Play on YouTube Music" one tap away |
| Understand an artist's world at a glance | Group people into orbits by role: who they rap/sing with, who makes their beats, everyone else in the credits |
| Go down the rabbit hole | One tap to open someone's web around them; a trail to get back |
| Show friends | A shareable story-format image of the web, made on the device |
| Not read instructions | Learn by doing: one short first-visit hint, legends as tappable filter chips |

## 3. The design

**Orbits.** The starting artist sits in the middle, large, haloed in their color. Direct connections sit on
three rings, each labeled faintly on the ring itself:

- **Features** (inner): artists they performed with.
- **Production** (middle): producers they worked with, in either direction.
- **Credits** (outer): writers, engineers, bands and everything else.

Within a ring, the most relevant people are spaced first, so the eye lands on them. When you open another
artist, their connections bloom around *them* with the usual force layout; the first artist's orbits stay put.

**Relevance, not raw strength.** The server ranks connections by a blend of connection strength (credits) and
public reach (ListenBrainz listener counts, aggregate and public). An artist with no listener data still ranks
by credits. Node size follows reach, so Taylor Swift reads bigger than an engineer with one credit; the line
width still shows how much they made together.

**Faces first.** Photos (Wikimedia Commons, ADR 0009) fill the nodes. Artists without a photo are drawn
smaller and quieter, so the web looks like people, not a letter grid.

**Songs on the lines.** Each connection carries its best shared songs (features before production credits,
original versions before remixes). Hovering or tapping a line names the song; the panel lists the songs
with "Play on YouTube Music".

**Alive, not busy.** Lines are soft curves. Pointing at someone lights their neighborhood and sends a slow
pulse along those lines; everything else dims. Nothing moves on its own when reduced motion is on.

**Filters as chips** on the canvas: All · Features · Production · Credits. The legend *is* the filter.

**The panel** (a bottom sheet on phones): photo, name, reach, the songs together with play links, and three
actions: *Explore their web*, *Find a path*, *Artist page*.

**Share.** "Share image" renders the current web into a 1080×1920 story card on the device (title, the web,
the SongNexus mark) and opens the system share sheet, or downloads it where sharing files isn't supported.

## 4. Success metrics (pilot)

| Metric | Target |
|---|---|
| Sessions on the web that tap a node or line | ≥ 70% |
| Webs where a second artist is opened | ≥ 35% |
| "Play on YouTube Music" taps per web session | ≥ 0.3 |
| Shares per 100 web sessions | ≥ 3 |
| Time to first meaningful tap (median) | < 6 s |

## 5. Guardrails

- Every line is still backed by credits with sources; the panel shows them.
- Listener counts are public aggregate ListenBrainz data, never anyone's personal listening.
- The list view remains the accessible equivalent of the canvas, with the same content and order.
- 60 fps target on a mid-range phone with ~150 artists; cached sprites, no per-frame allocation.
