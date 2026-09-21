# v0.2 实现验证记录

日期：2026-09-21。以下是实际运行过的检查，不是预计结果。

## 本次实际完成

- 从四个现存原始 ZIP 重算 v0.1 的 360 条结果；得到 347/360、310 个高 pmax 关联观测中零错误、估计模型费 $0.015228444。审计脚本和哈希已保存。
- 在 ChatGPT 工作容器的 Python 3.13.5 上运行 `python -m unittest discover -s tests -v`：**新增 88 项离线测试通过**。
- `quick`、`quality`、`robustness`、`scaling`、`fanout`、`replay --steps 50` 的 CLI 不联网运行均完成，六组均记录 `real_model_requests=0`、`offline_no_model_results`。10/20 步回放也由单元测试覆盖。
- 验证旧许可撤销、可信来源、约束预算溢出、工具调用/结果配对、叙述依赖、归档哈希损坏、检索失败、未来信息隔离、短视图、版本变化、无用量停止、密钥不上产物、默认禁用网络等边界。
- Choice、Noul、Score 的响应协议由明确的假供应商测试验证；**不是实际 Jev v0.2 结果**。可选云端小 LLM 的严格 JSON 请求路径已实现，真实供应商兼容性仍需其模型和密钥验证。

仓库原有 60 项 v0.1 离线测试未修改。新 GitHub Actions 将运行整个 tests 目录；其是否成功，以对应提交的 Actions 结果为准，不凭本地 88 项测试声称远端已通过。

## 没有运行或没有证明

本次没有新 Jev 付费调用、没有使用聊天中出现过的密钥、没有下游生成 LLM 调用、没有本地神经模型、没有人工金标准、没有实际主工作流接入。

证据召回不是 LLM 任务完成率；UTF-8 字节不是 provider token；序列化前缀不是实际 KV/prompt-cache 命中；程序固定保留约束不是 Jev 自身识别约束的成绩；合成场景不是独立真实 coding session。

## 已知实现边界

每次手动运行的 $0.25 是应用内估算保护，不是跨运行或供应商发票硬限额。socket timeout 不能保证严格的单次总墙钟期限；程序在请求间检查总时限，并由 Actions job 上限补充。发生未知用量、协议错误或预算估计不足时停止，不自动重试。

原始档案/身份元数据由受控测试环境提供，不含真实用户角色/权限提取器。归档检索是 lexical 基线，不是已证明可靠的召回器；失败必须留在统计中。冻结数据的流程约束与哈希并不阻止操作者反复查看测试集，不能冒称形式化防泄漏。

## 2026-09-21 quick live run

Run `35576946439` used commit `6e834eaa508b28831b8a28545a2ba65225daca5c`: 18/18 real Jev requests succeeded, 92,092 input tokens, known model-cost subtotal $0.003867864, client p50 about 409 ms and p95 about 564 ms.

Across the six condition records per primitive, policy-level required-evidence recall was 1.0 and serialized byte reduction was about 24%–29%. This includes deterministic PINNED constraints and dependency closure, so it is NOT Jev-only accuracy. Using Choice rows as one non-independent view, model policy recall was 1.0; lexical/equal-score about 0.833; recency 0.5 at roughly similar byte reduction. Only two template families were present, so this is a smoke signal, not a statistical result.

Choice used 24,370 input tokens (~$0.001024, p50 ~390 ms); Score 21,926 (~$0.000921, p50 ~369 ms); four Noul signals 45,796 (~$0.001923, p50 ~470 ms). The signals form asked four times as many questions, so parallelism kept latency growth modest, but it consumed materially more input and showed no retention benefit on this tiny set.

The run exposed two benchmark-design problems. First, the provisional `needed` gold mixed semantic direct evidence with deterministic obligations (PINNED constraints and tool-call/result closure). Six apparent high-confidence `needed=no` errors were on such structural/policy items; their `constraint` signal was 0.93–0.96. They must not be reported as six high-confidence semantic failures. Second, the later-retrieval gold was already present in the initial selected context, so `recovery=1.0` did not exercise archive retrieval.

