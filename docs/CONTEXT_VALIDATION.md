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
