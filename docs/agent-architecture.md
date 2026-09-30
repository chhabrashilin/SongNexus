# Part 5: Agent architecture

**Rule: LLM-generated text ≠ knowledge-graph fact.** The model chooses tools and writes the prose. Everything
structured in a response (entities, the path, evidence) is copied from tool outputs, never parsed from model text.

## Shape: one orchestrator, deterministic tools

```
question ─▶ AgentService ──mode?──▶ LlmOrchestrator (Claude, tool use, ≤ 8 steps)  ─┐
                               └──▶ DeterministicPlanner (intent patterns → plans) ─┤
                                                                                     ▼
                                     run_tool(): allow-list → Pydantic validation → service call → trace
                                                                                     ▼
                                     EvidenceLedger: entities, known names/IDs, path (+kinds), evidence, limitations
                                                                                     ▼
                                     Grounding: path re-verified against graph; answer scanned for unsupported artists
                                                                                     ▼
                                     AgentResponse {answer, path, entities, evidence, tools_used, limitations, grounding}
```

Why not several agents? The task is one loop: resolve names, call a graph operation, explain the result. A
planner/worker/verifier split would add latency, cost and evaluation surface without a capability the single
loop lacks. Verification is deterministic code, which is stronger than a second model's opinion. Revisit only if
evaluation shows a failure mode that a separate agent demonstrably fixes ([ADR-003](decisions/ADR-003-agent-orchestration.md)).

## Tools (allow-list)

| Tool | Arguments (validated) | Backed by |
|---|---|---|
| `search_entities` | `query` (1–120 chars), `entity_type`, `limit ≤ 10` | search index + ER matcher → *matched / ambiguous / no_match* |
| `get_artist` | `artist_id` (UUID) | catalog service |
| `get_neighbors` | `artist_id`, `categories?`, `limit ≤ 25` | neighborhood + top evidence per neighbor |
| `find_path` | `source_id`, `target_id`, `mode`, `max_depth ≤ 8`, `alternatives ≤ 3`, `categories?` | bidirectional BFS / Dijkstra / Yen |
| `get_connection_evidence` | `artist_a`, `artist_b`, `limit ≤ 20` | edge evidence |
| `rank_artists` | `metric` (pagerank, betweenness, degree), `scope`, `limit ≤ 20` | centrality |
| `get_provenance` | `artist_a`, `artist_b`, `limit ≤ 20` | fact → raw record → run |

Tool schemas are generated from the Pydantic models (`extra="forbid"`: unknown fields are rejected). Invalid
arguments, unknown tools (e.g. a hallucinated `run_sql`) and domain errors return `is_error` results the model can
correct; all are traced. There is no tool that writes, runs SQL, touches the filesystem or reaches the network.

## The loop (`agent/llm.py`)

- Manual loop instead of the SDK's beta tool runner. It needs per-call validation, a hard step budget, tracing, and a
  forced final answer (`tool_choice: none`) when the budget is spent.
- The full assistant content (including thinking blocks) is appended unchanged: an append-only history.
- Parallel tool calls are executed and returned in a single user message.
- Stop reasons: `refusal` and `max_tokens` raise `LlmUnavailableError`. So do API/connection errors (typed SDK
  exceptions) and empty answers. The service then answers with the deterministic planner and says so in
  `limitations`.

### Model configuration

`claude-opus-5-5`, effort `medium` (configurable via `SONGNEXUS_AGENT_MODEL` / `SONGNEXUS_AGENT_EFFORT`),
`max_tokens` 16k, prompt caching on the stable system prompt + tools, and server-side refusal fallback
(`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`). Without `ANTHROPIC_API_KEY` the service runs
deterministic-only and `/health` reports `llm_available: false`.

## Deterministic planner (`agent/planner.py`)

Ordered regex intents: connection, collaborators, producers, genre-bridges, bridges, central, about. Each has a fixed tool
plan and a template answer built from tool output. It is free, reproducible and instant, and it serves as:
the baseline the LLM mode must beat; the fallback when the LLM is unavailable; and the CI-evaluated mode.
Unsupported questions get the list of supported question types plus a limitation. Genre-specific bridge
questions ("artists who connect jazz and hip-hop") fall back to overall bridges with an explicit limitation,
because genre-filtered discovery is Phase 3.

## Grounding and evidence

1. **Structural:** `path`, `entities`, `evidence` come from the ledger.
2. **Path verification:** every hop is re-checked against the graph (edge exists with non-zero strength in the
   kinds used, no repeated nodes). On failure the path is withheld and a limitation is added.
3. **Mention check (heuristic):** capitalized spans of the answer that exactly name an artist in the graph must
   be an entity some tool returned (by ID, so alias quirks such as a MusicBrainz alias "Kendrick Lamar, SZA" do
   not trigger false alarms), or a name the user typed. Quoted titles, arrows and colons are boundaries. After a
   clean match, the *other* search candidates do not count as returned (a test caught this laxity).
   Unsupported mentions are listed in `grounding.unsupported_mentions` and in `limitations`.
   Limitation: it cannot catch claims about artists absent from the graph, or wrong claims about present ones
   (see evaluation).
4. **Missing data:** "no path" answers say *not connected in the loaded data*, never *not connected*.

## Safety

- Prompt injection: tool output is externally sourced text (artist names, titles). It is sanitized (control
  characters stripped, length-bounded), the system prompt states that tool output is data, and, most importantly,
  the tools are read-only, so a successful injection could only affect prose, which is then grounding-checked.
- Rate limiting: per-client token bucket on `/agent/query` (default 20/min).
- Input bounds: question ≤ 500 chars; step budget 8; tool result ≤ 12k chars.

## Observability

Every response carries `trace_id`, `tools_used` (step, tool, arguments, ok, summary, latency) and
`elapsed_ms`. Logs record mode, intent, tool outcomes and grounding. Metrics: per-tool latency and error counts,
queries per mode, LLM fallbacks, unsupported-mention count.

## Evaluation strategy

`evaluation/agent_cases.json` (20 cases: graph reasoning, direct facts, discovery, comparative, missing data) is
scored by `songnexus eval-agent --mode deterministic|llm` on tool-selection accuracy, task success, grounded rate,
unsupported-claim rate, limitation admission and latency. Deterministic results (recorded): task success 0.90, grounded
1.00, unsupported claims 0.00, limitation admission 1.00. The two failures are the *comparative* cases, a known
planner gap that LLM mode is expected to close. **LLM-mode results: TBD.** A run costs API credits and needs the
team's go-ahead. See [evaluation.md](evaluation.md).
