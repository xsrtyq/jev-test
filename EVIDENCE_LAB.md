# 新入口：Jev evidence-first v0.5

这是独立实验，不安装到Codex，不修改主coding系统。完整计划：`docs/EVIDENCE_NEXT_PLAN.md`。旧结果核对：`evidence/audit-before-v05.json`。

## 先只跑一次 smoke

GitHub → `xsrtyq/jev-test` → Actions → **Jev evidence-first v0.5** → Run workflow。

|字段|值|
|---|---|
|Branch|main|
|stage|smoke|
|split|dev|
|confirm_jev_paid|勾选|
|confirm_llm_paid|勾选|
|case_id|留空|
|resume_run|留空|

沿用已有的 `TYPESAFE_API_KEY` 和 `A2AGENT_API_KEY`，不需要再贴key或购买新的API。

这一轮最多 **18次Jev + 12次A2Agent Flash**，覆盖三条案例。绿色只表示计划完整记录，不表示模型质量过关。两项付费都不勾则为离线dry-run；smoke/e2e仅勾一项会拒绝执行，避免只花一半钱却没有配对结果。

后续不是一键全跑：先看smoke，随后 `retrieval128`（只勾Jev）和 `e2e128`（两项都勾）；再决定是否值得扩大256。

## 看产物

artifact名：`jev-evidence-v05-<run_id>-<attempt>`，保留30天。

`report.md` 是入口；`summary.json` 有每臂完整分母、helped/harmed、证据召回、用量与整条路径成本/延迟。`plan.json` 是冻结计划，gold只留在评测端；`requests/` 保存实际送出的合成请求体，不含headers或key；`calls.jsonl` 逐请求记录intent/result；`retrieval.jsonl` 保存分片、候选和原文包；`trials.jsonl` 保存每次下游结果。

输出上限会计为失败但不自动重试；费用仍计入。未知计量、认证/传输等问题会停。看到红卡先保留artifact，不要连续重跑。

## 中断后恢复

相同stage、split、case_id、代码/协议未变时，在 `resume_run` 填上一个运行的数字ID。程序下载原artifact，校验计划/请求哈希，只复用已有完整结果。未确定是否已经计费的发送不会自动重试，需要先审阅。

要跨时间测模型变化，应留空 `resume_run`，使用同一计划做一轮新观测；否则复用旧响应不算重测。

## 本机可选命令

```bash
python -m unittest discover -s tests -v
python -m evidence_lab plan --stage smoke --split dev --out phase-plan.json
python -m evidence_lab run --plan phase-plan.json --out runs/phase-dry
# 环境变量由你在本机安全设置；下句才会真实付费。
python -m evidence_lab run --plan phase-plan.json --out runs/phase-live --allow-jev-paid --allow-llm-paid
```

只有Python标准库，不需要GPU或安装本地模型。
