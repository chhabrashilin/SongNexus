# Software bills of materials and license audit (M8-07)

Generated 2026-10-13 in CycloneDX 1.5:

| File | Scope | Components |
|---|---|---|
| `server.cdx.json` | the server's Python environment (`uvx --from cyclonedx-bom cyclonedx-py environment server/.venv`), which includes dev tools | 86 |
| `web.cdx.json` | the web app's production dependency tree (`npm sbom --omit dev --package-lock-only`) | 101 |

Regenerate at each release. The container image's SBOM from the build is the authoritative record of what ships.

## License summary

- **Web (shipped):** Apache-2.0 (53), MIT (21), ISC (14), BSD-3-Clause (12), 0BSD (1). All permissive; none unknown.
- **Server:** MIT, Apache-2.0, BSD-2/3-Clause, PSF-2.0 and MIT-0 dominate.
- **Flagged and reviewed:**
  - `psycopg` and `psycopg-binary` (LGPL-3.0): shipped, used unmodified as a separate library installed through pip, so
    users can replace it and the product's own license is unaffected. Legal to confirm (plan §24).
  - `certifi` (MPL-2.0, shipped): file-level copyleft; unmodified, so the only duty is to keep the notice.
  - `hypothesis` and `pathspec` (MPL-2.0), `@axe-core/playwright`: development only, not shipped.
  - `protobuf`: the SBOM has no license field; upstream is BSD-3-Clause.
- **Data:** MusicBrainz core data is CC0. Genre tags are CC BY-NC-SA 3.0, kept as a separate source and credited on the
  About page; their non-commercial term must be re-checked before any commercial use (ADR 0003).

Nothing copyleft is linked into the shipped web bundle. Policy (plan §24): permissive for anything shipped; every
flagged item above has a recorded reason.
