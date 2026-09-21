# 新入口：Jev evidence-first v0.6

v0.5 的 smoke 与 retrieval128 原始结果已经冻结在 `docs/results/`。v0.6 不修改旧结果；它只修复 retrieval128/dev 暴露出的一个结构性问题：**状态记录所在分片看不到“当前revision/scope绑定”，因此会把同对象的旧revision误判为更相关。**

## v0.6 检索结构

128条档案现在按最多64条/24,000字节分片。每个案例执行：

1. 所有分片先找“当前对象/revision/scope/identity绑定”；
2. 每片固定贡献少量anchor候选，统一重排后保留2个anchor并恢复pair/dependency；
3. 将同一anchor原文上下文带入每个分片，再评分状态、反证等补充证据；
4. 候选统一重排，最后按7,800字节预算恢复逐字原文与依赖闭包；
5. rules/BM25基线不变。

问题模板已缩短，避免在每个block重复长说明。128条时每案例预计6次Jev检索；e2e另加1次proposal。256条时预计10次Jev检索。gold仍只在评测端，anchor/evidence选择不读取gold。

## 为什么没有直接跑 e2e128

v0.5 retrieval128/dev 的最终证据包是17/18完整。唯一失败 `release-positive-en-128-s601` 中，当前绑定在一个分片，真正当前状态在另一个分片；状态分片看不到绑定，因此旧revision状态占据Top-4，当前状态只排第7。zh/mixed同模式也只排第6/第8，只是pair closure偶然救回。

因此先修检索再花144次Flash更合理。dev允许调协议；calibration/test仍保持未见。

## 下一次只跑精确失败case

GitHub → Actions → **Jev evidence-first v0.6**：

|字段|值|
|---|---|
|stage|`retrieval128`|
|split|`dev`|
|confirm_jev_paid|勾选|
|confirm_llm_paid|不勾|
|case_id|`release-positive-en-128-s601`|
|resume_run|留空|

这轮最多6次Jev、0次Flash。若anchor binding与最终必要证据都恢复，再跑完整 `retrieval128/dev`（108次Jev）；完整dev通过后才进入 `e2e128/dev`。

旧v0.5 artifact不能作为v0.6 resume来源：版本、请求和协议hash不同，这是故意的。

## 产物

artifact前缀改为 `jev-evidence-v06-`。retrieval-only报告现在直接显示anchor命中、conditioned局部存活、最终必要证据完整率、rules完整率与语言拆分，不再输出空的arm表。

Secret仍只使用已有的 `TYPESAFE_API_KEY` 和 `A2AGENT_API_KEY`；retrieval阶段不会读取或调用下游LLM key。没有自动付费运行，也没有接入主coding系统。
