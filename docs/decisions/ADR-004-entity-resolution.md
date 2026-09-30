# ADR-004: Entity resolution never merges silently

**Status:** accepted (2026-09-30)

## Context

Names are not identifiers. The first fetch made this concrete: of 28 seed names, 10 matched more than one
MusicBrainz artist (e.g. "Drake": the Canadian rapper and a Chilean metal band), and "Kanye West" is now listed
as "Ye". Recordings of the same song also appear several times (remasters, explicit versions), which would inflate
collaboration counts.

## Decision

1. **Source IDs first:** an exact source identifier (MBID) links with confidence 1.0.
2. **Name matching is a three-way decision** (*matched / ambiguous / no match*) from a documented score
   (edit distance + trigram similarity over normalized names and aliases, with a small prior), with thresholds
   biased to precision and a required margin over the runner-up. Identical names need a double margin.
3. **Ambiguity stops the line.** Seeds fail with a candidate list until a human pins an ID, and a pinned ID requires
   a `pin_reason`. At query time the agent reports ambiguity instead of choosing.
4. **Every mapping is recorded** in `entity_source_mappings` with method, confidence and decision
   (`created`, `merged`, later `review`).
5. **Recording deduplication** uses a conservative blocking key (base title + primary artists) that keeps remixes
   and live versions separate; merges get confidence 0.9.

## Consequences

- Some manual work (10 pins for 28 seeds), in exchange for no wrong merges in the graph.
- Cross-source ER (Phase 1) plugs into the same matcher and adds a review queue. Before any automatic cross-source merging,
  precision/recall must be measured on a labeled pair set.
- Thresholds are in one `MatchPolicy` object, so tuning them is a reviewed, evaluated change.
