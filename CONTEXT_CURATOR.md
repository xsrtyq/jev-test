# Jev Context Curator v0.2

**新入口：Actions → Jev context curator。** 旧的 `Jev live smoke` 继续保留，不会自动改动或启动任何付费实验。

这次从“单条文本分类”升级成“多块证据、固定上下文预算、依赖保留和检索恢复”的独立实验。没有修改主 coding 系统，没有内置模型权重，也不需要你的电脑装Python或GPU。

先阅读 `docs/EVIDENCE.md`（核实到什么），再读 `docs/NEXT_PLAN.md`（完整下一阶段计划）与 `docs/CONTEXT_RUN.md`（如何运行）。测试范围/尚未验证事项见 `docs/CONTEXT_VALIDATION.md`。

当前状态：已实现，离线验证；**v0.2 的真实 Jev 结果尚未运行**。之前360次调用属于v0.1，不能移用为新实验分数。

## 首轮建议

Actions → Jev context curator → Run workflow：main、suite=quick、split=dev、steps=20、question_language=auto。先不勾付费可做全流程dry-run；勾选后最多18次真实Jev请求，模型费估计预算$0.25。仍用现有 `TYPESAFE_API_KEY` repository secret，不需要再贴密钥。

六组实验：quick / quality / robustness / scaling / fanout / replay。分步决定是否继续，不一口气跑完整笛卡尔积。

## 本机命令（可选，不要求你有本地环境）

```bash
python -m unittest discover -s tests -v
python -m curator plan --suite quick --out plan-v02.json
python -m curator run --frozen-plan plan-v02.json --out runs/context-dry
# 真正调用前，在本机安全设置 TYPESAFE_API_KEY；不要提交密钥。
python -m curator run --frozen-plan plan-v02.json --out runs/context-live --allow-paid
python -m curator run --suite replay --steps 20 --out runs/replay-dry
python -m curator cache --out runs/cache-assumptions.json
```

没有pip依赖，只用Python3.11+标准库。输出目录必须全新。

## 判定原则

必须先看：关键证据/精确原文召回、过期状态、候选遗漏、孤立叙述、预算阻断、检索后是否真的拿到所需信息。之后看序列化字节和费用。PINNED由程序保护，不把它算成Jev准确率；保留指针不等于取回成功；字节压缩不等于token节省；fixture证据覆盖不等于长coding任务成功率。

v0.2只有API接线、静态/序列证据实验和程序策略，不是可安装到Codex/Claude的上下文插件。云端小LLM适配器是可选对照，需要独立模型与费用配置；真实下游LLM任务闭环、本地神经网络、服务端KV/prompt cache测量均未完成，不能声称已优化你的订阅用量。

## 2026-09-21 更新

真实 quick、retrieval/dev、retrieval/calibration 已经运行。原版“历史路径检索”被证明对修正后的 structured matcher 过于容易，因此没有继续跑原 retrieval/test。

新增 suite：retrieval_hard。它使用 64-block archive、近似语义干扰和“为什么做出某决定”类 query，只把 deterministic top16 候选送给 Jev rerank，以测试 Jev 是否在规则/词项检索之外提供真正的语义增量。

同时增加了完全独立的 Jev → LLM decision-assist benchmark；入口与说明见 docs/DECISION_ASSIST.md。两条实验线分别证明价值后，才考虑组合进主 coding workflow。

