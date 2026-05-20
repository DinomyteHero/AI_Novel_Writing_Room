# Archive

> **These are historical artifacts.** The documents below were written as
> build instructions for each development phase and reflect what was
> *planned* at the time, not the current state of the code. Field names,
> file paths, test counts, and feature descriptions may be outdated.
> For current documentation, see the parent [docs/](../) directory.

This directory contains historical implementation briefs used during the development of the AI Writers' Room. These documents were written as instructions for Claude Code to follow during each build phase and are preserved here for reference.

They describe what was **planned** to be built at each phase, not necessarily the final state of the code. For current documentation, see the parent `docs/` directory.

## Contents

| File | Original Name | Description |
|------|--------------|-------------|
| `design-document-v1.1.md` | `AI_Writers_Room_Design_Document_v1.1.md` | Original technical design specification (v1.1). Contains architecture diagrams, JSON schemas, and the phased roadmap. Some sections (e.g., directory structure) are aspirational and may not match the current codebase. |
| `phase-1-brief.md` | `Claude_Code_Project_Brief_v1.1.md` | Phase 1 implementation brief: MVP pipeline (4 agents, orchestrator, CLI). |
| `phase-2-brief.md` | `Phase_2_Prompt.md` | Phase 2 implementation brief: Memory, Canon, and Story Physics. |
| `phase-3-brief.md` | `Phase_3_Prompt.md` | Phase 3 implementation brief: Quality Metrics, Character Specialist, Revision Pipeline. |
| `phase-4-brief.md` | `Phase_4_Project_Brief.md` | Phase 4 implementation brief: Export, Physics Integration, Adaptive Revision, Scene Cards. |
| `Phase_5_Changelog.md` | `Phase_5_Changelog.md` | Phase 5 changelog and migration guide: Series support, workshop expansion, character arcs, hook governance, voice definition, style fingerprinting, manuscript review. |
| `phase-3-gap-report.md` | `docs/development/phase-3-gap-report.md` | 2026-04-16 point-in-time drift report after Phase 3 closed. All P0 items have since been resolved; retained for historical context. |
| `model-routing-evaluation-2026-04-17.md` | `docs/reference/model-routing-evaluation-2026-04-17.md` | Historical model-routing and cost evaluation from the pre-lean pipeline. |
| `model-selection-and-cost-review-2026-04-17.md` | `docs/architecture/model-selection-and-cost-review.md` | Historical model-selection and cost review; current production routing is documented in user-guide and architecture docs. |
| `forward-relay-v4-proposal-2026-04-21.md` | `docs/architecture/forward_relay_v4_proposal.md` | Historical relay proposal superseded by the current lean production and manuscript-level review workflow. |
| `ruusan-revision-assessment-2026-04-19.md` | `docs/editorial/ruusan-revision-assessment-2026-04-19.md` | 2026-04-19 manuscript-level revision assessment for The Ruusan Atonement, written before the lean shipping default and final-copy pipeline landed. References scene files in `_archive/` paths that have since been pruned in the public-release cleanup. |
| `pipeline-redesign.md` | `docs/architecture/pipeline-redesign.md` | Historical design brief for the forward-only relay (gates, save-blockers, compression guard, Final Gate). Superseded by the 2026-05-19 lean teardown, which removed that machinery; the per-scene pipeline is now a single lean forward pass. |
| `architecture_upgrade_spec.md` | `docs/architecture/architecture_upgrade_spec.md` | Slice-by-slice implementation playbook (Slices 1–6). Slices 1/4/5 (state firewall, continuity event log, sociogram) were removed; Slices 2/3/6 (chapter packet, promise ledger, manuscript lifecycle) shipped and are documented in `CLAUDE.md`. Superseded by the 2026-05-19 lean teardown. |
