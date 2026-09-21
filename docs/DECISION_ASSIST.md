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

第一阶段固定 gpt-5.6-luna，原因不是认为它最好，而是它是当前官方面向成本敏感高吞吐工作的 GPT-5.6 档位，适合先验证“Jev 是否能给较小 LLM 带来增量”。

当前冻结配置：

- model: gpt-5.6-luna
- Chat Completions + strict JSON Schema
- reasoning effort: none
- input: $0.20 / 1M tokens
- cached input: $0.02 / 1M
- output: $1.20 / 1M
- 单次实验 LLM 预算保护：$0.75
- Jev 预算保护仍为 $0.25

来源：
- https://developers.openai.com/api/docs/models/gpt-5.6-luna
- https://developers.openai.com/api/docs/guides/structured-outputs

OpenAI 官方当前支持 Chat Completions 与 Responses 的 Structured Outputs；本实验沿用仓库已有的 Chat Completions stdlib 适配器，只输出一个严格枚举标签，不要求长解释。

如果 Luna 上出现明确增益，后续再用独立冻结配置验证 Terra / Sol；不要先不断换模型直到结果变漂亮。

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

完整 paired run 需要 Repository Secrets：

- 已有：TYPESAFE_API_KEY
- 新增：OPENAI_API_KEY

第一次：

- confirm_jev_paid = true
- confirm_llm_paid = true
- suite = quick
- split = dev
- question_language = auto

如果没有 OPENAI_API_KEY，先不要运行真实 paired benchmark。离线 CI 和 dry-run 已覆盖，不需要为了“试按钮”购买调用。

API 费用是 OpenAI API 账户的独立计费项目；本 workflow 只读取 GitHub Secret，不把 key 写进配置、日志或 artifact。上传前分别扫描两个 secret 的原值。

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
