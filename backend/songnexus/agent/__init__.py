"""Grounded discovery agent.

The graph computes. The agent orchestrates. The model explains. The evidence decides.

* ``tools``     - the allow-list: typed, validated, read-only graph operations.
* ``ledger``    - structured intermediate state: every entity, path and piece of
                  evidence the tools returned during one request.
* ``planner``   - deterministic intent parsing and tool plans (no LLM needed).
* ``llm``       - Claude as planner/explainer over the same tools.
* ``grounding`` - checks the final answer against the ledger.
* ``service``   - chooses a mode, runs it, assembles the response.
"""
