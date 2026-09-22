# Jev 最后验证阶段：运行顺序与停止条件

日期：2026-09-22。

这一阶段只回答一个工程问题：**在厂商逐步提供 history/new_context/memory 的前提下，我们的薄语义层是否仍能带来可重复的净收益。**

不接入主 coding 系统，不自动付费，不继续扩展为独立 context platform。

## 已实现

1. 数据版本与代码版本分离：evidence fixture 不再因 protocol VERSION 更新而更换随机 ID。
2. 固定输入回归：同一份 v0.5 已知失败 fixture 同时比较：
   - legacy_v05：原32-block/长问题/Top-4方案；
   - short_no_anchor：64-block+短问题，但不提供跨分片 binding anchor；
   - relation_anchor_v06：两阶段 anchor-conditioned 方案。
3. Window/cache smoke：
   - append_all：整个轨迹持续追加；
   - rewrite_each：每轮重新构造词项工作集；
   - window_rules：只在窗口边界用程序检索初始化工作集，窗口内追加；
   - window_jev：只在窗口边界用 Jev 选择历史证据，窗口内追加。
   固定轨迹共3个窗口×4 turn。后续请求使用固定gold作为历史assistant响应，隔离 provider 输出分歧；记录input/cached/uncached token、列表价、字节级前缀复用。它测的是A2Agent relay报告和结构特征，不冒充Codex/OpenAI KV-cache实测。
4. Coding continuation smoke：
   - 两个合成任务：金额舍入与支付timeout重试；
   - full_history / rules_window / jev_window 三组；
   - 主模型只选择预定义 patch ID，不允许模型生成代码在CI执行；
   - 选择后由本地隐藏行为测试验证patch语义。
5. 所有真实调用仍需GitHub Actions手动勾选；无retry loop；artifact会做secret scan。

## 推荐运行顺序

### Gate 0 — 已完成：离线CI
确认 main 最新 Offline verification 为绿色。若红色，不运行任何付费实验。

### Gate 1 — 固定输入归因回归

Actions → **Jev fixed-input retrieval regression**

- confirm_jev_paid = true

最多14次Jev，0次Flash。

希望看到：
- legacy_v05 复现旧失败；
- short_no_anchor 告诉我们“仅换64-block/短问题”是否足够；
- relation_anchor_v06 必须 final all_required=true。

如果 relation_anchor_v06 仍失败：**冻结 context route，不继续调v0.7。**

### Gate 2 — simplest-sufficient retrieval128/dev

Gate 1 显示 short_no_anchor 在完全相同失败输入上也能得到完整最终证据包，并且调用/输入/费用约为 relation-anchor 的一半。因此先跑更便宜方案。

Actions → **Jev short-no-anchor retrieval gate**

- confirm_jev_paid = true

上限54次Jev，0次Flash，18个稳定dev案例。

门槛：
- 若18/18 final packet包含全部必要证据：优先保留简单方案，暂不跑完整relation-anchor；
- 若任何case遗漏最终必要证据：再运行 **Jev evidence-first v0.6** / retrieval128 / dev（108次Jev）并精确比较相同fixture；
- 不因为local recall小于1直接判失败，只要deterministic pair/dependency closure后的最终原文包完整；真实无pair历史由后续coding continuation覆盖。

任何最终miss在完成上述同输入比较前都不进入更大的下游实验。

### Gate 3 — 极小 coding continuation smoke

Actions → **Jev coding continuation smoke**

- confirm_jev_paid = true
- confirm_llm_paid = true

上限2次Jev + 6次Flash。

主要比较：
- hidden tests passed；
- full_history vs rules_window vs jev_window 的输入、reasoning、费用；
- Jev是否在减少输入时保持2/2测试通过。

如果 jev_window 出现 full_history 没有的失败：暂停，不跑cache probe。

### Gate 4 — Window/cache economics smoke

Actions → **Jev window/cache economics smoke**

- confirm_jev_paid = true
- confirm_llm_paid = true

上限2次Jev + 48次Flash；固定1条轨迹、3窗口×4turn×4策略。

主要比较：
- 12/12问题正确率；
- provider报告的 cached_input_tokens / uncached_input_tokens；
- list-rate LLM cost；
- mean byte-prefix reuse；
- Jev额外费用。

重点是 window_jev vs window_rules，而不是只拿Jev和故意糟糕的rewrite_each比较。

A2Agent的cache字段不是Codex/OpenAI缓存测量，因此这一轮只能筛选架构。若出现正面信号，下一阶段才值得接真实OpenAI/Codex计量。

## Go / Freeze

完成Gate 1–4后停止新增实验，做一次正式决策。

继续投资需要至少满足一种：
- 在质量无下降时，总成本或总时间有可重复的约20%级改善；或
- 成本增加不超过约10%，但真实continuation中的历史错误/返工显著下降。

否则冻结：
- 保留benchmark；
- 保留immutable archive/provenance和backend-neutral router接口；
- 等OpenAI/Anthropic原生context manager成熟后直接适配。

## 暂时不要运行

- retrieval128 calibration/test
- retrieval256/e2e256
- 旧decision-assist direct/signals
- 主coding系统集成

这些只有Go决策后才有理由继续。
