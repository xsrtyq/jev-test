# 在 GitHub 上运行 Jev：不需要本地 GPU 或本地 Python

状态：已提供手动云端执行入口。是否已有真实模型结果，以对应 Actions 运行的 results.jsonl / summary.json 为准。代码通过测试不等于模型通过 benchmark。

## 一次性设置

在本仓库的 Settings → Secrets and variables → Actions → New repository secret 创建：

- Name：`TYPESAFE_API_KEY`
- Secret：在 TypeSafe 控制台生成的 API key。

不要把 key 写入代码、workflow 输入框、Issue、聊天或提交记录。已经发到聊天的 key 建议撤销，使用新 key。撤销应在 TypeSafe 控制台进行，仅删除聊天或 GitHub Secret 不能使原 key 失效。

## 第一次真实运行

进入 Actions → **Jev live smoke** → Run workflow，选择 `main`。

1. 核对 TypeSafe 当前可用的 `jev-1.13.0` 和价格，再勾选 `confirm_paid`。
2. 保持 `case_count=30`、`variant=base`、`question_language=auto`。
3. 点击 Run workflow。未勾选 `confirm_paid` 就只做 dry-run，不调用 Jev。

30 条记录来自 10 个原始案例的中文、英文、混合版本，覆盖模块路由、错误分类、上下文相关性；不是 30 个独立案例。90 条才是全部 30 个原始案例。样本标签仍为人工编写但尚未独立人工复核的 smoke 标签。

流程是手动触发，不因 push/PR/定时任务自动消费模型额度。GitHub connector 当前可读取日志和产物，但没有创建 Secrets 或 dispatch workflow 的可用动作，因此这两次网页操作由账户持有者完成。

## 限额与失败行为

最多 9/30/90 次请求，单次运行模型预算估算 $0.25，单请求预留 $0.005，socket 超时 15 秒，job 上限 15 分钟，串行发送，不自动重试。API、解析或用量计量异常后停止后续请求。中断的请求是否计费须查供应商账单。

预算使用仓库 `config/jev.json` 的历史价格快照，不承诺绝对账单上限。每次手动重跑都会重新计算预算；不要反复盲点。GitHub Actions 的执行时长也可能有独立计费，取决于你的账户额度。

密钥仅在显式授权的执行和产物检查步骤作为环境变量提供；checkout 不保留 GitHub 凭据。产物上传前检查原始 key 和 `apikey_` 模式，发现则阻止上传；这不是对所有变形/编码泄露的万能检测。

## 查看结果

运行结束后看 Summary，下载 `jev-smoke-<run_id>-<attempt>` artifact。含：

- `plan.json`：选了哪些语言/任务分组、预算与源 commit。
- `cases.jsonl`：合成测试输入及外置参考标签。
- `config.json`：无密钥配置。
- `jev/manifest.json`：输入 hash、配置、运行环境。
- `jev/results.jsonl`、`summary.json`、`report.md`、`failures.jsonl`：真实调用结果或明确的 dry/blocked/error 状态。

产物保留 7 天，不自动提交进 git。这里不涉及真实客户数据、主工作流权限、删除、发布或生产操作。模型输出只记录。

## 解释边界

本阶段可以观察中文/英文/混合样本质量、高 pmax 错误与静态上下文相关性。改写、换序或提示注入变体需要分别手动运行。

本阶段尚未实现：真实长任务闭环、完整上下文整理器、正式概率校准、Choice/Noul/Score 全面对比、fan-out 对照、本地模型或小型 LLM 实测。不能根据这轮推断完整任务成功率、长任务节省 token 或 KV/prompt cache 实测收益。

## 本次准备时的环境记录

ChatGPT 容器访问 TypeSafe 官方文档时发生 DNS 解析失败。未向模型接口发送带凭据的请求，也未在容器/仓库保存用户给出的 key。GitHub 文件连接可用，因此提供上述云端入口；这份准备记录不是模型 benchmark。
