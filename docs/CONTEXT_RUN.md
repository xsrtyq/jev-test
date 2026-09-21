# 云端运行指南

## 已有的设置继续用

仓库：`xsrtyq/jev-test`。Repository Secret：`TYPESAFE_API_KEY`。不要把密钥填进任何workflow输入、代码或结果文件。

这次请选择新的 **Jev context curator**，不是旧的 Jev live smoke。

## 第一轮

`Actions → Jev context curator → Run workflow`：

|字段|值|
|---|---|
|Branch|main|
|Authorize paid Jev requests|先不勾=免费模型dry-run；勾选=真实API调用|
|suite|quick|
|split|dev|
|steps|20（quick中不生效，只供replay）|
|question_language|auto|

第一次真实quick最多18请求：2个主题场景×3种语言×Choice/signals/Score。每次请求会并行问多个block问题，不能与旧smoke“1请求1题”按调用数直接比费用。

模型费保护：当前官方输入价$0.042/M、输出免费，每次手动运行估计上限$0.25，至多240请求。不是发票绝对上限。重复手动运行会重置本地账本；GitHub Actions算力可能另有费用。程序遇API/计量异常会停，不自动重试。

## 跑完看什么

绿色success只表示程序完成，不表示保留质量合格。打开Summary，再看同页artifact `jev-context-<suite>-<run_id>-<attempt>`。有：

- plan.json：完整样本、留出分组、种子、顺序、最高请求数；含外置gold但不发送给模型。
- config.json / manifest.json：无密钥配置、代码/输入hash、commit、运行环境。
- results.jsonl：模型请求和结构化回答、全部程序baseline、选中原文块、错误及恢复。
- summary.json / report.md：按语言/形式的证据召回、失败、预算阻断、字节收益、费用、延迟与限制。
- failures.jsonl：未保留完整证据或超预算/错误的记录；回放逐检查点失败在results.jsonl。
- ledger.json：本次真实请求数、预留/估计费用与停止原因。

Artifacts保留14天。仅合成数据，不含你的项目文件、聊天记录或API key。

## 再下一轮怎样选

修正版quick后先跑 `retrieval/dev`。这一组把“后续目标已归档”固定下来，隔离比较 lexical top4、带路径/编号锚点的 structured top4、以及 Jev Noul 语义检索 top1/top4。只有恢复层至少有一条可靠路径后，再扩大到 `quality/dev`，之后才跑 `robustness/dev`。

`scaling`增加背景噪声字节，并改变关键证据首/尾位置。标签是字节档位，最终按API usage报告实际token，不能说“16k token”除非实测支持。

`fanout`对同一问题集合比较每次1/4/13问题，重复两次，不把吞吐当单请求延迟。`replay`选择10、20或50环境步，每5步及查询变化时评估，不是任意生产agent循环。

调模板只用dev。固定方案后再跑calibration、test；不为得到胜利结论反复查看test并修改模板。当前标签仍待独立人工复核。

## 可选云端小LLM

不需要本地模型，但需要另一个有效的云端API及预算。复制 `config/context-llm.example.json` 到一个本地配置，填实际可用模型和核实价格。当前支持官方OpenAI Chat Completions严格JSON Schema，不自动选模型、不自动降低格式要求。

```bash
python -m curator plan --backend llm --suite quick --out plan-llm.json
python -m curator run --frozen-plan plan-llm.json --config config/context-llm.local.json --out runs/llm --allow-paid
```

只做Choice紧凑标签对照，不让LLM写长解释或伪概率。模型不同导致的usage、缓存、网络差异需独立记账。此对照暂不提供带密钥的Actions入口，避免意外调用额外付费服务。

## 明确的限制

没有自动派发、后台持续付费、自动集成或部署。Socket timeout不是每个请求的严格总墙钟上限；程序在请求前检查总deadline，Actions另有job硬上限。API客户端只有一层、零自动重试。缺少密钥或异常后，可查看部分记录，不要盲目连点重跑。

## 当前下一步（2026-09-21）

retrieval/dev 已完成，不要因该 run 的红色 UI 再付费重跑；红色来自结果写完后的 failures artifact bug，模型数据完整。修复后离线 CI 已通过。

下一次请选择：
- suite = retrieval
- split = calibration
- steps = 20（retrieval 不使用）
- question_language = auto
- paid = 勾选

这是不同的4个主题族，用来检查 dev 的 Jev top-1 12/12 是否能泛化。不要先跑 test；如果 calibration 暴露问题，只允许在 dev/calibration 范围分析和改进，然后重建新的未见 test 版本。若 calibration 仍强，再冻结一次并运行 retrieval/test。

## 当前下一步（retrieval calibration 之后）

旧的 retrieval/dev + calibration 已经说明：明显的路径/ID 查询可以被正确的 deterministic structured 检索解决，因此原 retrieval/test 暂停，不再为它花额度。

新的 harder benchmark 已实现为 suite = retrieval_hard：

- 每个场景 64 个 archive blocks；
- 大量近似主题、错误理由、其他 path/ID 干扰；
- query 问“为什么拒绝某方案 / 为什么做出这个决定”，不是直接问某个历史路径；
- deterministic hybrid 先取 top16 候选；
- Jev 只在这 16 条上做语义 rerank；
- 分开统计 candidate16 recall、deterministic top4、Jev top1/top4。

下一次 Context Curator 方向应先跑 retrieval_hard / dev / auto。不要跑旧 retrieval/test。

另外，Jev → LLM 的决策辅助已经拆成独立 workflow；见 docs/DECISION_ASSIST.md。它不属于 Context Curator 指标，也不会用 retrieval 结果替代。

