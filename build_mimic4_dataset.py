# -*- coding: utf-8 -*-
"""MIMIC-IV -> ICD 编码样本对构造脚本
产出: (出院小结文本, ICD 码集合) 样本对, 按 70/10/20 切 train/dev/test (按 subject_id 切, 无泄漏)
与 MIMIC-III 脚本同构, 字段差异:
  - note 在 mimic-iv-note 包的 discharge.csv.gz, note_type == 'DS'
  - 同一 hadm 多份 note 时取 note_seq 最小的一份 (原始全文, 补记 addendum 是追加片段)
  - diagnoses_icd 带 icd_version (9/10), 输出同时给 icd9_codes / icd10_codes 两个列表
用法: python build_mimic4_dataset.py
"""
import gzip
import json
import os
from collections import Counter

import pandas as pd

NOTE_DIR = r"C:\Users\asus\Desktop\暑期科研\mimic-iv-note-deidentified-free-text-clinical-notes-2.2\note"
HOSP_DIR = r"C:\Users\asus\Desktop\暑期科研\mimic数据库\mimic-iv-3.1\mimic-iv-3.1\hosp"
OUT_DIR = r"C:\Users\asus\WorkBuddy\2026-08-16-23-01-28\output\mimic4-icd-dataset"
CHUNKSIZE = 100_000

os.makedirs(OUT_DIR, exist_ok=True)


def load_discharge_summaries():
    """逐块读取 discharge.csv.gz, 只保留 note_type == 'DS'"""
    keep_rows = []
    n_chunks = 0
    reader = pd.read_csv(
        os.path.join(NOTE_DIR, "discharge.csv.gz"),
        chunksize=CHUNKSIZE,
        low_memory=False,
    )
    for chunk in reader:
        n_chunks += 1
        m = chunk["note_type"].eq("DS")
        keep_rows.append(chunk.loc[m, ["subject_id", "hadm_id", "note_id", "note_seq", "text"]])
        print(f"  chunk {n_chunks} done, kept {sum(len(r) for r in keep_rows)}", flush=True)
    return pd.concat(keep_rows, ignore_index=True)


def main():
    print("[1/4] reading discharge.csv.gz (1.1GB gz, may take a few min)...", flush=True)
    notes = load_discharge_summaries()
    print(f"  DS notes: {len(notes)}", flush=True)

    # 同一 hadm 多份 note 时取 note_seq 最小的一份 (原始完整小结)
    notes = notes.sort_values("note_seq").groupby("hadm_id", as_index=False).first()
    print(f"  after dedup by hadm_id: {len(notes)}", flush=True)

    print("[2/4] reading diagnoses_icd...", flush=True)
    diag = pd.read_csv(
        os.path.join(HOSP_DIR, "diagnoses_icd.csv.gz"),
        dtype={"icd_code": str, "icd_version": "Int64"},
    )
    # 按 version 拆成两组标签
    d10 = diag[diag["icd_version"] == 10]
    d9 = diag[diag["icd_version"] == 9]
    lab10 = d10.groupby("hadm_id")["icd_code"].apply(
        lambda s: sorted(set(s.dropna()))).rename("icd10")
    lab9 = d9.groupby("hadm_id")["icd_code"].apply(
        lambda s: sorted(set(s.dropna()))).rename("icd9")
    print(f"  hadm with ICD-10: {len(lab10)}, with ICD-9: {len(lab9)}", flush=True)

    print("[3/4] joining text + labels...", flush=True)
    df = notes.merge(lab10, left_on="hadm_id", right_index=True, how="left")
    df = df.merge(lab9, left_on="hadm_id", right_index=True, how="left")
    df["icd10"] = df["icd10"].apply(lambda v: v if isinstance(v, list) else [])
    df["icd9"] = df["icd9"].apply(lambda v: v if isinstance(v, list) else [])
    df["labels"] = df["icd10"] + df["icd9"]
    df = df[df["labels"].str.len() > 0].reset_index(drop=True)
    print(f"  final samples: {len(df)}", flush=True)

    print("[4/4] splitting 70/10/20 by subject_id (no leakage)...", flush=True)
    subjects = df["subject_id"].drop_duplicates().sample(frac=1.0, random_state=42)
    n = len(subjects)
    tr = set(subjects[: int(n * 0.7)])
    dv = set(subjects[int(n * 0.7) : int(n * 0.8)])
    te = set(subjects[int(n * 0.8) :])
    for name, sub in [("train", tr), ("dev", dv), ("test", te)]:
        part = df[df["subject_id"].isin(sub)]
        path = os.path.join(OUT_DIR, f"{name}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for _, r in part.iterrows():
                f.write(json.dumps(
                    {"subject_id": int(r["subject_id"]),
                     "hadm_id": int(r["hadm_id"]),
                     "note_id": r["note_id"],
                     "text": r["text"],
                     "icd10_codes": r["icd10"],
                     "icd9_codes": r["icd9"]},
                    ensure_ascii=False) + "\n")
        print(f"  {name}: {len(part)} samples", flush=True)

    # 统计报告
    all10 = Counter(c for labs in df["icd10"] for c in labs)
    all9 = Counter(c for labs in df["icd9"] for c in labs)
    both = df["icd10"].str.len().gt(0) & df["icd9"].str.len().gt(0)
    lengths = df["text"].str.len()
    stats = {
        "total_samples": len(df),
        "unique_patients": int(df["subject_id"].nunique()),
        "unique_icd10_codes": len(all10),
        "unique_icd9_codes": len(all9),
        "samples_with_icd10": int(df["icd10"].str.len().gt(0).sum()),
        "samples_with_icd9": int(df["icd9"].str.len().gt(0).sum()),
        "samples_with_both_versions": int(both.sum()),
        "avg_codes_per_sample": round(sum(len(l) for l in df["labels"]) / len(df), 2),
        "text_len_chars": {"mean": int(lengths.mean()), "median": int(lengths.median()),
                           "p95": int(lengths.quantile(0.95))},
        "top20_icd10_codes": all10.most_common(20),
        "codes_appearing_once": sum(1 for c in list(all10.values()) + list(all9.values()) if c == 1),
    }
    with open(os.path.join(OUT_DIR, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print("DONE ->", OUT_DIR, flush=True)


if __name__ == "__main__":
    main()
