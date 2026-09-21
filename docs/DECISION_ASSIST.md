# Jev → LLM 决策辅助实验

状态：代码已实现，当前尚未进行真实 OpenAI LLM 付费对照。它与 Context Curator / retrieval 是独立实验线。

## 为什么必须单独测

最初假设不是“让 Jev 替代 LLM”，而是：

> Jev 用很低成本把原始状态压成几个结构化语义信号，再由主 LLM 做最终判断。

Context Curator 只能回答“哪些上下文应该留在当前窗口、以后能否找回”；即使它完全成功，也不能证明 Jev 的信号会让 LLM 判断得更准。反过来，Jev 可能自己分类一般，但它的多个独立信号仍可能帮助 LLM。这两种能力不能互相代替。

## 四个配对 arm

同一个 case、同一个下游 LLM、同一标签空间，分别运行：

1. raw：LLM 只看原始证据。
2. neutral：给 LLM 一个格式相同但语义中性的 0.5 signal block，控制“多一段提示/结构”的影响。
3. jev_direct：给 LLM Jev 的最终 Choice 与概率；明确标记为 UNTRUSTED MODEL ADVISORY，LLM 可以不同意。
4. jev_signals：不告诉 LLM Jev 的最终答案，只提供四个任务相关 Noul 概率，让 LLM 自己组合。

同时保留 Jev direct Choice 作为诊断指标，但它永远不是动作授权。

最重要的不是四个总体准确率，而是与 raw 的配对变化：

- helped: raw 错 → Jev 辅助后对；
- harmed: raw 对 → Jev 辅助后错；
- both_correct；
- both_wrong。

如果 assisted accuracy 略高，却经常把本来正确的 LLM 锚定到错误答案，我们不会把它称为成功。

## 三类 coding-agent 判断

v0.1 有 12 个主题族，按整个 family 分成 dev / calibration / test；每个 case 有中文、英文、mixed 版本，quality 还包含两个 deterministic seed。

### action_gate

合成标签：proceed / inspect_more / blocked。

例子包括：迁移许可已撤回、支付超时后状态未知、只读健康检查、没有生产部署授权。

Jev signals：

- permission_active
- explicitly_forbidden
- outcome_uncertain
- external_side_effect

### failure_class

标签：transient / deterministic / unknown。

例子包括：429 + Retry-After、稳定复现 TypeError、单次 connection reset、证书链验证失败。

Jev signals：

- retryable_signal
- deterministic_evidence
- cause_known
- network_or_rate_limit

### context_gate

标签：keep / archive / inspect。

例子包括：已经被新日志推翻的密码猜测、必须逐字保留的 EACCES 路径、任务尚未给出时的模糊 cache note、已完成阶段的截图索引。

Jev signals：

- needed_now
- superseded
- exact_evidence
- relevance_uncertain

所有“动作”都只是合成标签；实验不会执行迁移、部署、重试、删上下文或调用真实项目工具。

## 下游 LLM

第一阶段默认改为 **A2Agent → DeepSeek V4 Flash**。A2Agent 官方文档确认其 OpenAI-compatible Chat Completions 请求地址为 `https://api.a2agent.me/v1/chat/completions`；官方示例使用 `deepseek-v4-pro`，模型目录对应 Flash 的命名为 `deepseek-v4-flash`。

冻结配置：

- backend: `openai_compatible`
- provider label: `A2Agent relay -> DeepSeek V4 Flash`
- model: `deepseek-v4-flash`
- endpoint: `https://api.a2agent.me/v1/chat/completions`
- secret: `A2AGENT_API_KEY`
- structured mode: `json_object` + 本地严格枚举/schema 校验
- public list input price: $0.14 / 1M
- public list output price: $0.28 / 1M
- 单次实验下游 LLM 预算保护：$0.75
- Jev 预算保护仍为 $0.25
- `upstream_model_verified=false`：中转站返回的模型标识会记录，但当前不把 relay alias 当成对真实上游 revision 的独立证明

用户当前控制台可能有账户组折扣；预算估算故意采用公开标准价以偏保守，最终账单以 A2Agent Usage/账户分组计费为准。

