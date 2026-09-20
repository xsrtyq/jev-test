# Jev Test — 中文优先的独立决策实验

**状态：v0.1 可运行的离线实验台；真实 Jev/LLM API、社区本地模型与长任务闭环尚未实测。**

本项目不是 Jev 推广演示，也不接入任何生产工作流。目标是验证三个问题：Jev 是否优于配置合理的小型 LLM；中文是否出现明显退化；高置信错误是否会导致长任务偏航。得到“不适合接入”的结论同样成功。

不修改 Coding Workflow Suite、InvoiceFlow、全局 AGENTS.md、skills、MCP、Codex/Claude 配置或任何权限/签名/验收链。所有结果都是 `record_only`；模型不能执行工具、删除上下文或授权重试/发布。不会自动下载模型、购买服务、训练模型或启动云资源。

## 1. 先免费跑通

在仓库根目录，使用 Python 3.11+（仅标准库，无 pip 依赖）：

```powershell
python -m unittest discover -s tests -v
python jev_lab.py dataset --out data/smoke.jsonl
python jev_lab.py run --data data/smoke.jsonl --config config/rules.json --out runs/rules-01 --limit 90
python jev_lab.py run --data data/smoke.jsonl --config config/jev.json --out runs/jev-dry-01 --limit 90
```

最后一条是 dry-run，不联网、不收费，报告不会伪造准确率或模型回答。输出路径必须是新的；重复运行请换 `-02` 等名字，不覆盖历史结果。

`data/smoke.jsonl` 由代码确定性生成：**30 个原始案例 × 中文/英文/混合三种条件 = 90 条记录，不是 90 个独立案例**。默认 `--limit 30` 取前 10 个案例的三种语言；`--limit 90` 才覆盖全部三类任务。所有标签均为作者拟定、尚未人工复核的冒烟标签，不能用于证明生产可靠性。

## 2. 真正调用 Jev（需要自己的 API 资格和密钥）

当前适配器按官方文档实现 `POST /v1/systemone`，固定 `jev-1.13.0`；v0.1 只使用 `choice` 问题。不要把密钥发进聊天或提交到仓库。

Windows PowerShell 中可隐藏输入：

```powershell
$secret = Read-Host "TypeSafe API key" -AsSecureString
$env:TYPESAFE_API_KEY = [System.Net.NetworkCredential]::new("", $secret).Password
python jev_lab.py run --data data/smoke.jsonl --config config/jev.json --out runs/jev-live-01 --limit 30 --allow-network --allow-paid
Remove-Item Env:TYPESAFE_API_KEY
```

这才会发生付费请求。先检查供应商控制台的价格、可用模型和预算；确认冒烟结果后再用新目录跑完整 90 条。缺少密钥、网络许可或付费许可时不会调用。任何后端错误或缺失 usage 都停止该后端的后续请求，不自动重试。

`config/jev.json` 的每次运行建议预算为 $1、每次请求预留 $0.005，输入价快照 $0.042/百万 token、输出价 $0。它是应用内的保守保护，**不是绝对账单上限**：价格/计量可能变化，未知计费保留预留额，新运行会重置本地账本。正式费用查供应商账单。输出免费也可能返回非零 output_tokens。

## 3. 公平的小型 LLM 对照

复制 `config/llm.example.json` 为 `config/llm.local.json`，填入你实际可访问的小型模型的固定版本、当前输入/输出/缓存价格、核对日期。示例占位符和空价格会被拒绝；程序不猜模型名，不借用 ChatGPT 订阅额度。

```powershell
Copy-Item config/llm.example.json config/llm.local.json
# 编辑本地配置；在本机设置 OPENAI_API_KEY，不写进配置。
python jev_lab.py run --data data/smoke.jsonl --config config/llm.local.json --out runs/llm-live-01 --limit 90 --allow-network --allow-paid
python jev_lab.py compare runs/llm-live-01/results.jsonl runs/jev-live-90/results.jsonl --out runs/comparison.json
```

比较前两次运行必须具有完全相同的案例集合及输入；上例 Jev 也必须另外跑出 `jev-live-90` 的 90 条记录。缺题、dry-run、被阻止的运行不能拿来比较。输出差值为 **右侧减左侧**。

