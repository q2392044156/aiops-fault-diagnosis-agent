# AIOps Fault Diagnosis Agent

面向公开 HDFS 日志的可复现研究原型。W1 提供可追溯数据准备；W2 冻结时间/事件代理协议并建立传统基线；W3 实现小型监督式 LSTM；W4 完成统一评测和 v0.2 模型冻结；W5 将冻结的 LR 发布为可恢复的异常检测 API；W6 提供 CPU 容器、独立 worker 和 Streamlit 事件复核台。不执行自动修复。

当前状态：W1 全量数据 11,175,629 行、575,061 个 block 会话；W2/W3 使用 Dmain 100,000 个训练会话、Ddev 10,000 个训练会话及完整 38,504 个验证会话。W4 按预登记规则一次性评测 250,538 个测试会话，默认发布模型冻结为 TF-IDF + Logistic Regression，LSTM 保留为研究对照。W5 API 已用 W1 开发批次完成真实模型冒烟测试。W6 服务部署版本为 v0.3，模型仍是 W4 冻结的 `v0.2_lr`。

## Conda 环境

唯一支持的环境是名为 `aiops-fault-diagnosis-agent` 的 Conda 环境，Python 3.11。旧 `.venv` 不再使用，但不会自动删除。

```powershell
conda env create --file environment.yml
conda run --name aiops-fault-diagnosis-agent python -m pip install -r requirements-lock.txt
conda run --name aiops-fault-diagnosis-agent python -m pip install -e ".[dev,research]" --no-deps
conda run --name aiops-fault-diagnosis-agent python -m pip check
conda run --name aiops-fault-diagnosis-agent python -m pytest -q
```

也可使用 `environment.yml` 创建环境；`requirements-lock.txt` 是本次 Windows 验收环境的精确 Python 包快照。所有命令须从项目根目录执行。

## W1 数据命令

```powershell
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.data download --config configs/data.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.data build --config configs/data.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.data split --config configs/data.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.data subset --config configs/data.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.data audit --config configs/data.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.data trace --config configs/data.yaml --log-id '<源文件SHA256>:<行号>'
```

全量运行前建议至少保留 20 GB 可用磁盘。数据输出位于 `data/`，按批处理并由 Git 忽略。

## W2 建模命令

```powershell
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling freeze --config configs/model_lr.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling templates --config configs/model_lr.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling train --config configs/model_lr.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling predict --config configs/model_lr.yaml --split validation
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling evaluate --config configs/model_lr.yaml --split validation
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling run --config configs/model_lr.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling inspect --config configs/model_lr.yaml --run-id <run_id> --session-id <block_id>
```

`predict` 和 `evaluate` 只接受 `dev` 或 `validation`，传入 `test` 会以非零状态失败。模型只从项目生成、哈希登记的实验目录加载；数据协议、Drain3、词表、模型或 manifest 被修改后会拒绝复用。

本地大型制品写入 `artifacts/` 和 `experiments/`。`docs/` 中的本地报告、模型卡和审计材料也不纳入 Git；这些目录均由 `.gitignore` 整体忽略。

## W3 LSTM 命令

W3 默认优先使用 CUDA，CUDA 不可用时回退 CPU；可通过 `--device auto/cuda/cpu` 显式控制。

```powershell
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling lstm-prepare --config configs/model_lstm.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling lstm-tune --config configs/model_lstm.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling lstm-train --config configs/model_lstm.yaml --device auto
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling lstm-predict --config configs/model_lstm.yaml --split validation
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling lstm-evaluate --config configs/model_lstm.yaml --split validation
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling lstm-run --config configs/model_lstm.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.modeling lstm-inspect --config configs/model_lstm.yaml --run-id <run_id> --seed 42 --session-id <block_id>
```

模板序列最长块固定为 128；更长会话按连续、不重叠块完整处理，并以块级最大 logit 汇聚为会话异常分数。模型只接受模板、事件间隔和四项审计过的会话统计。W3 只评估 `dev`/`validation`；请求 `test` 会以非零状态失败。

## W4 统一评测命令

```powershell
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.selection preregister --config configs/model_selection.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.selection compare-parsing --config configs/model_selection.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.selection ablate --config configs/model_selection.yaml --device auto
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.selection finalize --config configs/model_selection.yaml --device auto
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.selection report --config configs/model_selection.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.selection inspect --config configs/model_selection.yaml --model-id logistic_regression --session-id <block_id>
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.selection run --config configs/model_selection.yaml --device auto
```

`finalize` 是测试集的唯一受控入口。测试阈值来自 W2/W3 验证结果；完成后相同输入只校验并复用同一套预测，配置或上游模型 hash 变化会被拒绝。W4 测试结果显示明显时间分布差异：LR 的 F1 为 0.883181、AP 为 0.789731；LSTM 三 seed 的 F1 为 0.882568–0.883925、AP 为 0.953322–0.993442。由于固定阈值下没有跨 seed 稳定提升，测试结果不改变预先冻结的 LR 默认选择。

## 实验边界

标签不参与日志解析、模板拟合或 Dmain/Ddev 抽样。Drain3 只按训练日志原始顺序拟合，验证、测试和服务推理只调用冻结 `match()`，未知模板映射为 `T_UNK`。IPv4 哈希主机事件簇只是降低泄漏或合并告警的保守代理，不是真实故障事件。HDFS 没有真实根因类别或可信故障开始时间，因此不报告根因准确率或生产 MTTD。W6 不实现 RAG、Agent、鉴权、TLS 或自动处置。

