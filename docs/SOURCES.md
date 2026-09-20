# 一手来源与证据边界

核查日期：2026-09-20/21（跨时区会话）。对照模型、价格、API 版本运行前仍需核实。

- TypeSafe 官方发布文：https://typesafe.ai/blog/introducing-system-one-models-and-jev
  2026-09-15 发布；宣称并行 sampler、RLCD、类型化概率输出。Workflow eval 使用其他大模型的参考概率，而非普遍的人工真实标签。发布文也说明短输入演示有利于表现采样差异，地域网络会影响延迟。
- 官方构建 skill：https://github.com/typesafe-ai/skills/blob/65a39f393687675ce170e6094757de20370365b9/skills/typesafe-ai/SKILL.md
  本次通过连接器读取。明确指出：typed output 保证接口不保证事实；confidence 汇总分布集中度，不是整个工作流正确率或执行许可。问题并行且不能看到彼此答案。阈值需要在用户数据上验证。
- HTTP API：https://docs.typesafe.ai/api
- 当前模型、限额与定价：https://docs.typesafe.ai/models
- 语言和状态说明：https://docs.typesafe.ai/concepts/state
- 当前已知失败模式：https://docs.typesafe.ai/model-jaggedness/jev-1.13
- 概率与 confidence：https://docs.typesafe.ai/confidence
  这些官方文档路径在前一版计划列明；本次重新请求其中部分页面失败。适配器按既有公开 v1 contract 实现，尚未进行真实在线验收。语言准确率没有可验证的单一百分比，不把网页缺失当作模型质量结论。
- 官方 LLM 对照适配器：https://github.com/typesafe-ai/system-one-adapter-python
- 社区机制研究：https://github.com/TheoLeeCJ/SemIf
- 社区本地基线：https://github.com/fritzprix/systemone-lite
- 训练型候选：https://github.com/Mapika/decider
- OpenAI 结构化输出：https://developers.openai.com/api/docs/guides/structured-outputs

本仓库原创的 smoke 样例不是从这些项目复制的公开 benchmark，也没有宣称与其得分可比。只提供接线，不下载和执行以上社区仓库或安装全局 skill。
