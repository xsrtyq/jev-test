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