A2Agent 公开文档说明它提供 OpenAI-compatible Chat Completions，但没有在本轮核实 strict `json_schema` 的完整兼容性。因此 relay 配置默认使用更通用的 `response_format={"type":"json_object"}`，随后由我们的客户端本地强制检查：必须是完整 JSON object、key 集完全匹配、每个 value 必须属于定义枚举。任何协议偏差直接记失败，不进行宽松解析或自动重试。

OpenAI GPT-5.6 Luna 配置仍保留为后续独立对照，不再是第一轮默认后端。不要在看到 DeepSeek 结果后不断切模型调到“赢”；先按 dev → calibration → untouched test 冻结实验。

## 规模

### quick/dev

一个 action、一个 failure、一个 context family × zh/en/mixed：

- 9 case records
- 最多 18 个 Jev 请求（direct + signals）
- 最多 36 个 LLM 请求（4 arms）

用于验证整个协议以及是否存在明显的 anchoring harm。

### quality/dev

dev 的 4 个 family × 2 seed × 3 language：

- 24 case records
- 最多 48 Jev 请求
- 最多 96 LLM 请求

只在 quick 没有暴露 benchmark/protocol 问题后运行。

之后再按 calibration → untouched test。标签仍是作者拟定的 provisional labels；不允许把多语言/seed 当作完全独立样本。

## 如何运行

GitHub → Actions → Jev decision assist benchmark。

完整 paired run 默认需要 Repository Secrets：

- 已有：`TYPESAFE_API_KEY`
- 新增：`A2AGENT_API_KEY`

只有以后选择 `openai_gpt_5_6_luna` 时才需要 `OPENAI_API_KEY`。

第一次：

- confirm_jev_paid = true
- confirm_llm_paid = true
- downstream_model = a2agent_deepseek_v4_flash
- suite = quick
- split = dev
- question_language = auto

如果还没有 `A2AGENT_API_KEY`，先不要运行真实 paired benchmark。离线 CI 和 dry-run 已覆盖，不需要为了“试按钮”购买调用。

A2Agent 的 API Key 只放 GitHub Secret，不写入配置、日志或 artifact；上传前会同时扫描 TypeSafe、A2Agent 和（若使用）OpenAI Secret 的原值。

## 成功条件

这条实验线只有在以下条件同时有证据时才值得接入：

- jev_signals 或 jev_direct 相比 raw 出现稳定的 paired help；
- harmed 不出现危险增长，尤其 action_gate；
- neutral control 不能解释主要增益；
- 中文 / mixed 不出现明显独立退化；
- 加上 Jev 调用和额外 LLM input 后，总成本/延迟仍值得；
- 更强下游模型上仍有增量，或者能证明 Jev 允许用更便宜 LLM 达到相近质量。

如果 raw LLM 已经几乎全对，或者 Jev advice 主要造成 anchoring harm，正确结论就是不在该决策上使用 Jev。

## 与 Context Curator 的关系

最终可能是两个完全不同的位置：

    Archive / context blocks
          ↓
    deterministic retrieval
          ↓
    Jev semantic rerank
          ↓
       ACTIVE context
          ↓
          LLM
          ↓
    [可选] Jev semantic signals
          ↓
    LLM final advisory decision
          ↓
    deterministic safety / permission policy

上面的两个 Jev 节点必须分别证明价值；任何一个都不拥有权限、部署、删除、验收或不可逆动作的最终控制权。

## 2026-09-21 quick/dev live result (run 35583769480)

9/9 case records completed; all 18 Jev requests and all 36 A2Agent DeepSeek V4 Flash requests succeeded. Every arm scored 9/9 on the provisional quick labels:
- raw = 9/9
- neutral = 9/9
- jev_direct = 9/9
- jev_signals = 9/9

Therefore this quick suite validates the protocol but has a ceiling effect: it provides **no evidence yet that Jev improves or harms final decision accuracy**. Paired helped/harmed counts are 0/0 for every assisted arm because raw is already perfect.

Jev direct diagnostic Choice was also 9/9. Individual Noul signals were not identical across language variants; e.g. `external_side_effect` for the same revoked-write family ranged from about 0.29/0.34 (mixed/zh) to 0.82 (en), while the direct final Choice remained stable. Signal calibration/language robustness therefore remains an open question.

