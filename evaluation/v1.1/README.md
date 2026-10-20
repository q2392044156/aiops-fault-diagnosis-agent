# v1.1 检索评测协议（建设中）

本目录包含 16 条从 Apache 官方公开文档主题编写的**自审候选问题**：开发 4 条、校准 4 条、待复核测试 8 条，覆盖 HDFS 3.3.5、3.3.6、3.4.1 和 3.4.2。数量和问题族覆盖尚不足以支持泛化结论，测试问题也已被开发者看到。`knowledge/evaluation/rdev.jsonl`、`rtest.jsonl` 已经在 v1.0 开发和报告中使用，只能作为回归对照。目前尚无经过独立复核的新盲测集，**v1.1 效果目标未验收**。

另有 `review_pool.jsonl` 的 8 条新候选（4 条拟有答案、4 条拟无答案），来自 3.4.1/3.4.2 官方文档主题，尚未并入任何冻结 split，也不参与校准或指标计算。拟有答案的知识单元、拟无答案判定都只是供领域人员复核的提案；复核时应先隐藏这些拟定标签，并检查题意、知识库适用范围、与旧题的语义重复及来源对应关系。即使全部通过，正式独立测试仍需另行扩容、冻结和独立复核。

`review_packet.jsonl` 是供复核人员使用的无拟定答案副本，只列问题、版本、官方来源和空白复核字段。复核人员需同时阅读冻结知识卡目录，独立填写 `review_has_answer`、`review_evidence_unit_ids`、`reviewer_id` 和 `review_notes`；不要把包含拟定标签的 `review_pool.jsonl` 发给复核人员。此包只有 8 题，是标注流程样例，不是正式独立测试集。

在此流程样例基础上，`public_candidate_pool_60.jsonl` 已扩充为 60 条公开 Apache 文档候选，拟有答案 40 条、拟无答案 20 条，覆盖 HDFS 3.4.1 与 3.4.2。`public_review_packet_60.jsonl` 是对应的盲化副本，不含 `family_id`、拟定答案或拟定证据。结构校验会检查数量、比例、唯一 ID、问题族、与 v1.0/v1.1 已有题目的文本重复、官方来源域名、版本和知识单元适用性：

```powershell
python -m aiops_diag.retrieval.candidate_pool_v11 validate evaluation/v1.1/public_candidate_pool_60.jsonl evaluation/v1.1/public_review_packet_60.jsonl knowledge/cards evaluation/v1.1/development.jsonl evaluation/v1.1/calibration.jsonl evaluation/v1.1/independent_test.jsonl knowledge/evaluation/rdev.jsonl knowledge/evaluation/rtest.jsonl
```

只能把 `public_review_packet_60.jsonl` 和复核所需的知识卡交给复核者。填写规则沿用上文的 `review_has_answer`、`review_evidence_unit_ids`、`reviewer_id` 与 `review_notes`。收到填写副本后，可使用 `review_v11` 校验结构和列出与拟定标签的分歧。由于这 60 题已在开发过程中生成和看到，它们即使通过复核也应先作为候选集或外部复核材料；正式盲测是否采用，必须由未参与开发的负责人完成污染审计并决定，不能由程序自动升级。机器可读状态见 `deliverables/results/v1_1_public_candidate_pool.json`。

收到 8 题样例填写后的副本时，可运行 `python -m aiops_diag.retrieval.review_v11 evaluation/v1.1/review_pool.jsonl evaluation/v1.1/review_packet.jsonl <填写后的复核文件> knowledge/cards <新的复核结果路径>`。60 题候选使用相同命令，只需将前两个参数换成 `public_candidate_pool_60.jsonl` 和 `public_review_packet_60.jsonl`。校验器检查题包未泄露拟定标签、问答与证据单元一致、适用版本和分歧清单，并记录输入与工具哈希；它只能核对结构，无法证明复核者的真实身份或标签语义。分歧需人工裁决，不能自动把复核结果标成正式独立测试。

如果 60 题外部复核没有分歧，可以生成一个新的、不可覆盖的完整协议目录；开发、校准集从当前协议复制并重新计算哈希，外部复核题转换为独立测试集：