## W5 服务命令

W5/W6 默认只监听本机，使用 SQLite WAL。先发布并校验便携冻结制品；本地开发时分别启动 API 和 worker：

```powershell
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service publish --config configs/service.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service init --config configs/service.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service verify --config configs/service.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service serve --config configs/service.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service worker --config configs/service.yaml
```

OpenAPI 页面为 `http://127.0.0.1:8000/docs`。`POST /api/v1/batches/uploads` 接受最大256 MiB的原始 HDFS 文本日志；`POST /api/v1/batches/registered` 只接受配置白名单中的批次 ID。任务返回202，随后可查询任务、批次、异常事件、会话和脱敏日志。相同内容、发布和处理配置会复用同一任务；可选 `Idempotency-Key` 冲突返回409。

服务只加载发布清单中登记且哈希匹配的 Drain3、模板词表、TF-IDF 和 LR 制品，不触发训练或阈值搜索。运行数据库、上传和 Parquet 输出位于 `runtime/` 并由 Git 忽略。当前无鉴权和 TLS，只适用于本机研究演示。

## W6 Docker Compose

W6 使用不含 Torch/CUDA 的 Python 3.11 CPU 镜像。模型发布包只读挂载，SQLite、上传和任务制品保存在命名卷中。API、worker 和 UI 均以非 root 用户运行，根文件系统只读且不挂载 Docker socket。

先在 Conda 环境中生成并校验自包含发布包，然后启动三服务：

```powershell
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service publish --config configs/service.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service verify --config configs/service.yaml
docker compose -f deployment/compose.yaml up --build -d
docker compose -f deployment/compose.yaml ps
docker compose -f deployment/compose.yaml logs --tail=100 api worker ui
```

- API/OpenAPI：`http://127.0.0.1:8000/docs`
- Streamlit：`http://127.0.0.1:8501`
- API readiness 同时检查发布包、数据库和最新 worker 心跳。
- `docker compose -f deployment/compose.yaml down` 会保留命名卷；只有显式追加 `-v` 才删除运行数据。
- `GET /api/v1/operations/summary` 返回队列、任务和 worker 摘要，不暴露本地路径。

W6 工程基准命令如下，结果保存到被忽略的 `experiments/w6/`：

```powershell
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service benchmark --config configs/service.yaml --suite e1
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service benchmark --config configs/service.yaml --suite e2
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service benchmark --config configs/service.yaml --suite e3
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.service benchmark --config configs/service.yaml --suite e4
```

若发布包或登记数据不在默认位置，可在启动 Compose 前设置 `AIOPS_RELEASE_DIR` 和 `AIOPS_REGISTERED_FILE` 为对应宿主机路径。容器运行阶段不会下载模型、训练模型或重新选择阈值。

## W7 运维知识检索

W7 提供30篇可追溯的中文原创知识卡片（24篇HDFS、6篇通用运维）、BM25、BGE Dense 与 RRF Hybrid 检索。Dense 模型固定为官方 `BAAI/bge-small-zh-v1.5` revision `7999e1d3359715c523056ef9478215996d62a620`，本地导出为FP32 ONNX；服务镜像不安装Torch，也不会在运行时联网下载模型。

```powershell
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.retrieval validate --config configs/retrieval.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.retrieval fetch-model --config configs/retrieval.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.retrieval build --config configs/retrieval.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.retrieval tune --config configs/retrieval.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.retrieval publish --config configs/retrieval.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.retrieval finalize --config configs/retrieval.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.retrieval verify --config configs/retrieval.yaml
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.retrieval search --config configs/retrieval.yaml --query "NameNode安全模式如何只读排查？"
conda run --name aiops-fault-diagnosis-agent python -m aiops_diag.retrieval benchmark --config configs/retrieval.yaml
```

Rdev 冻结方案为固定切分、Hybrid、Top-3，证据门禁阈值为 `0.55043625831604`。冻结前Rdev的Hybrid Top-5取得 Recall 1.000、MRR 0.9333、nDCG 0.7854；一次性Rtest的Hybrid Top-5取得 Recall 0.975、MRR 0.9375、nDCG 0.7827。门禁在Rdev将无答案误返回控制为10%，但Rtest实测为20%，说明拒答校准仍有分布差异；该结果未用于反向调参，W8前应将其作为已知限制。

服务新增 `POST /api/v1/retrieval/search`、`GET /api/v1/knowledge/chunks/{chunk_id}` 和 `GET /api/v1/knowledge/releases/current`。Streamlit“知识检索”页只通过这些API访问数据，可查看BM25、Dense、RRF分数和可点击证据。检索只返回现有卡片证据，不调用LLM，也不生成诊断结论或处置建议。

本机 W6 验收中，W1 开发批次的 233,584 行日志和 10,000 个会话在约9.82秒内完成，得到502个异常事件；并发1/2/4下100次摘要查询均无错误，P95分别为4.60/8.23/16.03毫秒。五次完整容器启动为13.07–13.74秒，五次热重启为1.92–2.04秒。以上仅是当前机器的研究原型实测，不作为生产容量承诺。

请只提交代码、配置、依赖文件和自制测试；不要提交 `data/`、`artifacts/`、`experiments/`、`docs/`、`.conda-env/` 或旧 `.venv/`。
