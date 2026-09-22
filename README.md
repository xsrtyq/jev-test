# Jev Decision & Context Research

独立、可复现、中文优先的 Jev / System One 实验仓库。  
Independent research on Jev/System-One-style semantic decision models for routing, evidence selection, and long-agent context management.

**当前状态：研究分支已冻结（2026-09-22）。**

本仓库的结论不是“Jev 无效”，而是：Jev 在语义选择上显示了真实能力，但目前没有观察到足以支持把它接入生产 coding workflow 的稳定端到端质量/成本优势。因此不继续扩展独立 context manager，保留实验、接口和复现材料，等待新的真实证据或厂商原生 context/history primitives 成熟。

本项目与 TypeSafe、OpenAI、Anthropic 等厂商无隶属关系。

## 结论先读

目前最值得保留的工程结论是：

> **语义模型适合做粗粒度候选选择；结构完整性应由确定性程序保证。**

在 authored synthetic dev 集中，较轻的 64-block + short question + deterministic pair/dependency closure 路线最终恢复了 **18/18** 案例的全部必要证据，但 Jev 自身平均局部语义 recall 只有约 **69.4%**。完整率来自“语义粗筛 + deterministic provenance closure”的组合，而不是单独依赖模型概率。

缓存经济性 smoke 的结果：

| strategy | correct / 12 | input | cached | uncached | trace cost incl. Jev |
|---|---:|---:|---:|---:|---:|
| append_all | 11 | 73,390 | 60,416 | 12,974 | $0.010503 |
| rewrite_each | 10 | 71,120 | 56,320 | 14,800 | $0.010351 |
| window_rules | 10 | 71,910 | 56,320 | 15,590 | $0.010398 |
| window_jev | 10 | 71,914 | 56,320 | 15,594 | $0.010612 |

这不是 Codex/OpenAI KV-cache benchmark，而是 A2Agent/DeepSeek relay 上的一次固定轨迹 smoke。它否定了“当前实现已经明显更省”的假设，但不能证明真实超长 coding session 永远没有 break-even 点。

完整冻结理由：docs/JEV_FREEZE_DECISION_2026-09-22.md

## 我们测过什么

### 基础分类与鲁棒性

覆盖中文、英文和中英混合状态，以及 option order、prompt injection、长 distractor 等变体。语言变体属于相关样本，不能当作额外独立任务。

### Context retrieval

实验从 64-block 语义检索扩展到 128-block sharded archive，并暴露了跨分片 current revision/scope binding 问题。

固定输入回归比较：
- 旧 32-block 长问题方案；
- 64-block 短问题方案；
- relation-aware 两阶段 anchor 方案。

两阶段 anchor 能提高局部存活率，但较轻方案也能通过 deterministic closure 获得完整最终证据，而且在已知失败案例上的 Jev 输入/费用约为两阶段的一半。

结果：
- docs/results/FIXED_REGRESSION_35698863339.md
- docs/results/SHORT_GATE_35699455848.md

### Evidence-first downstream reasoning

Jev 只选择和重排原始证据，程序恢复逐字原文；Jev 不拥有删除、授权或事实写入权。

小型 smoke 中，下游输入可以大幅减少，但计入 Jev 后完整路径成本没有同步下降。因此本仓库不把 token reduction 直接等同于系统更便宜。

### Jev as an LLM prior

把 Jev direct label 或 semantic signals 交给下游强模型，没有在当前 authored hard/dev 上证明质量收益，反而增加总成本/推理量。

旧 wrong_direct stressor 还存在已记录的方法学污染：payload 明示 synthetic_known_wrong，因此不能解释为“模型能抵抗未标记错误先验”。

### Ordinary unpaired project history

两个 tiny coding-continuation 任务没有 tool-pair closure 兜底。jev_window 两题都保留了足够证据并选中通过本地隐藏行为测试的 patch；但样本只有两题，完整路径成本高于 full history。

结果：docs/results/CODING_CONTINUATION_35699848204.md

### Window/cache economics

固定三窗口轨迹比较 append-only、每轮重组、规则窗口和 Jev 窗口。relay 报告非零 cached_input_tokens；当前 Jev 窗口方案没有表现出经济或质量优势。

结果：docs/results/WINDOW_CACHE_35700455133.md

## 当前架构观点

如果未来重新打开这条路线，目标不是自研另一套通用 memory/context platform，而是一层很薄、可替换的 semantic policy：

~~~text
vendor-native history / context manager
        ↓
deterministic project state + provenance
        ↓
optional semantic router
        ↓
main model
        ↓
deterministic safety / approval gates
~~~

Jev 只是 semantic-router 的一个候选后端。未来应与 deterministic retrieval、embedding、小型本地模型和厂商原生能力做同协议对照。

## 快速开始

需要 Python 3.11+。核心离线测试只使用标准库：

~~~bash
python -m unittest discover -s tests -v
~~~

早期离线 smoke：

~~~bash
python jev_lab.py dataset --out data/smoke.jsonl
python jev_lab.py run --data data/smoke.jsonl --config config/rules.json --out runs/rules-01 --limit 90
python jev_lab.py run --data data/smoke.jsonl --config config/jev.json --out runs/jev-dry-01 --limit 90
~~~

默认 dry-run 不联网、不收费，也不会伪造模型答案。

较新的实验入口：
- curator/ — context policy / retrieval
- evidence_lab/ — evidence-first 与 fixed-input retrieval
- window_lab/ — window/cache economics 与 coding continuation
- assist/ — Jev prior / downstream-assist

## 真实 API 调用

真实调用必须显式授权。不要把 API key 写入配置、提交到仓库、issue、PR 或聊天截图。

GitHub Actions 中的付费 workflow 都是手动 workflow_dispatch；普通 push 只运行离线验证。仓库中的价格都是实验时的冻结快照，不是供应商当前报价或账单承诺。

## 证据边界

请不要把本仓库数字解释成产品 benchmark 排名：

- 多数任务为作者构造的 synthetic fixtures；
- 中文/英文/mixed 变体不是独立样本；
- 多个 smoke 样本量很小；
- 一些 relay 的真实 upstream revision 无法独立验证；
- A2Agent cache 字段不是 Codex/OpenAI KV-cache 测量；
- 成本按冻结价格估算，不等于供应商账单；
- 负结果和实验设计缺陷被有意保留。

研究目标是可证伪地回答“这个组件是否值得进入系统”，而不是证明某个模型必须有用。

## 阅读顺序

1. docs/JEV_FREEZE_DECISION_2026-09-22.md — 当前最终决策
2. docs/PHASE_REVIEW_2026-09-22.md — 冻结前阶段复盘
3. docs/results/ — 冻结实验结果
4. EVIDENCE_LAB.md — evidence-first 结构与边界
5. CONTEXT_CURATOR.md — context curator 早期设计
6. docs/SOURCES.md — 资料来源与证据边界

## 安全与隐私

- fixtures 为 synthetic data；不要把真实客户代码、凭证或个人数据直接放入公开复现实验。
- paid workflows 不自动运行。
- artifact 扫描不是完整 secret-scanning 产品。
- 安全问题请按 SECURITY.md 处理，不要公开贴出凭证。

## 贡献

欢迎可复现 benchmark、更强 deterministic/embedding baseline、长任务与缓存方法学改进、实验审计，以及 System-One-compatible backend 适配。请先阅读 CONTRIBUTING.md。

## License

MIT. See LICENSE.
