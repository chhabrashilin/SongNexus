# Engineering standards

The bar every change must meet before it merges. It is modeled on Google's public engineering practices
(code review guide, style guides, API Improvement Proposals). If a change can't meet a rule, the change
description says why.

## 1. Changes and review

- **Small changes.** Aim for under ~300 changed lines, one logical change each. Split refactors from behavior changes.
- **Every change is reviewed** by at least one other team member before merge. The reviewer checks design,
  correctness, tests, naming, comments and readability, in that order (Google's code review guide).
- **Change description:** what and why in the first line (imperative, ≤ 72 chars); a body explaining the
  motivation, alternatives and testing done; and a link to the milestone (design doc §12).
- **No direct pushes to `main`.** Changes merge only with CI passing.

## 2. Style

| Language | Style guide | Enforced by |
|---|---|---|
| Python | [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) | `ruff` (lint + format, Google docstring convention), `mypy --strict` |
| TypeScript | [Google TypeScript Style Guide](https://google.github.io/styleguide/tsguide.html) | `gts` (Google's TypeScript lint/format config), `tsc --strict` |
| SQL / config | Consistent with surrounding code | review |

Readability rules that tools don't catch:
- Names say what a thing is, not how it's implemented. Avoid abbreviations except well-known ones (`id`, `url`).
- Comments explain *why*. Every public function, class and module gets a docstring.
- No dead code, no commented-out code, no TODOs without an owner and an issue link.
- Hard-coded numbers become named constants, with a comment when the value is a tuned choice.

## 3. Testing

- Every behavior change ships with tests in the same change.
- Tests are **hermetic** (no network, no wall-clock dependence, no shared state) and **deterministic**. A flaky
  test is treated as a bug and quarantined within a day.
- Test pyramid: many fast unit and property tests, fewer integration tests, a handful of end-to-end tests per CUJ.
- Algorithms are tested against a reference implementation on generated inputs (property tests).
- Golden datasets (`data/`) carry regression floors for user-visible quality (search, matching).

## 4. APIs

- Follow the [API Improvement Proposals](https://google.aip.dev): resource-oriented names, standard methods,
  custom methods with `:verb`, pagination with `page_size`/`page_token`, and a single error model with canonical
  codes (`INVALID_ARGUMENT`, `NOT_FOUND`, `RESOURCE_EXHAUSTED`, …).
- Every request has explicit bounds (page sizes, search depth, payload size). No unbounded work.
- Breaking changes only in a new major version.

## 5. Data, privacy and security

- Every stored fact carries provenance (source, source record, pipeline version, confidence).
- **Users' listening history is personal data.** Raw files are processed on the device; the server receives
  aggregates only, keeps them in memory per request and never logs request bodies.
- No secrets in the repository. Configuration comes from the environment, and `.env` is git-ignored.
- Dependencies: minimal, pinned and license-checked (permissive licenses only), and audited in CI.

## 6. Product quality

- **Accessibility:** WCAG 2.2 AA. Keyboard and screen-reader paths exist for every interaction, and every graph
  has a list equivalent.
- **Internationalization:** no user-visible strings in logic code; RTL-safe layouts; names matched across scripts.
- **Performance budgets:** p95 server latency per endpoint (design doc §10) and a JavaScript bundle budget for the client.
- **Honest UX:** absence of data is reported as absence ("not connected in this dataset"), never as a fact.

## 7. Definition of done (per change)

- [ ] Design doc updated if behavior or architecture changed
- [ ] Tests added or updated; CI green (format, lint, types, tests, build, audit)
- [ ] Public APIs documented; errors use the shared model
- [ ] No new personal data collected, or the privacy section is updated and reviewed
- [ ] Accessibility checked for UI changes (keyboard, screen reader, contrast)
- [ ] Reviewed and approved by a teammate
