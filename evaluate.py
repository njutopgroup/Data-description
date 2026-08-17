# -*- coding: utf-8 -*-
"""ICD 编码评测脚本: 预测码 vs 真值码
指标: micro/macro Precision / Recall / F1, P@5, P@8

预测文件格式 (pred.jsonl), 每行:
  {"hadm_id": 100001, "codes": ["4019", "25000", ...]}
真值文件: 上面 build_mimic3_dataset.py 产出的 dev.jsonl / test.jsonl

用法:
  python evaluate.py --truth test.jsonl --pred pred.jsonl
"""
import argparse
import json
from collections import defaultdict


def load_jsonl(path):
    data = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            codes = r.get("codes") or r.get("pred_codes") or r.get("icd9_codes")
            data[int(r["hadm_id"])] = set(codes)
    return data


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", required=True, help="真值 jsonl (含 icd9_codes)")
    ap.add_argument("--pred", required=True, help="预测 jsonl (含 codes)")
    args = ap.parse_args()

    truth = load_jsonl(args.truth)
    pred = load_jsonl(args.pred)
    common = sorted(set(truth) & set(pred))
    missing = len(set(truth) - set(pred))
    if missing:
        print(f"[warn] {missing} 条真值样本没有对应预测, 按全漏记入指标")

    # micro
    tp = fp = fn = 0
    # macro (per-code)
    c_tp, c_fp, c_fn = defaultdict(int), defaultdict(int), defaultdict(int)
    # P@k
    pk_hits = {5: 0, 8: 0}

    for hid in set(truth):
        t = truth[hid]
        p = pred.get(hid, set())
        tps = t & p
        tp += len(tps)
        fp += len(p - t)
        fn += len(t - p)
        for c in tps:
            c_tp[c] += 1
        for c in p - t:
            c_fp[c] += 1
        for c in t - p:
            c_fn[c] += 1
        # P@k: 预测列表有序时取前 k (无序时退化为集合前 k)
        plist = sorted(p)
        for k in pk_hits:
            pk_hits[k] += len(set(plist[:k]) & t)

    n = len(truth)
    p, r, f = prf(tp, fp, fn)
    print(f"样本数: {n}  (有预测: {len(common)})")
    print(f"micro:  P={p:.4f}  R={r:.4f}  F1={f:.4f}")

    per_f1 = []
    for c in set(c_tp) | set(c_fn):
        cp, cr, cf = prf(c_tp[c], c_fp[c], c_fn[c])
        if c_tp[c] + c_fn[c] > 0:  # 真值中出现过的码才计入 macro recall 侧
            per_f1.append(cf)
    print(f"macro:  F1={sum(per_f1)/len(per_f1):.4f}  (over {len(per_f1)} codes)")

    for k in pk_hits:
        print(f"P@{k}: {pk_hits[k]/(n*k):.4f}")


if __name__ == "__main__":
    main()