LLM 只输出紧凑标签，不写解释、不生成完整概率表；同一状态的所有问题放在一次调用。默认使用严格 JSON Schema；仅当所选兼容服务确实不支持时，显式设置 `response_format: "json_object"`，不静默降级。`max_tokens_field` 可显式选 `max_tokens`，默认是 `max_completion_tokens`。推理档位和温度只在该模型支持且配置明确时发送。

LLM 标签没有原生概率时，概率统计是 unknown，不编造“confidence=1”。Jev 的 provider confidence 与最高类别概率 pmax 分别保存，两者都不直接等于正确率。

## 4. 中文与鲁棒性实验

```powershell
python jev_lab.py dataset --out data/questions-en.jsonl --question-language en
python jev_lab.py dataset --out data/reversed.jsonl --variant reverse_options
python jev_lab.py dataset --out data/injected.jsonl --variant injection
python jev_lab.py dataset --out data/distractor.jsonl --variant distractor
```

`--question-language en` 只改变固定问题模板，不翻译状态或要求用户改用英文。其他变体分别测试选项换序、不可信文本的提示注入、无关长材料。先审查样本，只有基础质量值得继续时再执行真实调用，避免全组合消耗。

变体比较必须显式加 `--perturbation`，否则拒绝不同输入的对照：

```powershell
python jev_lab.py compare runs/base/results.jsonl runs/reversed/results.jsonl --out runs/order-comparison.json --perturbation
```

报告逐语言质量、翻转率和按原始案例分组的探索性 bootstrap 区间。译文/改写不能当成额外独立样本；混合文本长度也不同，不能拿原始耗时直接证明语言造成的推理差异。

## 5. 长链故障累积：只演示假设，不冒充 Jev 成绩

```powershell
python jev_lab.py simulate --steps 100 --episodes 2000 --error-rate 0.01 --detection-rate 0.9 --out runs/fault-assumptions.json
```

这是独立错误的数学模拟，假设每个未检出的错误都致命、检出的错误获得完美恢复。报告明确标为 `SYNTHETIC_FAULT_SIMULATION_NOT_JEV_BENCHMARK`。真实错误可能相关，验证器和回退模型也会失败。它**不是** Jev 的实测错误率、100 步任务成功率、已实现的自动恢复工作流。

## 6. 本地模型：仅提供可选协议适配器

`config/local.example.json` 指向已由你另行运行的、兼容 System One 响应格式的回环 HTTP 服务。复制为 `config/local.local.json`，填写实际模型及 revision；只有 `--allow-network` 才连接本机服务。也支持 `kind: "llm_local"` 的本机 Chat Completions 兼容端点。

**本仓库不包含 Jev 权重、不内置 systemone-lite/decider 推理引擎、不下载或安装它们。** 社区项目的真实响应兼容性和本机 RAM/VRAM 要在另一步验证。服务只允许 localhost/127.0.0.1/::1；不会向本地服务传云端密钥。先完成云端质量对照，再决定是否值得维护本地环境。

## 7. 产物与阅读顺序

每次 `run` 生成 `manifest.json`、`results.jsonl`、`summary.json`、`report.md`、`failures.jsonl`。Manifest 保存数据/代码/输入 hash、实际运行环境、模型配置及价格快照；实际响应模型单列。日志不保存密钥、原始状态或服务端异常正文，但标签和结果仍可能敏感，`runs/` 默认忽略，不应随意上传。

重点看：全部请求口径准确率、仅返回标签口径准确率、按语言/任务指标、关键案例错误/未决、高 pmax 桶中的实际误判、Brier、概率分桶、回退阈值的风险-覆盖关系、p50/p95、未知用量。0.9/0.95 仅是诊断阈值，**不是生产执行门槛**。

`docs/EXPERIMENT.md`：如何判断继续还是停止。`docs/VALIDATION.md`：本次真实执行过哪些测试。`docs/SOURCES.md`：官方文档与证据边界。

第一版没有完成 300 例冻结测试、人工标注审核、正式阈值校准、真实闭环任务、同权重生成/读出消融、GPU 实测、强制总墙钟 deadline 或跨运行预算账本。HTTP 超时是 socket timeout；不宣称完整生产级超时控制。也不会减少当前 Codex 的订阅用量。