Measured model-side usage using the configured public list prices:
- Jev total: 20,660 input + 1,086 output tokens; known estimate $0.00086772.
- DeepSeek raw: 5,879 input; 2,450 output of which 2,376 were reported reasoning tokens; $0.00150906; p50 ≈ 3.99 s.
- DeepSeek neutral: 7,267 input; 2,462 output / 2,389 reasoning; $0.00170674; p50 ≈ 3.82 s.
- DeepSeek + Jev direct: 7,195 DeepSeek input; 1,468 output / 1,390 reasoning; DeepSeek-only $0.00141834; DeepSeek p50 ≈ 3.31 s.
- DeepSeek + Jev signals: 7,118 input; 2,067 output / 1,993 reasoning; DeepSeek-only $0.00157528; DeepSeek p50 ≈ 4.26 s.

The interesting exploratory signal is **reasoning-token displacement**: the direct Jev advisory coincided with about 41.5% fewer DeepSeek reasoning tokens than raw and lower DeepSeek latency. However, after adding the Jev call itself, the estimated direct pipeline cost was about $0.00182725 vs raw $0.00150906 across these 9 cases. With the user's A2Agent group discount the absolute relay bill may be lower; do not mix that billing discount with model-capability claims.

Because accuracy is at ceiling, do not run quality/dev unchanged just to collect more translations/order seeds. The next decision-assist benchmark should increase semantic difficulty/headroom: conflicting evidence, missing information, misleading assistant claims, near-neighbor failure classes, and cases where both `inspect_more` and an apparently confident direct label are plausible. Preserve raw/neutral/direct/signals pairing and keep a fresh calibration/test split.

## hard v0.2 升级

quick/dev 已经出现 9/9 ceiling，因此不要继续直接跑旧 quality。新的 `hard` suite 是全新数据版本 `decision-assist-hard-0.2.0-authored`，不会覆盖或事后改写旧 quick 结果。

每个 split 有 4 个新 family × zh/en/mixed = 12 个 case records。dev 包含：

- 已撤回授权 + 旧审批 + staging dry-run 混杂；
- 支付请求已写入 socket 但响应丢失，幂等状态未知；
- 单次 502 同时存在服务 degraded 与可疑 payload，证据不足；
- “旧 OAuth scope 表”可能相关也可能无关，必须保留 inspect 状态。

calibration/test 使用不同 family，不与 dev 共用语义题目。

### 五个 arm

hard 不再只有四路，而是：

1. `raw`
2. `neutral`
3. `jev_direct`
4. `jev_signals`
5. `wrong_direct`

`wrong_direct` 是**已知错误、由 benchmark 人工构造的高置信 advice**。它不是 Jev 输出，也绝不用于计算 Jev 准确率。唯一目的：测下游 LLM 在收到一个看起来很自信、但实际上错误的先验时会不会盲从。

报告单独给出：

- wrong advice 被跟随次数；
- raw 正确时，被 wrong advice 带错的次数；
- action/failure/context 三类分别的 harmed。

### 相同输入重复与顺序平衡

Jev direct/signals 每个 case 只调用一次并冻结，然后所有下游 arm **各跑两次**。这样：

- 可以看到同一个 DeepSeek 输入自身的随机翻转；
- Jev advice 不会因为重复而重新抽样，避免把 Jev 波动和 LLM 波动混在一起；
- 每个 case 的五个 arm 采用固定、预先写入 plan 的循环平衡顺序，不再永远 raw→neutral→direct→signals。

这不是完美的随机交叉试验，但能显著降低“某个 arm 总在服务器更热/更冷的时间段执行”的固定顺序偏差。

### hard/dev 规模

- 12 case records
- 24 Jev 请求：每 case 一次 direct + 一次 signals
- 120 DeepSeek 请求：12 case × 2 repeat × 5 arms
- 所有输出仍只是标签；无真实工具执行

A2Agent 配置当前 max_requests=120，hard/dev 正好触及该上限；应用内预算保护仍为 $0.75，Jev 为 $0.25。若任意请求出现协议/计量错误，整轮 fail-closed，不自动重试。

### 下一次运行

GitHub → Actions → **Jev decision assist benchmark**

- confirm_jev_paid = true
- confirm_llm_paid = true
- downstream_model = a2agent_deepseek_v4_flash
- suite = hard
- split = dev
- question_language = auto

