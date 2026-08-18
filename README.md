# ICD 自动编码项目 —— 数据层说明（README）

> 最后更新：2026-08-17

## 一句话概括

数据层把原始 MIMIC 数据库整理成 **Agent 可以直接吃的"出院小结 + ICD 编码答案"样本对**，并提供了全组统一的**评测脚本**。简单说：**出了题（数据集）、备了答案（ICD 标签）、造了阅卷的尺子（evaluate.py）**。

## 做了什么

### 1. 构造了两个数据集

从 PhysioNet 的原始数据库中，筛选出院小结、关联诊断编码、去重、按病人切分，产出可直接用于训练/评测的 jsonl 数据集：

| | MIMIC-III 数据集 | MIMIC-IV 数据集 |
|---|---|---|
| 来源 | NOTEEVENTS + DIAGNOSES_ICD | mimic-iv-note (discharge) + diagnoses_icd |
| 样本量 | 52,722 | 331,604 |
| 病人数 | — | 145,817 |
| 编码版本 | ICD-9（6,918 种码） | ICD-9 + ICD-10 双版本（8,837 + 16,155 种码） |
| 平均码数/样本 | 11.74 | 12.68 |
| 切分 | train 36,937 / dev 5,280 / test 10,505 | train 232,817 / dev 33,236 / test 65,551 |

处理细节：

- **筛选**：只保留出院小结（MIMIC-III 的 `CATEGORY == "Discharge summary"`，MIMIC-IV 的 `note_type == "DS"`），剔除标记为错误的 note
- **去重**：同一住院（hadm_id）只保留一份小结
- **切分**：70/10/20，**按 subject_id（病人）切分**，同一病人绝不跨 train/test，防止数据泄漏
- **双版本标签**（仅 MIMIC-IV）：诊断码按 `icd_version` 拆成 `icd9_codes` / `icd10_codes` 两个字段，用哪版自取

每行样本格式：

```json
{"subject_id": 22532, "hadm_id": 167853, "text": "Admission Date...（出院小结全文）", "icd9_codes": ["4019", "4280", "25000"]}
```

MIMIC-IV 额外多 `note_id` 和 `icd10_codes` 字段。

### 2. 评测脚本（全组统一的打分标尺）

`evaluate.py`：Agent 输出预测后一条命令打分。

```bash
python evaluate.py --truth test.jsonl --pred predictions.jsonl
```

输出 micro/macro-F1、P@5、P@8（ICD 编码领域标准指标）。MIMIC-III / MIMIC-IV 通用。

### 3. 数据统计与预警（详见各 stats.json）

- **长尾问题严重**：MIMIC-III 有 1,510 个码全库只出现 1 次，MIMIC-IV 有 5,730 个——这是召回 Agent 和 G-Memory 最容易失效的区域
- **MIMIC-IV 以 ICD-9 为主**：209,323 个样本是 ICD-9，仅 122,288 个是 ICD-10（集中在 2015 年 10 月美国切换 ICD-10 之后）。**Trie 检索（pzy）选版本时要注意：用 ICD-10 就只有 12.2 万样本可用**
- 最高频码：MIMIC-III 是 `4019`（高血压）；MIMIC-IV ICD-10 是 `E785`（高脂血症）、`I10`（高血压）

### 4. eICU 的结论（重要，影响项目预期）

**eICU 2.0 已评估并放弃**：它的 note 表是 Philips 系统的结构化勾选记录（notevalue 全是 "Problem View"/"Copies" 这类下拉值），**不存在出院小结自由文本**，无法作为 ICD 编码任务的训练/评测数据补量。组内任何依赖"以后上 eICU 扩数据"的计划都不成立。

## 目录结构

```
├── README.md                  ← 本文件
├── .gitignore                 ← 挡住数据文件，防止误传（PhysioNet 协议禁止）
├── build_mimic3_dataset.py    ← MIMIC-III 数据集构造脚本
├── build_mimic4_dataset.py    ← MIMIC-IV 数据集构造脚本
├── evaluate.py                ← 评测脚本（全组统一打分标尺）
├── mimic3_stats.json          ← MIMIC-III 统计报告
└── mimic4_stats.json          ← MIMIC-IV 统计报告
```

## 数据文件去哪了（合规说明）

**train/dev/test.jsonl 不上传仓库**——文件内容是真实病历文本，PhysioNet 的 Credentialed Health Data License **禁止再分发**（私有仓库也不行）。

获取数据的正确方式（每个需要跑数据的成员）：

1. 在 https://physionet.org 注册并完成 credentialed 认证（学生邮箱 + CITI 培训证书）
2. 下载 `mimic-iii-clinical-database-1.4` 和 `mimic-iv-note 2.2` + `mimic-iv-3.1`
3. 修改脚本顶部的路径常量，运行：

```bash
python build_mimic3_dataset.py   # 约 2 分钟
python build_mimic4_dataset.py   # 约 2 分钟
```

脚本确定性切分（random_state=42），所有人跑出的数据集**完全一致**，无需互传文件。

## 各队友怎么用

| 谁 | 用什么 | 怎么用 |
|---|---|---|
| wyk（章节切分/召回） | train.jsonl + dev.jsonl | 读 `text` 字段切章节，读编码字段做召回 ground truth |
| lby（编码 Agent） | dev.jsonl + test.jsonl + evaluate.py | Agent 输出 `{hadm_id, codes}` 格式，用 evaluate.py 出分 |
| xzh（G-Memory） | mimic3_stats.json + mimic4_stats.json | 长尾码清单 = 记忆层最需要补经验的薄弱点 |
| pzy（ICD Trie） | stats.json + 本 README 第 3 节 | 确定版本：ICD-9 需覆盖 8,837 种码；ICD-10-CM 需覆盖 16,155 种 |

## 纪律

- **test.jsonl 任何人不得用于调参**，只在最终评测用一次
- 评测以 `evaluate.py` 的 micro-F1 为主要指标，结果才可比
- 若发现数据问题请先在群里同步，不要私自改脚本重跑（会破坏一致性）