Commit `cdd77c8` separates direct-evidence labels from policy closure and makes future retrieval target a neutral historical reference that is not an initial requirement. Commit `5c62d60` fixes a Python newline regression found by CI. Both offline workflows pass on `5c62d60`. The old quick artifact remains immutable evidence and is not retroactively rescored as the new benchmark.

Decision after revised quick run `35577897610`: 18/18 requests succeeded; 92,011 input tokens; known model-cost subtotal $0.003864462; client p50 about 198 ms and p95 about 294 ms. All language/primitive groups retained direct evidence and required policy evidence with no corrected high-confidence binary diagnostic errors; serialized byte reduction was about 24%–30%. However, six conditions actually archived the later target and exercised recovery, and the existing lexical fallback recovered only 1/6. The successful case was zh/payment/signals; English and mixed recovery failed. Signals archived the neutral future reference in 5/6 cases, Choice in 1/6, Score in 0/6, showing the expected tradeoff: more aggressive curation increases dependence on recovery. Therefore `quality` remains paused. A new isolated `retrieval/dev` suite compares lexical, structured-anchor and Jev semantic retrieval before any further scaling.

## 2026-09-21 isolated retrieval/dev live run (run 35579241228)

Workflow UI ended red, but the experiment itself completed: all 12/12 real Jev requests returned OK, summary.json and all 12 result rows are complete. The failure occurred afterwards while creating failures.jsonl: generic context code tried to read retrieval rows as model_result.metrics. Commit a8cd377 fixes the branch order; 9cff709 adds a live-fake regression test. Both offline workflows pass. Do not rerun this paid experiment just to turn the card green.

Measured retrieval result on dev (4 template families × zh/en/mixed, one seed):
- Jev semantic retrieval: top-1 12/12, top-4 12/12. Mean target Noul probability = 0.86. Minimum target-vs-runner-up margin = 0.38; all targets ranked first.
- deterministic lexical top-4: 4/12 (33.3%) — zh 4/4, en 0/4, mixed 0/4.
- deterministic structured-anchor top-4: 10/12 (83.3%) — zh 4/4, en 2/4, mixed 4/4.
- Jev input = 38,135 tokens, known model cost = $0.00160167, client p50 ≈ 166.8 ms, p95 ≈ 262.9 ms.

Target probability by language: zh mean 0.8425, en 0.9075, mixed 0.83. Lowest target probability was 0.73 (session/mixed), yet its runner-up was only 0.17. This is a strong dev smoke signal for Jev as an archive semantic retriever, not proof of production recall.

Important limitation: target notes intentionally contain recognizable historical references/paths and the later query explicitly requests a historical reference. The dev result may therefore be easier than open-ended real coding recall. The code/prompt is now frozen for this retrieval experiment; next use retrieval/calibration on unseen template families. Only if calibration remains strong should the untouched retrieval/test split be run once. Context quality expansion remains paused until this generalization check.

## 2026-09-21 isolated retrieval/calibration live run (run 35579713526)

12/12 real Jev requests succeeded. Input 38,187 tokens; known model-cost subtotal $0.001603854; client p50 ≈ 377.3 ms and p95 ≈ 417.8 ms.

Raw calibration report: Jev top-1 9/12 (75%), top-4 12/12 (100%). By language, top-1 = 3/4 for zh, en and mixed; top-4 = 4/4 for all three. Mean target probability: zh 0.74, en 0.8325, mixed 0.7275.

All three top-1 misses are the same `paths` template family. The query asks for a generic historical reference/path, while that scenario contains multiple plausible paths (old input path, current actual path, historical screenshot index). Jev ranks the intended screenshot index 2nd/3rd rather than first. Therefore top-1 is partly benchmark-ambiguous here; top-4 is the cleaner signal.