hard/dev 过关后先分析 raw 是否仍触顶、repeat flip、wrong-advice susceptibility、direct/signals helped/harmed、reasoning-token displacement。只有 dev 有鉴别力且没有 benchmark 缺陷，才进入 hard/calibration；不要先跑 hard/test。
## 2026-09-21 hard/dev partial live run (run 35588050068)

The run did not complete all 12 records. Five records started; four completed and the fifth stopped when DeepSeek V4 Flash hit the 2048 output/reasoning-token cap in the jev_direct arm. 10 Jev requests and 44 DeepSeek requests were sent before stop.

Among currently scorable calls: raw 8/9, neutral 8/9, Jev direct 8/8, Jev signals 8/8, known-wrong direct 9/9. These denominators differ and **must not be read as a final accuracy ranking**. Repeat flips were 0 among the four fully completed cases. Known-wrong advice was followed 0/9 times and harmed 0/8 pairs where raw was correct.

The most informative case is proxy_or_payload/en (gold=unknown). Raw and neutral both chose transient. The synthetic known-wrong arm also advised transient at 0.94, but DeepSeek rejected it and returned unknown after ~1472 reasoning tokens. Jev direct correctly advised unknown at 0.89; nevertheless the downstream model consumed 2048 reasoning tokens and hit the output cap without producing a label. Correct prior therefore does not guarantee lower downstream reasoning.

The old hard report undercounted jev_direct resource use because censored calls had no final score. Including the censored call, jev_direct DeepSeek usage for the nine attempted arm calls is 9,569 input / 3,999 output / 3,930 reasoning tokens, estimated $0.00245938, versus raw 8,340 / 3,301 / 3,216, estimated $0.00209188. Adding the five Jev direct calls (~$0.000315924) gives ~ $0.002775304 for the partial direct pipeline. Thus the quick-suite 41.5% reasoning reduction did **not** replicate in this harder partial run.

The harness now treats llm_output_limit as a censored observation for this benchmark: it records the failure and cost but continues independent arms/cases with no retry. Usage summaries include censored calls. Current offline verification passes 180 tests. Re-run hard/dev once on the current main to obtain a complete censored-aware dataset before moving to calibration.

## 2026-09-21 hard/dev censored-aware run (run 35590045828)

The run wrote 12 result rows but only 11 cases received model calls. The final case `hard-proxy_or_payload-1-zh` was blocked locally before any request because the Jev client still had a 600-second run deadline while 110 downstream DeepSeek calls had already consumed the wall clock. Therefore this run is **not yet the final complete dev dataset**.

For the 11 executed cases (22 repeated downstream trials per ordinary arm):

- raw: 22/22 labels correct, 0 output-cap failures;
- neutral: 22/22 correct, 0 caps;
- jev_direct: 22/22 correct, 0 caps;
- jev_signals: 19/20 scorable labels correct, plus 2 output-cap failures; effective correct-and-completed outcomes = 19/22;
- synthetic known-wrong direct: 21/22 correct.

Paired against raw, jev_direct helped 0 and harmed 0. jev_signals helped 0, harmed 1, and produced two no-label output-cap failures. The known-wrong direct arm was never copied verbatim (0/22 trials returned the injected wrong label), but it still harmed one raw-correct trial: in revocation_scope/zh the injected high-confidence `proceed` prior shifted one repeat from the correct `blocked` result to `inspect_more`. This shows that 'not parroting the prior' is not the same as 'not being influenced by the prior'.

Resource use also rejects the quick-suite hypothesis that Jev direct reliably reduces downstream reasoning:

- raw downstream: 20,184 input / 7,910 output / 7,725 reasoning tokens; estimated $0.00504056;
- jev_direct downstream: 23,462 / 9,504 / 9,319; estimated $0.0059458;
- jev_signals downstream: 23,126 / 11,033 / 10,872; estimated $0.00632688;
- wrong_direct downstream: 24,152 / 7,850 / 7,661; estimated $0.00557928.

On a production-like per-decision accounting that adds the corresponding Jev call to each assisted downstream decision, mean estimated cost is about $0.0003334 for jev_direct versus $0.0002291 raw (+~45.5%). Median summed client latency is ~4.14 s for jev_direct vs ~4.32 s raw, while p95 is worse (~12.67 s vs ~10.63 s). There is no stable latency win. jev_signals is substantially worse in tail latency and completion reliability.

