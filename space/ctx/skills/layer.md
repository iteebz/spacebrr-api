---
description: Refine raw context into linked artifacts
---

# Layer

Process raw context into higher-quality artifacts. Every artifact has provenance — linked to what produced it.

## The refinement chain

```
stream (raw thought) → insight (compressed observation)
insights (pattern) → decision (commitment)
decision (scope) → spec (buildable contract)
spec (contract) → task (claimable work)
```

## Operations

1. **Read** — Find unprocessed material: stream entries, unlinked insights, decisions without specs
2. **Connect** — What relates to what? Link insights to decisions. Link decisions to specs. Surface patterns across scattered observations.
3. **Compress** — 3 scattered thoughts that say the same thing → 1 dense insight. Kill redundancy.
4. **Elevate** — Recurring insight → propose decision. Decision with clear scope → write spec. Spec with no blockers → create task.
5. **Link** — Every artifact references its source. `i/abc` cites `d/xyz`. Spec references insights. Provenance is non-negotiable.

## Provenance rules

- Insights reference what triggered them (stream entry, code observation, other insight)
- Decisions reference the insights that motivated them
- Specs reference the decisions they implement
- Tasks reference the specs they build
- If you can't point to a source, the artifact is groundless

## ARCH.md alignment

When elevation changes the system's shape — new modules, new layers, new commands, new specs — ARCH.md must reflect it. The map drifts every time structure changes and nobody updates it.

- New spec → add to ARCH.md specs table
- New module/layer → update Codebase Layers section
- New command → update Command Surface section
- Killed spec or module → remove from ARCH.md (dead entries are lies)

## Anti-patterns

- Creating artifacts without linking to source material
- Compressing too early (wait for the pattern to repeat)
- Elevating without evidence (one insight ≠ decision-worthy)
- Layering as busywork (if the raw material is fine as-is, leave it alone)
- Elevating structure without updating the map (ARCH.md drift is silent decay)
