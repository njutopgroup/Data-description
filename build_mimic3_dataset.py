# -*- coding: utf-8 -*-
"""MIMIC-III -> ICD 编码样本对构造脚本
产出: (出院小结文本, ICD-9 码集合) 样本对, 按 70/10/20 切 train/dev/test
用法: python build_mimic3_dataset.py
"""
import gzip
import json
import os
from collections import Counter

import pandas as pd

MIMIC3_DIR = r"C:\Users\asus\Desktop\暑期科研\mimic数据库\mimic-iii-clinical-database-1.4\mimic-iii-clinical-database-1.4"
OUT_DIR = r"C:\Users\asus\WorkBuddy\2026-08-16-23-01-28\output\mimic3-icd-dataset"
CHUNKSIZE = 200_000

os.makedirs(OUT_DIR, exist_ok=True)


def load_discharge_summaries():
    """逐块读取 NOTEEVENTS, 只保留 Discharge summary, ISERROR != 1"""
    keep_rows = []
    n_chunks = 0
    reader = pd.read_csv(
        os.path.join(MIMIC3_DIR, "NOTEEVENTS.csv.gz"),
        chunksize=CHUNKSIZE,
        dtype={"ISERROR": "Float64"},
        low_memory=False,
    )
    for chunk in reader:
        n_chunks += 1
        m = chunk["CATEGORY"].eq("Discharge summary")
        m &= chunk["ISERROR"].fillna(0).ne(1)
        keep_rows.append(chunk.loc[m, ["SUBJECT_ID", "HADM_ID", "ROW_ID", "TEXT"]])
        print(f"  chunk {n_chunks} done, kept {sum(len(r) for r in keep_rows)}", flush=True)
    return pd.concat(keep_rows, ignore_index=True)


def main():
    print("[1/4] reading NOTEEVENTS (1.1GB gz, may take a few min)...", flush=True)
    notes = load_discharge_summaries()
    print(f"  discharge summaries: {len(notes)}", flush=True)

    # 同一 hadm 多份小结时取 ROW_ID 最大的一份 (CAML 标准做法)
    notes = notes.sort_values("ROW_ID").groupby("HADM_ID", as_index=False).last()
    print(f"  after dedup by hadm_id: {len(notes)}", flush=True)

    print("[2/4] reading DIAGNOSES_ICD...", flush=True)
    diag = pd.read_csv(
        os.path.join(MIMIC3_DIR, "DIAGNOSES_ICD.csv.gz"),
        dtype={"ICD9_CODE": str},
    )
    labels = (
        diag.sort_values("SEQ_NUM")
        .groupby("HADM_ID")["ICD9_CODE"]
        .apply(lambda s: sorted(set(s.dropna())))
        .rename("labels")
    )
    print(f"  hadm with diagnoses: {len(labels)}", flush=True)

    print("[3/4] joining text + labels...", flush=True)
    df = notes.merge(labels, left_on="HADM_ID", right_index=True, how="inner")
    df = df[df["labels"].str.len() > 0].reset_index(drop=True)
    print(f"  final samples: {len(df)}", flush=True)

    print("[4/4] splitting 70/10/20 by subject_id (no leakage)...", flush=True)
    subjects = df["SUBJECT_ID"].drop_duplicates().sample(frac=1.0, random_state=42)
    n = len(subjects)
    tr = set(subjects[: int(n * 0.7)])
    dv = set(subjects[int(n * 0.7) : int(n * 0.8)])
    te = set(subjects[int(n * 0.8) :])
    for name, sub in [("train", tr), ("dev", dv), ("test", te)]:
        part = df[df["SUBJECT_ID"].isin(sub)]
        path = os.path.join(OUT_DIR, f"{name}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for _, r in part.iterrows():
                f.write(json.dumps(
                    {"subject_id": int(r["SUBJECT_ID"]),
                     "hadm_id": int(r["HADM_ID"]),
                     "text": r["TEXT"],
                     "icd9_codes": r["labels"]},
                    ensure_ascii=False) + "\n")
        print(f"  {name}: {len(part)} samples", flush=True)

    # 统计报告
    all_codes = Counter(c for labs in df["labels"] for c in labs)
    lengths = df["TEXT"].str.len()
    stats = {
        "total_samples": len(df),
        "unique_patients": int(df["SUBJECT_ID"].nunique()),
        "unique_icd9_codes": len(all_codes),
        "avg_codes_per_sample": round(sum(len(l) for l in df["labels"]) / len(df), 2),
        "text_len_chars": {"mean": int(lengths.mean()), "median": int(lengths.median()),
                           "p95": int(lengths.quantile(0.95))},
        "top20_codes": all_codes.most_common(20),
        "codes_appearing_once": sum(1 for c in all_codes.values() if c == 1),
    }
    with open(os.path.join(OUT_DIR, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print("DONE ->", OUT_DIR, flush=True)


if __name__ == "__main__":
    main()