```powershell
python -m aiops_diag.retrieval.freeze_reviewed_v11 evaluation/v1.1/protocol.json evaluation/v1.1/public_candidate_pool_60.jsonl evaluation/v1.1/public_review_packet_60.jsonl <填写后的复核文件.jsonl> knowledge/cards evaluation/v1.1/releases/<新目录>
```

若有分歧，命令默认拒绝冻结。人工裁决文件应只包含分歧题，每行字段为 `candidate_id`、`final_has_answer`、`final_evidence_unit_ids`、`adjudicator_id` 和 `adjudication_notes`；裁决者必须与原复核者不同。再次运行时追加 `--adjudication <裁决文件.jsonl>`。输出的 `freeze_manifest.json` 会绑定题池、盲化包、回传文件、裁决文件及协议哈希，并保留 `external_process_required` 身份核验提示。即使程序返回 `release_ready=true`，项目负责人仍必须线下确认复核者身份、领域能力、独立性和污染情况，随后基于新协议重新生成候选清单；禁止把单元测试中的模拟复核者或自行填写的标签用于发布。

## 数据来源与标注

优先从 Apache 官方的 [Hadoop 3.3.6 HDFS 文档](https://hadoop.apache.org/docs/r3.3.6/hadoop-project-dist/hadoop-hdfs/) 和 [Hadoop 3.4.1 HDFS 文档](https://hadoop.apache.org/docs/r3.4.1/hadoop-project-dist/hadoop-hdfs/) 制作跨版本案例；来源发布日期统一按[官方公告页](https://hadoop.apache.org/release.html)记录，例如 3.3.5 的公告日期为 2023-03-22，不能混用网站重新部署时间或其他统计日期。对校验和、网络链路等主题，来源指向相应版本的 HDFS Architecture 页面，不笼统引用 User Guide。若问题针对版本特有行为，须先有相应版本的知识卡和证据单元；若索引没有该版本的适用证据，应标注为无答案。跨数据集日志可评估异常检测迁移，但不能自动充当检索问题的根因标准答案。

正式集每个问题记录 `query_id`、`family_id`、`split`、`query`、布尔值 `has_answer`、`source_id`、`product_version`、`annotator_id` 和不同的 `reviewer_id`。当前自审候选集尚无独立标注者与复核者。有答案问题在 qrels 中记录 `evidence_unit_id` 和相关度 1/2；无答案问题不能有 qrels。来源目录记录原始 URL、产品版本和正式发布日期。相同问题族、规范化后的重复问题、已见过的 v1.0 问题均不能跨 split。独立测试集应由未参与调参的领域人员复核；自审数据只用于开发或候选预检。

## 冻结与门禁

`protocol.json` 使用 `schema_version: 2`，含 `sources`、`knowledge_cards_dir`、`legacy_query_files` 和 `splits.development/calibration/independent_test`。每个 split 指向查询和 qrels JSONL 文件，记录 `queries_sha256`、`qrels_sha256` 和 `annotation_status`。`published_at` 记录 Apache 正式版本发布日期，不采用网站重新部署时间。文件冻结后只允许生成新候选版本，不覆盖旧哈希。运行：

```powershell
python -m aiops_diag.retrieval.protocol_v11 evaluation/v1.1/protocol.json --release-ready
```

检查器验证文件哈希、来源版本、答案/qrels 一致性、qrels 的证据单元及适用版本、跨 split 与旧版问题泄漏，并要求独立测试集经过独立复核、至少 60 条问题且其中至少 20 条无答案、包含至少两个版本和两个来源日期，且测试来源时间晚于开发/校准来源。60/20 是最低验收规模门槛，仍不足以自动证明泛化效果。目前 `--release-ready` 会按预期失败。检查器不能判断标注语义是否正确，人工复核和污染审计报告仍是发布门禁。

先用开发与校准集确定门禁，再一次性运行独立测试。报告必须同时给出样本量、Top-3 Recall、MRR、nDCG、有答案误拒率、无答案误返回率和按版本/组件分组结果。无答案误返回率 ≤10% 是**目标**，不是当前实测。任何测试结果驱动的修改都要产生新候选和新独立验收。

当前 `aiops_diag.retrieval.gate_v11` 候选门禁使用最终排名第一的证据项相似度；原 v1.0 门禁比较所有适用知识块中的最高相似度。候选校准命令只读取开发与校准文件：

```powershell
python -m aiops_diag.retrieval.gate_v11 configs/retrieval.yaml evaluation/v1.1/protocol.json experiments/v1_1/gate_calibration.json
```

当前 4 条开发与 4 条校准候选样本得到阈值约 `0.55808`，两组各只有 2 条无答案问题，门禁误返回均为 0/2。这仅是**小样本的开发/校准观察**，不能当成 v1.1 独立测试结果，也不足以证明达到 ≤10% 泛化目标。`independent_test` 文件未由该命令读取或调参。

## 隔离候选运行与回退

当前 Python 包版本为 `1.1.0rc1`，候选 Agent 清单标记 `v1.1-rc1` / `RESEARCH_CANDIDATE`。默认 `configs/service.yaml` 仍加载 v1.0；`configs/service_v11_candidate.yaml` 才启用新门禁和报告 Agent，并使用独立运行目录。候选清单发布与加载都会重新计算开发/校准阈值和确定性指标，拒绝手填或过期的校准结果。先生成校准结果，再生成候选清单：

```powershell
python -m aiops_diag.retrieval.gate_v11 configs/retrieval.yaml evaluation/v1.1/protocol.json experiments/v1_1/gate_calibration.json
python -m aiops_diag.agent_v11.release configs/agent.yaml evaluation/v1.1/protocol.json experiments/v1_1/gate_calibration.json configs/service_v11_candidate.yaml artifacts/releases/agent_v11_rc1_15
python -m pytest -q
docker compose -f deployment/compose.yaml -f deployment/compose.v11-candidate.yaml config --quiet
```

如需容器对照，须在 Docker daemon 和项目原有只读数据挂载、Secret 均就绪时，以这两个 Compose 文件构建和启动独立项目。候选覆盖文件使用独立 Compose 项目名和运行卷，挂载校准结果与候选 Agent 清单为只读；基础 v1.0 项目无需停机。回退就是停用候选 Compose 项目，继续运行**已冻结的 v1.0 镜像与制品**。不可从当前 v1.1 候选源码重新构建并标记为 v1.0；如需重建，应使用 v1.0 对应的 Git 提交。不能把候选运行卷中的报告或审批覆盖到 v1.0 运行卷。当前工作树新增了 Python 模块，旧产品级 `release verify` 的全源码哈希检查会按设计拒绝当前树；旧 Agent 与服务制品的单独验证仍通过。

独立复核、扩容、重新冻结协议并生成对应的新候选清单后，执行一次性离线验收命令：

```powershell
python -m aiops_diag.retrieval.blind_v11 configs/agent.yaml evaluation/v1.1/protocol.json experiments/v1_1/gate_calibration.json configs/service_v11_candidate.yaml artifacts/releases/<新的候选目录> experiments/v1_1/<新的独立验收目录>
```

该命令先检查发布就绪和候选清单，才读取独立测试问题；同一输出目录不能覆盖。输出包含旧门禁与候选门禁的逐题结果、分版本/组件结果、分子分母、延迟和绑定哈希。当前自审候选协议会被拒绝，不能用此命令产生正式验收报告；若根据盲测结果改算法，须创建新候选和新独立测试协议。

候选服务目前复用 v1.0 检测模型、知识索引、RAG 实现和服务制品，并在 API/worker 中 opt-in 新门禁与 Agent；API 报告标记 `rag_v0.2_candidate`，Agent 标记 `agent_v0.3_candidate`。它不是完整的 v1.1 正式发布。rc1_15 已完成三轮真实在线评测、干净环境验收和隔离 Compose 实际运行验收；发布前仍需外部独立复核、重新冻结的更大盲测集、对应的新候选清单和正式 Git 标记。当前不创建正式 `v1.1` tag。

干净环境中的**服务依赖**已单独检查：隔离 Python 3.11.17 环境安装 `requirements-service-lock.txt`、pytest 和本地构建的 `1.1.0rc1` 候选 wheel 后，77 个依赖兼容；排除需要研究依赖 PyTorch 的 `test_lstm.py`、`test_selection.py`，其余 119 项测试通过，从已安装 wheel 导入候选题池、协议冻结及在线评测工具，加载 rc1_15 worker 也通过。完整 135 项测试另在研究环境通过。记录见 `deliverables/results/v1_1_clean_env_acceptance.json`。Linux Compose 和在线 DeepSeek 验收分别记录，独立检索盲测仍未完成。

## v1.1 报告链三轮在线评测

`agent_v11.online_evaluation` 直接调用候选报告链，而不是沿用 v1.0 的简化四字段评测 Schema。每轮固定读取原 Atest 的 40 个安全场景：34 例构造日志和手册证据并调用 DeepSeek，6 例构造证据不足输入并验证零模型调用；三轮共预期 102 个正常在线案例，修复调用会额外计入。该适配用于输出稳定性、引用与只读安全回归，不代表根因准确率、检索相关性或生产效果。

在本机只通过环境变量或密钥文件配置 DeepSeek 后运行；不要把密钥写入命令、配置或报告：

```powershell
python -m aiops_diag.agent_v11.online_evaluation configs/agent.yaml evaluation/v1.1/protocol.json experiments/v1_1/gate_calibration.json configs/service_v11_candidate.yaml artifacts/releases/agent_v11_rc1_15 experiments/v1_1/online_rc1_15_external_01
```

输出目录不可覆盖，并绑定候选发布 ID、Atest、协议和所有逐轮文件哈希。每轮记录完整报告 Schema 通过数、直接生成数、模板降级分子/分母、预期证据不足数、修复失败分类、token、费用、P50/P95，以及非法引用、可执行建议、操作性文本、提示注入/URL 反射和 Agent 预算突破计数。总预算或单轮预算达到上限时停止后续调用并保留已完成结果。

rc1_15 已完成真实 DeepSeek 三轮验收：每轮 40 例全部完成，34 例直接生成，6 例证据不足并保持零模型调用；三轮 Schema 通过率均为 100%，模板降级率均为 0%，所有安全与预算硬门禁计数为 0。总计 102 次调用、45,102 输入 token、3,231 输出 token，记录费用 0.116052 元；平均 P50 为 978.64 ms，平均 P95 为 1408.20 ms。机器可读摘要见 `deliverables/results/v1_1_online_acceptance_rc1_15.json`。这些是构造安全场景的稳定性结果，不是根因准确率、检索相关性或生产效果。

## rc1_15 隔离 Compose 验收

rc1_15 已在独立 Compose 项目 `aiops-v11-rc1-15` 中实际运行，候选 API/UI 使用 18000/18501 端口，冻结 v1.0 继续使用 8000/8501；两套 API 和 UI 同时健康。worker、API、UI 均以 `10001:10001` 运行，根文件系统只读，候选与服务发布挂载不可写，镜像中不含 `.env`，DeepSeek 与复核凭据通过 Secret 文件挂载。

验收先停止 worker，再提交模板诊断：任务保持排队；相同幂等键返回同一个诊断，不同请求复用同一键返回 409；恢复 worker 后最终只有 1 个诊断、1 份报告、1 条审批和 1 条审批工具审计，且没有模型调用。自动化测试还模拟了审批工具完成后、报告发布前的中断，恢复后没有重复审批调用。机器记录见 `deliverables/results/v1_1_compose_acceptance_rc1_15.json`。该测试验证容器、队列、幂等和审计行为，不衡量真实根因效果。

## Agent runbook 覆盖预检（不代表相关性）

可从已处理的公开 HDFS 事件库生成 40 条脱敏报告输入快照，运行候选 Agent 的真实日志读取、检索和候选排序前半段，并冻结事件库、日志制品及候选发布 ID：

```powershell
python -m aiops_diag.agent_v11.report_cases configs/service_v11_candidate.yaml runtime/service.sqlite3 experiments/v1_1/report_cases_40_rc1_09 --count 40
python -m aiops_diag.retrieval.coverage_v11 configs/agent.yaml experiments/v1_1/report_cases_40_rc1_09 deliverables/results/v1_1_agent_runbook_coverage_rc1_09.json
```

当前本机快照中，旧门禁的通用 runbook 查询在 40/40 条事件返回文档，候选门禁在 2/40 条返回；其余 38 条进入证据不足路径。输入来源于真实的公开 HDFS 日志处理结果，但**没有文档相关性或真实根因标签**，因此覆盖率不能解释为准确率、召回率或候选门禁劣于旧门禁的证明。它表明当前 Agent 的通用查询与显式问题校准集存在明显分布差异；在补充逐事件文档相关性复核及候选在线样本之前，不得把候选设为默认，也不得用这 40 条事件报告生成 Schema ≥99% 的目标。

快照保存在忽略的 `experiments/` 下，包含脱敏日志证据，不进入公开报告。若环境没有旧服务数据库和日志制品，须先按 v1.0 流程处理公开 HDFS 批次；命令不会写入旧数据库。同一输出目录不可覆盖。

### 40 条事件的 runbook 相关性盲化复核

在已封存的 40 条事件快照上，生成逐事件复核题包：

```powershell
python -m aiops_diag.retrieval.runbook_review_v11 build configs/agent.yaml experiments/v1_1/report_cases_40_rc1_09 experiments/v1_1/agent_runbook_review_40_rc1_09
```

当前题包共 40 条事件、120 个事件—文档判断项。`packet.jsonl` 仅展示事件时间窗、最多 8 条去重的脱敏日志、旧版和候选版返回文档的并集，以及空白标注字段；文档按 ID 排序，不显示返回来源、分数或门禁结论。`return_map.private.jsonl` 保存旧版/候选版各自返回的文档 ID，**不得交给复核者**。两个文件及来源快照均有 SHA-256 绑定，保存在被 Git 忽略的 `experiments/` 目录，不应上传原始事件或复核包。复核者只能收到 `packet.jsonl`，并应独立于门禁调参与题包生成工作。

请复核者逐事件给每个 `review_relevance` 文档 ID 填整数：`0` 表示与日志观测无关，`1` 表示有部分排查关联，`2` 表示能直接支持只读排查；填写真实 `reviewer_id` 和非空 `review_notes`。请判断文档是否有助于解释或核查日志中的**观测**，不要根据文档猜测真实根因。若所有候选文档都不相关，全部标 `0`；题包只覆盖两套系统已返回的文档，无法证明知识库中不存在其他相关文档。若脱敏日志不足以判断，应在备注中说明并由人工裁决，不要臆造根因标签。

复核者回传填完的 JSONL 后，运行：

```powershell
python -m aiops_diag.retrieval.runbook_review_v11 evaluate experiments/v1_1/agent_runbook_review_40_rc1_09 <填写后的复核文件.jsonl> experiments/v1_1/agent_runbook_review_40_rc1_09/result.json
```

校验器会拒绝缺失、改动题面、非 `0/1/2` 分数和被篡改的返回映射；结果对照两版“至少一篇相关文档”的事件数，列出仅旧版相关、仅候选相关、两者都相关和两者都不相关。结果状态仍为 `STRUCTURALLY_REVIEWED_NOT_ADJUDICATED`：程序无法验证复核者身份、标签语义或未返回文档的相关性。当前尚未收到独立标注，因此 40/40 与 2/40 仍只是覆盖观察，不能据此调整门禁并继续沿用同一独立测试集。

## v1.0 生成失败基线复核

`experiments/w10/atest_online_summary.json` 留存的 40 例 × 3 次在线评测中，第一轮有 8 例模板降级，错误类型均记为 `DeepSeekError`；第二、三轮没有降级。因此旧的 93.33% `schema_pass_rate` 是“完整调用且 Schema 通过”的端到端口径，不能单独解释为模型返回 JSON 的 Schema 质量。候选评测用 `aiops_diag.agent_v11.evaluation.classify_run` 对每轮结果补充 `failure_categories`、`schema_returned_count` 与 `schema_pass_rate_returned`，区分服务故障、坏 JSON、Schema 错误和评测预算耗尽；原 v1.0 评测文件保持不变。重新归类的归档摘要在 `deliverables/results/v1_1_baseline_error_audit.json`：120 次中 8 次记录为服务错误，其余 112 次 Schema 通过；这个 112/112 仅是旧记录中可判断的条件通过率，不能推断全部故障的更细原因，也不是 v1.1 效果。
