# ADR 0008: Ask, AI in the search bar

- **Status:** Accepted, 2026-11-16.
- **Context:** People type questions into the search bar ("how is Kendrick Lamar connected to Daft Punk?", "who
  produced HUMBLE.?"), not just names. The sponsor asked for AI in the search bar on a free model. A language
  model asked about music will state credits that don't exist, and SongNexus's promise is that every claim is backed
  by a credit with a source (design principle 3). The 2026 redesign retired an earlier "Ask" because it was a keyword
  router presented as an assistant; anything called Ask now has to be honest about what it is.

- **Decision:**
  1. **The model interprets; our data answers.** A question becomes one of a closed set of intents with entity
     names as written: `FIND_PATH`, `COMPARE_ARTISTS`, `COMPARE_SONGS`, `SONG_CREDITS` (producer, featured,
     performer, all), `COLLABORATORS` (type, direction, years, genre), `CONNECTIONS`, `LOOKUP`, or `UNKNOWN`
     (`core/ask/intents.py`). Names are resolved against the catalog with the search index (a name that only
     distantly resembles something is "not in our data yet"; near-ties return alternatives for "Did you mean"). The
     answer is a message ID with values computed from the graph and credits (path length, mutual collaborators,
     credited producers, counts), with up to five supporting rows carrying evidence and sources, and a link to the
     app page that shows it in full. The model never writes a sentence the person sees.
  2. **Deterministic parser first** (`core/ask/parser.py`). Case- and punctuation-insensitive patterns cover the
     common phrasings: "X to Y", "between X and Y", arrows, "vs", "compare", possessives, quoted titles that
     contain "and" or "to", "by Artist", year phrases ("in 2015", "in the 90s", "since 2018") and genres from the
     served vocabulary. It runs on every question, costs nothing, and is the whole interpreter when no model is
     configured. A model is only asked when the parser finds no shape, or only a lookup for text that reads like a
     question.
  3. **Strict validation of model output** (`core/ask/llm.py`). Providers are asked for JSON constrained by one
     schema; the result is validated again (closed enums, strict types, year bounds, at most two names, no extra
     fields) and every name must appear in the question (allowing case and small typos), so a model can copy names
     but never add one. Anything off-schema is discarded and the parser's reading stands.
  4. **Providers**, one interface, chosen by `SONGNEXUS_LLM_PROVIDER`; request shapes checked against each
     provider's documentation on 2026-11-16:

     | Provider | Endpoint | Structured output | Default model |
     |---|---|---|---|
     | Google Gemini API (default; the sponsor's platform) | `v1beta/models/{model}:generateContent` | `generationConfig.responseFormat.text` with `APPLICATION_JSON` and a JSON Schema | `gemini-4-hydrogen` |
     | OpenRouter free models | `api/v1/chat/completions` | `response_format: json_schema, strict`, with `provider.require_parameters` and `data_collection: deny` | `openrouter/free` |
     | Ollama (local) | `api/chat` | `format` set to the JSON Schema | `llama3.2` |

     Without a key (Gemini, OpenRouter) or with `none`, there is no model. Temperature is 0.
  5. **Privacy.** Only the question text is sent, with our fixed instructions and schema: no user ID, session,
     history, address or cookies (tests assert the exact payload). Logs carry the intent, the outcome, whether the
     model was used, and latencies; never the question. Interpretations are cached under a SHA-256 of the
     normalized question (memory, and Redis when the response cache has it), never the text as a key. The answer
     panel says which model, if any, read the question.
  6. **Cost and limits.** The free tiers are the budget: Gemini's free tier (per-project limits shown in AI
     Studio) and OpenRouter's free models (20 requests a minute and 50 a day without purchased credits, 1,000 a day
     with at least 10). Most questions never reach a model (the parser reads them), identical questions hit the
     cache, and the endpoint is in the `ANALYZE` rate-limit class (120 a minute per client).
  7. **Failure modes all fall back to the parser:** no key, a timeout (`SONGNEXUS_LLM_TIMEOUT_S`, 4 s), an HTTP
     error or quota response, malformed JSON, off-schema output or ungrounded names. Failures are not cached. If
     the parser cannot read the question either, the answer says it is outside what our data covers and offers
     example questions. **Kill switch:** the `ask` flag turns the endpoint (503 `FLAG_OFF`) and the search-bar
     entry off.

- **Consequences:**
  - Answers are only as broad as the intents: "what's the best Kendrick album" is honestly not answered. New
    question types mean a new intent with its own answer from the data, not a better prompt.
  - Gemini's free tier may use prompts to improve Google's products. Questions are not personal data and are sent
    without any identity, but a production launch should use a paid tier (or Vertex AI), where prompts are not used
    for training. OpenRouter requests ask for providers that don't collect data; if no free provider qualifies, the
    request fails and the parser answers.
  - The parser is a list of patterns: it needs a test row for every phrasing it promises (the table in
    `tests/core/ask/test_parser.py`), and a pattern that mis-reads a name shows up as "not in our data yet", never as
    a wrong fact.
  - YouTube Music integration: the endpoint contract (question in, intent plus data-backed answer out) carries
    over; production would swap the provider for Google's internal model serving behind the same interface.
