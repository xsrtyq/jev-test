# Jev context/control research — Freeze decision 2026-09-22

## Decision

**FREEZE the standalone Jev context-management research branch. Do not integrate it into the main coding workflow now.**

Retain:
- immutable archive/provenance and pair/dependency closure design;
- fixed benchmark harnesses and result artifacts;
- backend-neutral semantic-router interface;
- the simplest 64-block short-question evidence selector as a research/reference implementation;
- Jev as an optional future backend, not an architectural dependency.

Do not continue now:
- calibration/test/256 expansion;
- relation-anchor full dev run;
- more prompt tuning to make the current synthetic benchmarks look better;
- automatic Jev compaction/deletion;
- production Codex context interception;
- direct/signals prior experiments.

## Why

Positive findings:
1. 64-block authored semantic retrieval showed strong signal.
2. The cheap short-no-anchor hybrid achieved 18/18 final evidence completeness on stable dev fixtures when combined with deterministic provenance/pair closure.
3. In two tiny unpaired continuation tasks, jev_window retained enough ordinary project-history evidence for 2/2 hidden behavioral tests.
4. Jev request cost/latency itself is small enough to be technically usable.

Negative/insufficient findings:
1. evidence-first smoke cut downstream input heavily but increased full-path cost.
2. unconditional Jev prior and multi-signal prior did not improve the already-strong downstream judge and increased cost/reasoning.
3. local semantic recall in the 18-case short gate averaged only 0.6944; final 18/18 relied heavily on deterministic closure.
4. the coding-continuation smoke was more expensive end-to-end than full history because histories were small.
5. the cache economics probe produced no quality or economic advantage for window_jev:
   - 10/12 vs append_all 11/12;
   - more uncached input (15,594 vs 12,974);
   - less cached input (56,320 vs 60,416);
   - list-cost including Jev $0.010611594 vs $0.01050308 append_all and $0.01039808 window_rules.
6. OpenAI/Anthropic are actively productizing native context/history/memory/window primitives, increasing the risk that a custom general-purpose context manager becomes duplicated infrastructure.

## Final validation spend

The final four-gate validation sequence cost approximately $0.06816208 on frozen list-price estimates:
- fixed-input regression: $0.005356176;
- short-no-anchor full dev gate: $0.019849116;
- coding-continuation smoke: $0.001092714;
- window/cache smoke: $0.041864074.

This excludes earlier research runs and is not a provider invoice.

## Reopen criteria

Reopen this branch only when at least one trigger exists:

1. A real coding trace demonstrates a repeated history-recovery failure that native context management does not solve.
2. OpenAI/Anthropic expose stable history/new-context/memory primitives and we can test a **thin semantic policy adapter** without reimplementing storage/compaction.
3. A cheaper/local System-One-compatible backend materially changes the economics.
4. A control-routing use case can demonstrably replace an expensive model call (not merely precede it), with a measurable task-level benefit.

If reopened, first compare the thin Jev semantic layer against a deterministic/embedding/native baseline. Do not rebuild a standalone context platform.

## Long-term target

The enduring target is vendor-agnostic **semantic policy**, not custom memory infrastructure:

native vendor history/context manager
→ deterministic project state/provenance
→ optional semantic router for ambiguous evidence/control decisions
→ main model
→ deterministic safety/approval gates

The component is valuable only if enabling it measurably improves long-task quality/resource efficiency and disabling it leaves the base workflow fully functional.