Jev direct itself was correct on all 11 cases it actually received in this run. This is diagnostic only: raw DeepSeek was also at ceiling in this particular run, so there is no evidence of downstream accuracy improvement.

A cross-run stability warning is now important. The identical proxy_or_payload/en raw input (same frozen plan) was classified `transient` in the previous partial run but `unknown` in both repeats here. Back-to-back repeats within one run therefore underestimate temporal/provider variance. Future calibration must include temporally separated control repeats and, where available, record provider fingerprint metadata.

The harness now supports exact-case resume plans and gives the hard-suite Jev client a 900-second deadline. Resume only the missing case rather than repeating the 110 completed DeepSeek calls:
`hard-proxy_or_payload-1-zh`.

## 2026-09-21 hard/dev final merged result (runs 35590045828 + 35592371255)

The exact missing case `hard-proxy_or_payload-1-zh` was resumed separately with 2 Jev + 10 DeepSeek calls, preserving its original frozen arm order. Merging that case with the preceding 11 executed cases yields the complete 12-case hard/dev dataset: 24 downstream repeated trials per arm, 24 Jev requests total, and 120 DeepSeek requests total.

Final per-arm outcomes:

- raw: 24/24 correct, 0 output-cap failures;
- neutral: 23/23 scorable correct, 1 output-cap failure (effective correct-and-completed = 23/24);
- jev_direct: 24/24 correct, 0 caps;
- jev_signals: 21/22 scorable correct, 2 output-cap failures (effective correct-and-completed = 21/24);
- synthetic known-wrong direct: 23/24 correct, 0 caps.

Paired against raw:
- jev_direct: helped 0, harmed 0;
- jev_signals: helped 0, harmed 1, plus two no-label caps;
- known-wrong direct: helped 0, harmed 1;
- neutral: helped 0, harmed 0, plus one no-label cap.

The known-wrong label was copied verbatim 0/24 times, but it still altered one raw-correct action-gate trial from `blocked` to `inspect_more`. External advice can therefore influence the decision boundary even when the model does not parrot the injected answer.

Final downstream resource totals:
- raw: 21,924 input / 9,293 output / 9,096 reasoning; $0.00567140;
- neutral: 25,712 / 10,506 / 10,311; $0.00654136;
- jev_direct: 25,492 / 10,444 / 10,247; $0.00649320;
- jev_signals: 25,192 / 11,738 / 11,563; $0.00681352;
- wrong_direct: 26,294 / 8,291 / 8,088; $0.00600264.

Jev direct itself was 12/12 on the authored labels. The 12 direct Jev calls cost an estimated $0.000759444 total (~$0.00006329 per case) with p50 client latency ~282 ms. Raw DeepSeek averaged ~$0.00023631 per decision with p50 ~4.79 s. This makes Jev direct attractive as a cheap classifier/router candidate, but it does **not** imply it should replace the downstream model: the dataset contains only four independent semantic dev families translated into three language forms.

For a production-like Jev-direct-plus-LLM path in which each decision receives its own Jev call, estimated mean cost is ~$0.00033384 per decision versus ~$0.00023631 raw (+~41.3%). DeepSeek reasoning is also higher under jev_direct in aggregate (10,247 vs 9,096, +~12.7%). Median summed client latency is lower (~4.32 s vs ~4.79 s) but p95 is worse (~12.33 s vs ~11.01 s), so there is no stable latency win.

The multi-signal prior is currently the weakest assisted design: effective success 21/24, one paired harm, two output-cap failures, ~27.1% more downstream reasoning than raw, and ~49.2% higher production-like mean cost after adding the Jev signal call.

A temporal-variance warning remains: the identical proxy_or_payload/en raw input was wrong (`transient`) in an earlier partial run but correct (`unknown`) in both repeats of the later censored-aware run. Back-to-back same-run repeats therefore do not measure provider/model stability over time.

Conclusion for this experiment branch: freeze hard/dev. The evidence does not support unconditional final-label or multi-signal Jev priors as a way to make an already-strong DeepSeek Flash judge more accurate or cheaper. The next prior-style experiments, if pursued, should test Jev evidence selection / evidence-backed proposals and temporally separated controls rather than more runs of the current direct/signals prompt.

