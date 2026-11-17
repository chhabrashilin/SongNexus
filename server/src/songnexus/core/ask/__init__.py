"""Ask: questions typed into the search bar, interpreted into fixed intents (ADR 0008).

The model interprets, our data answers. A question becomes one ``Interpretation``
(an intent plus entity names), first by the deterministic ``parser`` and, when
that cannot tell, by an optional language model (``llm``). Names are then
resolved against the catalog (``resolve``) and the answer is composed from the
graph and credits (``answer``). No component ever states a fact that did not
come from the catalog.
"""