A separate implementation bug was found in the deterministic structured baseline: raw regex strings had double-escaped `\\b`, `\\d`, `\\s` and Unicode ranges, so obvious path/ID anchors were under-detected. Recomputing the existing dev and calibration artifacts offline with the corrected regex yields structured top-4 = 12/12 on dev and 12/12 on calibration (24/24 combined). No paid calls are needed for this correction. Commit `fdc82c5` fixes the regex and `98e2488` adds explicit anchor-shape tests; both offline CI workflows pass.

Consequence: the current retrieval benchmark does **not** establish incremental value for Jev over a correct deterministic structured retriever. It establishes that Jev can retrieve the intended item into top-4 on all 24 dev+calibration language variants, but the deterministic structured strategy also does so after the bug fix. Do not run the current retrieval/test split yet: it is likely too easy and uses the same obvious anchor structure.

Next benchmark should be harder and newly versioned: larger archives, multiple competing paths/IDs, queries asking for reasons/decisions/previously rejected approaches rather than literally asking for a historical path, and separate measurement of candidate recall vs Jev reranking. A fresh untouched test split is required after redesign.
## 2026-09-21 retrieval_hard v0.4 dev live run (run 35587967298)

12/12 records completed, 24 Jev requests succeeded. Total input 221,306 tokens; known model-cost subtotal $0.009294852; client p50 ≈423 ms, p95 ≈530 ms.

The deterministic prefilter is the bottleneck: Top-16 candidate recall = 6/12 overall (zh 3/4, en 2/4, mixed 1/4); deterministic hybrid Top-4 = 4/12. When the target is actually present in Top-16, Jev reranks it to Top-1/Top-4 in 6/6. Jev scoring the full 64-block archive ranks the target Top-1 in 12/12, with target probability 0.83–0.95 (mean ≈0.903).

Candidate-only Jev path: 47,984 input tokens, ~$0.002015, median client latency ≈363 ms. Full-64 Jev path: 173,322 input tokens, ~$0.007280, median ≈497 ms. This is a small synthetic run; do not generalize the latency scaling beyond it.

Interpretation: on this dev set, semantic retrieval itself is strong while lexical/metadata prefiltering—especially cross-language/mixed—is the limiting stage. Do not rerun dev. Next run the frozen v0.4 retrieval_hard on calibration. If that generalizes, test sharded semantic retrieval for archives larger than one Jev state window rather than aggressively pruning by lexical similarity.

## 2026-09-21 retrieval_hard v0.4 calibration live run (run 35589853253)

12/12 records completed; 24/24 Jev requests succeeded. Total input 221,645 tokens; known model-cost subtotal $0.00930909; client p50 ≈482.8 ms and p95 ≈836.8 ms.

Calibration reproduces the dev split's central result:

- deterministic Top-16 candidate recall = 6/12 overall;
- deterministic hybrid Top-4 = 2/12 overall;
- when the target is present in Top-16, Jev candidate rerank puts it Top-1 in 6/6;
- Jev scoring the full 64-block archive puts the target Top-1 in 12/12 and Top-4 in 12/12.

By language, Top-16 candidate recall is zh 3/4, en 3/4, mixed 0/4. Full-64 Jev is 4/4 Top-1 in zh, en and mixed. Mean full-64 target probability ≈0.924; minimum target-vs-runner-up margin ≈0.22, mean margin ≈0.689. The smaller margins are concentrated in the queue-concurrency family, but the target still ranks first.

Cost/latency split: candidate-only Jev used 48,203 input tokens, ~$0.002025, p50 ≈397 ms; full-64 Jev used 173,442 input tokens, ~$0.007285, p50 ≈507 ms.

Across dev + calibration, full-64 Jev is now 24/24 Top-1 on 8 held-out template families × three language forms, while deterministic Top-16 candidate recall is 12/24 and remains especially poor for mixed-language cases. This is still a synthetic authored benchmark, not production proof.

Next step: freeze retrieval-hard v0.4 and run the untouched test split once. Do not tune prompts or thresholds before that run. If test preserves the result, move from single-archive experiments to sharded semantic retrieval at 128/256+ blocks and measure downstream task recovery, not just evidence ranking.

