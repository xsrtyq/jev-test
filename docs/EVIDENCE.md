# 证据台账：2026-09-21 核对

## 自己的真实API实验（已重新读取原始ZIP）

代码commit：`a75039b887a99ee6f1bb964ce3bfc561879669cd`。机器可复核摘要见 `evidence/verified-v01.json`；`python -m curator.audit <base.zip> <reverse.zip> <injection.zip> <distractor.zip> --out audit.json` 可重新计算。

|条件|运行号|正确/总数|pmax≥0.9错误/样本|模型费估算美元|
|---|---|---:|---:|---:|
|base|35569448936|87/90|0/78|0.001798986|
|reverse_options|35569813913|84/90|0/80|0.001798986|
|injection|35569897023|88/90|0/75|0.001931286|
|distractor|35569965540|88/90|0/77|0.009699186|

合计347/360、310个高pmax关联观测中0错，总费用估算$0.015228444。只包含四个90条运行，不包含最初30条smoke。每种语言：中文115/120、英文116/120、混合116/120。仅30个原始案例、翻译/扰动强相关，作者拟定标签，不得当作360个独立样本。

case-028-zh（当前禁止数据库操作，旧迁移许可已撤回）在base和reverse_options被判为irrelevant。低概率保守策略可以在这次挡住它，但不能证明未来没有高概率错误。

旧实验 ZIP SHA256：

- base: `a5382d221606760422c077c987249e83f8e70ea8d3434507a3955bd73430d57f`
- reverse_options: `d4781ed4e772ca019c432e7cd354961c1d12733a12b529a217c2e2048b86ff16`
- injection: `6c65f9633f85af461dda99fc16214135f9e484bfa8751ec23ab216cbe3d7ec94`
- distractor: `e0769b860235be05d55891ac7979ffc5ed27818a676ba4e05cc9c11a6444d57d`

原始来源：`https://github.com/xsrtyq/jev-test/actions/runs/<运行号>`。结果包由用户先前手动授权运行生成；本次审计未再调用模型。

## 直接核对的外部原始来源

**S1 / 官方模型与API协议（产品事实，不是独立效果证据）**

`https://docs.typesafe.ai/models`
`https://docs.typesafe.ai/api`
`https://docs.typesafe.ai/model-jaggedness/jev-1.13`

当前 `jev-1.13.0`，输入$0.042/M，输出免费；32k state+最长question、64k总请求。英语为主要训练语言；多语言不保证等效。官方自己承认长state无关材料、否定、对抗内容及跨primitive不一致。API问题键不参与推理，指向block的含义必须写进instructions。没有据此猜测参数量或“无KV架构”。

**S2 / 负面对照：Codex 恢复包重排**

`https://github.com/jcressler/fast-jev-compaction-codex/blob/main/benchmarks/PAIRED-RESULTS-2026-09-18.md`

作者报告6个合成案例、每个2次continuation；native与enhanced local为12/12，Jev和equal-score为8/12。20候选、1800字符包、同一压缩base、固定生成模型、交错执行；仅6次Jev排名请求。三个模板，两次continuation不独立。失败有候选召回和短视图因素；不测试自动PreCompact。模型账单成本unknown。支持新增候选召回、证据可见度、equal-score与后续质量对照，不支持宣告所有Jev上下文方案失败。

**S3 / 一线失败报告：留下叙述，删掉工具证据**

`https://github.com/tamaratran/fast-jev-compaction/issues/65`

2026-09-20，一位作者报告一个两天会话的第三次压缩后，接连9条无tool调用的完成报告；原文工具调用被删除，而助手叙述仍留下。不是随机对照、不是已独立复现的因果关系。支持测试claim→evidence与call/result结构，不能用作Jev模型本身失败率。

**S4 / 多轮累积报告**

`https://github.com/tamaratran/fast-jev-compaction/issues/70`

报告两段真实会话九轮压缩，候选集覆盖不了累积内容，低压缩率可能被误当作模型失败。用作多轮候选覆盖/预算增长的故障假设，不作已证明普遍规律。

**S5 / 有公开日志的分类评测**

`https://jevals.com/choice/`
`https://jevals.com/methodology/`

Banking77 300个人工标注数据集项目×5次；作者报告Jev79.7%准确率、同输入重跑2.7%翻转、换序10.3%。LLM是口述概率、prompt-only JSON，不是严格结构化紧凑标签，不能拿其价格/速度倍率作为公平小LLM结论。Jev经Gateway、实际底层版本不返回，不能视作与直连固定版本完全同条件。学习其重复和换序控制，而不是复用阈值。

**S6 / 正面但很小的审计任务实验**

`https://github.com/BorisLeMeec/jev/blob/main/bench/tokenecon/TOKENS_ASK.md`

三个语义审计，平均进入上下文token下降70%、计费token下降38%；一个任务的召回从1.00降至0.80。作者明确提示漏报比误报危险。不是“所有任务质量不变”，不外推长期任务或中文。

**S7 / 原生prompt cache**

`https://developers.openai.com/api/docs/guides/prompt-caching`

缓存依赖匹配前缀；v0.2仅记录序列化字节前缀和假设价格算式，没有第二个模型的cache usage，不报告KV显存收益或Codex额度下降。

## 不纳入本轮硬结论的内容

未重新拿到完整原始数据的旧聊天百分比；聚合站转述“永不丢关键上下文”；只有压缩前后长度没有任务结果的演示；几十次同题重复冒充几十个独立任务；用Jev自己打分证明Jev更好。均不作为接入依据。

以上仅是截至核对时读到的证据，不声称穷尽全社区，也不把作者尚未证实的原因假说当成事实。
