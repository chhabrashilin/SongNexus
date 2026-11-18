"""Z-star: the For You recommender (ADR 0010, docs/design/for-you.md).

A multi-stage recommender in the shape large feeds use, sized for this catalog:

1. **Signals** (``signals``): everything the listener told us or did, explicit
   (follows, Top 5, "more like this", "not interested", blocks, genre choices,
   imported or linked listening) and implicit (opens, listens, dwell, skips on
   the feed), turned into weighted *seed* artists and a genre profile, with
   recency decay.
2. **Retrieval** (``retrieval``): several independent candidate sources, each
   with provenance: random walks with restart over the collaboration and
   co-listening graph (Pixie-style), co-listening neighbors, nearest neighbors
   in an artist embedding space (``embed``), genre affinity, friends, and
   exploration.
3. **Ranking** (``features``, ``ranker``): per-candidate features, scored by a
   multi-head logistic model that predicts open, listen and negative feedback,
   combined into one value. Weights are learned from logged impressions
   (``songnexus zstar-train``); a documented prior serves until there is data.
4. **Re-ranking** (``rerank``): maximal marginal relevance against the items
   already placed, a genre cap per window, and reserved exploration slots.
5. **Experiments** (``experiments``): deterministic bucketing of listeners into
   arms that change the configuration or the model.

Everything here is pure and deterministic for a given input and seed: no
database, no clock, no network. ``evaluate`` measures it offline.
"""
