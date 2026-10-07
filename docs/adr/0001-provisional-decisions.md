# ADR 0001: Provisional decisions D1–D18

- **Status:** Accepted *provisionally*, 2026-10-07. The team adopted the plan's recommendations so building could
  start. Any decision can be reopened at the design review; a reversal gets its own ADR.
- **Context:** `plan.md` §6 lists 18 decisions that block work. None had been answered when building began.

| ID | Decision | Adopted | Revisit trigger |
|---|---|---|---|
| D1 | YouTube Music integration path | Handoff package; MusicBrainz as stand-in catalog | Sponsor offers data/API access |
| D2 | R1 scope | Committed / target / stretch tiers per plan §26 | Weekly burn-down behind by > 3 pd |
| D3 | LLM in v1 | None | After R1 |
| D4 | License | Apache-2.0 (`server/pyproject.toml`); publication pending sponsor | Sponsor answer |
| D5 | Languages | Python 3.12 server, TypeScript web | – |
| D6 | Storage | PostgreSQL; SQLite for fast unit tests only | – |
| D7 | JSON naming | lowerCamelCase | – |
| D8 | UI foundation | Own React components on Material 3 tokens | – |
| D9 | Hosting | Cloud Run + Cloud SQL + Firebase Hosting; configs in repo, nothing deployed until a GCP project exists | GCP project available |
| D10 | Python tooling | uv + lockfile | – |
| D11 | Workflow | PRs into `v2`, CODEOWNERS, 1 approval | – |
| D12 | Identity | Firebase Authentication (Google Sign-In); sessions per ADR 0002 | – |
| D13 | Social scope | R2; structured shares | R2 planning |
| D14 | Platform connection | R1 file imports only | Legal review of Spotify terms |
| D15 | Audio descriptors | R2; AcousticBrainz | R2 planning |
| D16 | Catalog completeness | R1 expanded snapshot | – |
| D17 | Campus trends | R2; opt-in, DP, cohort ≥ 25 | Privacy review |
| D18 | Capacity | Assumed 4 people × 2 days/week; buffer 8% | Team confirms real numbers |

- **Consequences:** work proceeds on recommendations; reversals cost rework proportional to how far the build has
  progressed, so the design review should happen as early as possible.
