# ADR-003: One LLM orchestrator over deterministic tools, with a deterministic planner

**Status:** accepted (2026-09-30)

## Context

The brief invites an "agentic" layer. The failure mode to avoid is a chatbot that states plausible but false
music facts, or a multi-agent system whose complexity is not earned.

## Decision

- A **single** Claude tool-use loop orchestrates **allow-listed, read-only, validated** tools that wrap the same
  services the UI uses. There are no planner/worker/critic agents: the task is one loop, and verification is done by
  deterministic code (path re-verification, mention check), which is more reliable than a second model's opinion.
- Structured response fields come from an **evidence ledger** filled by tools, never from model text.
- A **deterministic planner** (intent patterns → fixed tool plans → template answers) is the free, reproducible
  baseline, the fallback on any LLM failure, and the mode evaluated in CI.
- Manual loop rather than the SDK's beta tool runner: it needs per-call validation, a step budget with a forced
  final answer, and full tracing.

## Consequences

- The system works fully without an API key; LLM mode is an upgrade in coverage (e.g. comparative questions), not
  a dependency.
- Each LLM answer is auditable (trace of every tool call) and checked (grounding result in the response).
- Adding a capability means adding a tool and an evaluation case, not a new agent.
- Revisit multi-agent designs only if evaluation shows a failure class that a separate agent measurably fixes.
