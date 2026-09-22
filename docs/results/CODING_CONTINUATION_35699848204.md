# Coding continuation smoke — run 35699848204

Date: 2026-09-22. Code: a2378ebf7d19a945c0b71dc94ec6f59f530891c2.
Artifact: 10682305874; digest sha256:7712bac46936a1116487eba6b331648b3d7b684077f4f139ece32e43b461959b.

## Result

Two authored continuation tasks were run: invoice rounding and payment-timeout/idempotency handling. The downstream model selected one of four predetermined patch candidates; local hidden behavioral tests evaluated the selected candidate. No generated model code was executed.

|strategy|hidden tests passed|LLM input|reasoning|LLM list-cost USD|
|---|---:|---:|---:|---:|
|full_history|2/2|734|700|0.000302120|
|rules_window|0/2|695|1024|0.000384020|
|jev_window|2/2|704|745|0.000310520|

Jev selection: 2 calls, estimated cost $0.000096054.
Total measured experiment list-cost: Jev $0.000096054 + LLM $0.000996660.

Production-like jev_window accounting for these two tasks:
- LLM $0.000310520 + Jev selection $0.000096054 = $0.000406574.
- Compared with full_history LLM $0.000302120, this tiny benchmark is about 34.6% more expensive end-to-end.
- Input reduction is only 30 tokens total (~4.1%) because the authored histories contain only six short records each. This benchmark tests unpaired-history sufficiency, not long-context economics.

## What happened

Rounding:
- full_history selected B and passed.
- rules_window supplied c04,c05,c01,c02,c03; the model hit the 512-token output/reasoning cap before returning a patch ID.
- jev_window supplied c01,c02,c04,c03,c06; selected B and passed.

Payment timeout:
- full_history selected B and passed.
- rules_window supplied p01,p02,p04,p05,p06, omitting p03: the provider contract exposing read-only status lookup by persisted idempotency key. The model again hit the 512-token cap.
- jev_window supplied p02,p03,p01,p04,p05; selected B and passed.

The Jev selector therefore retained sufficient ordinary, unpaired project-history evidence in both cases, including the semantically important p03 record that the simple lexical rule missed.

## Limits

- Only two authored tasks; no production error-rate estimate.
- One downstream observation per strategy/task, no temporally separated repeat.
- Strategy calls were made in fixed order (full_history, rules_window, jev_window), so latency/reasoning differences are not causal estimates.
- rules_window 0/2 are censored output-limit outcomes, not explicit wrong patch choices.
- All six downstream calls reported cached_input_tokens=0. This run says nothing about prompt-cache economics.
- Histories are tiny; jev_window is more expensive end-to-end here because the selector cost exceeds the small downstream input reduction.

## Decision

The stop condition "jev_window fails where full_history succeeds" was NOT triggered. Proceed to the bounded window/cache economics smoke.

Do not treat this as evidence that Jev is already cost-saving. The next gate is specifically responsible for measuring whether window-boundary selection can create enough context/cache benefit to repay the selector cost.
