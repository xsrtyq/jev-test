# Fixed-input retrieval regression — run 35698863339

Date: 2026-09-22. Code: ecc79a18688dce71e8f51dbd4d26982c5276229e.
Artifact: 10680869073, digest sha256:43a1805e5ecca3f9258ecf8b1a841c9b77849c3cf40fbfe63210b37501ef9e53.
Fixture state hash: af610538b65773a2d5e5cae7416cceff350b477187ea4720b0c1cce2b1f4fda7.

The same exact v0.5 known-failure state was evaluated under three retrieval implementations.

|strategy|Jev calls|input tokens|known cost USD|sequential client ms|local recall|final recall|all required|
|---|---:|---:|---:|---:|---:|---:|---:|
|legacy_v05|5|45,811|0.001924062|2,225.99|0.5|0.5|false|
|short_no_anchor|3|25,769|0.001082298|1,213.98|0.5|1.0|true|
|relation_anchor_v06|6|55,948|0.002349816|2,455.26|1.0|1.0|true|

Total experiment cost estimate: $0.005356176. No downstream LLM was called.

## Interpretation

1. The old failure reproduces on the exact frozen input, so the original v0.5 miss was not an artifact of changing fixture IDs.
2. The relation-aware v0.6 path improves local survival from 0.5 to 1.0 and produces a complete final packet.
3. However, relation anchors are **not necessary to obtain a complete final packet on this one case**. Merely moving to 64-block shards plus the shorter relevance question also yields final recall 1.0.
4. short_no_anchor still has local recall 0.5. Its final success depends on deterministic pair/dependency closure restoring the missing result after a related tool-call survives. This is legitimate system behavior for paired tool history, but does not prove robustness for unpaired semantic notes.
5. On this case, short_no_anchor uses ~53.9% fewer Jev input tokens and ~54.0% lower Jev list-cost than relation_anchor_v06, and roughly half the sequential client time.

Therefore the next experiment should not immediately run the more expensive relation-aware design across all dev cases. Apply a **simplest-sufficient strategy gate**:

- First run short_no_anchor on all 18 stable retrieval128/dev fixtures (54 Jev requests).
- If it finishes 18/18 final all-required evidence, prefer the simpler method for the next economic/coding smoke; keep relation-aware retrieval as an unproven fallback hypothesis.
- If short_no_anchor misses any final evidence, run relation_anchor_v06 on the same frozen 18 fixtures and compare the exact failures.
- Do not tune against calibration/test at this point.

This remains an authored synthetic benchmark and is not a production error-rate estimate.
