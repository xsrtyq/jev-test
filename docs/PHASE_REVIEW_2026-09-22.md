# Jev / System One 阶段复盘 — 2026-09-22

## 阶段结论

当前证据支持把 Jev 定位为 **实验性的语义证据路由层（semantic evidence router）**，而不是默认上下文压缩器、不可逆删除器，或强 LLM 的无条件先验。

### 已支持
- 64-block authored semantic retrieval：dev/calibration/test 合计 36/36 Top-1；传统 Top-16 预筛仅 16/36。
- evidence-first smoke：Jev 原文包使下游输入约减少 85%，3/3 grounded completion；但计入 Jev 后完整路径费用比 Raw 高约 35%–41%。
- v0.5 retrieval128/dev：最终必要证据完整 17/18；发现跨分片关系缺失，而不是字节预算不足。
- v0.6 精确回归 run 35691628270：已知失败 case 修复成功。anchor binding、conditioned survival、final evidence 都为 1.0；最终包 3324 bytes；6 Jev calls / 55,943 input tokens / $0.002349606（冻结价估算）。

### 不支持 / 暂停
- unconditional Jev direct prior：hard/dev Raw 24/24、direct 24/24，无准确率增益，生产式估算成本约 +41%。
- multi-signal prior：21/24 effective success，2 caps、1 paired harm；暂停。
- aggressive lexical/structured prefilter：在旧 hard retrieval 中显著漏召回；不能作为删除权威。
- “压缩 token = 省总成本/更快”：社区与本地实验均未稳定复现。
- relevance-based irreversible deletion：不安全；历史不可复现工具结果必须保留可检索原件。

## 社区证据对当前设计的影响

1. fast-jev-compaction issue #25 的复现表明 relevance != reproducibility：极高压缩率仍可能永久丢失历史计算结果。因此保留 immutable archive、tool call/result closure、不可复现结果保护是硬要求。
2. jcressler/fast-jev-compaction-codex 的受控 paired 测试中 native/local 12/12，而 Jev rerank 8/12；后续 held-out 中 Jev exact facts 18/24 > native 14/24，但完整通过都只有 4/8，且没有减少 recovery calls。不能把 Jev 设为默认。
3. 同项目 long-task 单例中 Jev 与 native 都 100/100，reported native input 334,840 vs 723,808，但 Jev 运行约慢 18 秒；说明减少模型输入可以成立，但不自动推导为成本/延迟优势。
4. fast-jev-compaction 当前社区问题集中在 question wording、threshold scale、tool-result preview、request fitting、timeouts/cancellation 等，说明外围协议设计会主导实际效果。
5. 已出现 System One 风格的开源/本地实现，因此内部接口继续保持 backend-neutral，不把架构锁死在 TypeSafe API。

## 当前目标架构

immutable raw archive
→ deterministic provenance / PINNED constraints / tool-pair closure
→ structured anchors when available
→ Jev semantic evidence routing for ambiguous/unstructured history
→ extractive verbatim packet
→ downstream LLM reasoning
→ deterministic safety/permission policy and human approval

Jev 没有删除权、授权权或事实写入权。概率只用于排序。

## 下一阶段 gates

### A. v0.6 retrieval correctness
1. 运行完整 retrieval128/dev（108 Jev，0 LLM）。
2. Gate：18/18 final all-required evidence；任何 miss 都先停止 e2e。
3. dev 通过后冻结协议，运行 retrieval128/calibration，不再按 calibration outcome 调 prompt/threshold。
4. calibration 通过才跑 untouched test。
5. 128 held-out 成立后再扩大 256；不是先扩大再补正确性。

### B. retrieval economics
同时记录：Jev input、request count、wall time、packet bytes；目标不是最小 packet，而是在零决定性证据遗漏下减少重复 state 成本。

生产设计优先尝试：
- repo/branch/commit/file/tool-pair/permission revision 等结构化 anchor 由程序维护；
- Jev 只处理无法由 metadata 确定的语义关系；
- 缓存 query-stable anchor，避免每个下游 turn 重做全 archive anchor pass；
- 不用词项相似度做不可逆 candidate deletion。

### C. e2e128
只有 retrieval gate 通过后再跑。现有四臂 raw/rules/evidence/proposal 主要测 grounded completion、成本、reasoning 与延迟，不再期待简单 authored join 证明准确率提升。

若 Raw 再次 ceiling，停止扩大这个任务集，转入 coding-continuation benchmark。

### D. coding continuation benchmark
构造接近真实 Codex 的长任务：文件修改、旧 revision、失败路径、不可复现 tool output、权限变化、后续事实追问和隐藏验收测试。比较：
- native context/compaction
- deterministic archive recovery
- Jev evidence router

主要指标：最终任务通过、历史事实恢复、recovery calls、raw/cached/non-cached input、wall clock、Jev cost。任何 token 优势必须与 downstream task success 同时成立。

### E. Codex shadow integration
在主 coding 系统之前只做 shadow：
- Jev 生成 would-select packet；
- 不改变 Codex 实际可见上下文；
- 记录 would've-kept / would've-missed；
- 对真实会话离线重放。

只有满足 no-regression 且有明确效率收益后，才考虑受控 A/B；不直接替换 native compaction。

## 当前阶段判定

研究从“Jev 是否神奇地压缩上下文/给 LLM 提示”推进到了一个更窄、可证伪的工程问题：

> Jev 是否能在 immutable archive + deterministic provenance 的约束下，成为低成本、高召回的语义证据路由器，并最终改善长任务的质量/资源前沿？

这是下一阶段唯一需要继续验证的主假设。
