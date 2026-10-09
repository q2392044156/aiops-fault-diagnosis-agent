# AIOps Fault Diagnosis Agent

面向公开 HDFS 日志的可复现研究原型。W1 提供可追溯数据准备；W2 冻结时间/事件代理协议，拟合 Drain3，并建立规则、TF-IDF + Logistic Regression 和 Isolation Forest 会话级异常检测基线。不执行自动修复。

当前状态：W1 全量数据 11,175,629 行、575,061 个 block 会话；W2 使用 Dmain 100,000 个训练会话、Ddev 10,000 个训练会话及完整 38,504 个验证会话。测试集保持封存，没有生成测试预测或测试指标。

## Conda 环境

唯一支持的环境是名为 `aiops-fault-diagnosis-agent` 的 Conda 环境，Python 3.11。旧 `.venv` 不再使用，但不会自动删除。

```powershell
conda env create --file environment.yml
conda run --name aiops-fault-diagnosis-agent python -m pip install -r requirements-lock.txt
conda run --name aiops-fault-diagnosis-agent python -m pip install -e . --no-deps
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

## 实验边界

标签不参与日志解析、模板拟合或 Dmain/Ddev 抽样。Drain3 只按训练日志原始顺序拟合，验证集只调用冻结 `match()`，未知模板映射为 `T_UNK`。IPv4 哈希主机事件簇只是降低跨边界泄漏风险的保守代理，不是真实故障事件。W2 不实现 LSTM、根因分类、RAG、Agent、API、前端或自动处置。

请只提交代码、配置、依赖文件和自制测试；不要提交 `data/`、`artifacts/`、`experiments/`、`docs/`、`.conda-env/` 或旧 `.venv/`。
