#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json, sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CORPUS=ROOT/"evals"/"editorial-gold.jsonl"
SELECTOR=ROOT/"scripts"/"select_priority_news.py"

def load_selector():
    spec=importlib.util.spec_from_file_location("priority_selector",SELECTOR)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

def load_cases():
    cases=[]
    for n,line in enumerate(CORPUS.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip(): continue
        x=json.loads(line)
        for k in ("id","kind","expected"):
            if k not in x: raise SystemExit(f"FAIL corpus line {n}: missing {k}")
        cases.append(x)
    return cases

def evaluate(require_minimum=0, threshold=.90):
    m=load_selector(); cases=load_cases()
    cls=defaultdict(list); dedup=[]; errors=[]
    for x in cases:
        if x["kind"]=="classification":
            c=x["candidate"]; chapter=c.get("chapter")
            if chapter not in m.POLICY: errors.append(f"{x['id']}: unknown chapter"); continue
            asof=m.parse_dt(x.get("asof") or "2026-09-02T00:00:00+00:00")
            got="ACCEPT" if m.score(c,asof)[0] is not None else "REJECT"
            cls[chapter].append((x,got))
        elif x["kind"]=="event_duplicate":
            got="DUPLICATE" if m.same_event(x["a"],x["b"]) else "DISTINCT"
            dedup.append((x,got))
        else: errors.append(f"{x['id']}: unknown kind {x['kind']}")
    print(f"EDITORIAL_GOLD cases={len(cases)}")
    gate=True
    for ch,rows in cls.items():
        tp=sum(1 for x,g in rows if g=="ACCEPT" and x["expected"]=="ACCEPT")
        fp=sum(1 for x,g in rows if g=="ACCEPT" and x["expected"]=="REJECT")
        fn=sum(1 for x,g in rows if g=="REJECT" and x["expected"]=="ACCEPT")
        precision=tp/(tp+fp) if tp+fp else 1.0
        recall=tp/(tp+fn) if tp+fn else 1.0
        print(f"  {ch}: n={len(rows)} precision={precision:.3f} recall={recall:.3f}")
        if len(rows)<require_minimum:
            print(f"    INSUFFICIENT_GOLD: {len(rows)} < {require_minimum}")
            gate=False
        elif precision<threshold:
            print(f"    PRECISION_GATE_FAIL: {precision:.3f} < {threshold:.3f}")
            gate=False
        for x,g in rows:
            if g!=x["expected"]: errors.append(f"{x['id']}: expected {x['expected']} got {g}")
    if dedup:
        ok=sum(1 for x,g in dedup if g==x["expected"])
        print(f"  event_duplicate: {ok}/{len(dedup)} correct")
        for x,g in dedup:
            if g!=x["expected"]: errors.append(f"{x['id']}: expected {x['expected']} got {g}")
    if errors:
        print("MISMATCHES:")
        for e in errors: print("  -",e)
        gate=False
    ready=all(len(rows)>=10 for rows in cls.values()) and len(cls)>=4
    print("PRECISION_AT_10_READINESS=" + ("READY" if ready else "SEED_CORPUS_INCOMPLETE"))
    return 0 if gate else 1

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--require-minimum",type=int,default=0)
    ap.add_argument("--precision-threshold",type=float,default=.90)
    a=ap.parse_args()
    return evaluate(a.require_minimum,a.precision_threshold)

if __name__=="__main__": sys.exit(main())
