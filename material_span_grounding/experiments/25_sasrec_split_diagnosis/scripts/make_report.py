#!/usr/bin/env python3
"""Render results/*.json into results/report.html (Korean, self-contained)."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common25 as C

R = C.RESULTS
PROTO = {"loo": "사용자별 마지막 (last_out)", "tsp": "세로: 시점 기준 (timestamp)", "uh": "가로: 사용자 분할 (holdout)"}
PROTO_SHORT = {"loo": "last_out", "tsp": "timestamp", "uh": "user holdout"}
DATA = {"all": "전체 상품 학습", "rec": "추천 가능 상품만 학습"}


def load(name):
    return json.loads((R / name).read_text())


def pct(x, d=2):
    return "–" if x is None else f"{100 * x:.{d}f}%"


def num(x, d=4):
    return "–" if x is None else f"{x:.{d}f}"


def ms(values, fmt):
    values = [v for v in values if v is not None]
    if not values:
        return "–"
    if len(values) == 1:
        return fmt(values[0])
    return f"{fmt(float(np.mean(values)))}<span class=sd> ±{fmt(float(np.std(values, ddof=1)))}</span>"


def table(head, rows, cls=""):
    th = "".join(f"<th>{h}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def main() -> int:
    summary = load("summary.json")
    stats = load("split_stats.json")
    factors = load("factor_stats.json")
    knn = load("content_knn.json")
    union = load("union_candidates.json")
    ml = load("sanity_ml1m.json")
    same = load("same_cohort_data_scope.json")
    v5 = json.loads((R / "runs_recipe_v5/loo-all-bce-s20260917.json").read_text())
    lr_path = R / "runs/loo-all-bce-lr3e-4-s20260917.json"
    lr3 = json.loads(lr_path.read_text()) if lr_path.exists() else None

    groups = defaultdict(list)
    for row in summary["rows"]:
        if "lr3e-4" in row["tag"]:
            continue
        groups[(row["protocol"], row["data"], row["loss"])].append(row)
    detail = summary["detail"]

    def g(p, d, l, key):
        return [r[key] for r in groups[(p, d, l)]]

    def seed1(p, d, l):
        tags = [r["tag"] for r in groups[(p, d, l)] if r["seed"] == C.SEED]
        return detail[tags[0]]

    n_seeds = min(len(v) for v in groups.values())

    main_rows, chart = [], []
    for d in ("all", "rec"):
        for p in ("loo", "tsp", "uh"):
            rows = groups[(p, d, "bce")]
            ci = seed1(p, d, "bce")["rec_view"]["R@500_minus_pop_ci"]
            diff = float(np.mean(g(p, d, "bce", "R@500"))) - rows[0]["pop_R@500"]
            verdict = ("차이 없음" if ci[0] <= 0 <= ci[1] else ("인기도보다 높음" if ci[0] > 0 else "인기도보다 낮음"))
            main_rows.append([
                f"<b>{PROTO_SHORT[p]}</b><br><span class=sub>{DATA[d]}</span>",
                f"{rows[0]['users']:,}",
                pct(rows[0]["warm%"] / 100, 1),
                ms(g(p, d, "bce", "R@10"), pct),
                ms(g(p, d, "bce", "NDCG@10"), num),
                ms(g(p, d, "bce", "R@500"), pct),
                pct(rows[0]["pop_R@500"]),
                f"{diff * 100:+.2f}%p<br><span class=sub>[{100 * ci[0]:+.2f}, {100 * ci[1]:+.2f}] {verdict}</span>",
                ms(g(p, d, "bce", "warm_R@500"), lambda x: pct(x, 1)),
                ms(g(p, d, "bce", "cold_R@500"), lambda x: pct(x, 1)),
            ])
            chart.append({"label": f"{PROTO_SHORT[p]} · {'전체 학습' if d == 'all' else '추천가능만 학습'}",
                          "sasrec": float(np.mean(g(p, d, "bce", "R@500"))),
                          "pop": rows[0]["pop_R@500"], "users": rows[0]["users"]})
    main_table = table(["설정", "평가 사용자", "warm 정답", "SASRec R@10", "SASRec NDCG@10",
                        "SASRec R@500", "인기도 R@500", "SASRec − 인기도<br>(R@500, 95% CI)",
                        "warm 정답<br>R@500", "cold 정답<br>R@500"], main_rows, "num")

    loo_all = groups[("loo", "all", "bce")]
    loo_rec = groups[("loo", "rec", "bce")]
    scope_rows = [
        ["기존 (exp24와 같은 조건)", "모든 정답 (액세서리·신발 포함)", "전체 825,869개",
         f"{stats['loo-all']['test']['users']:,}",
         ms([r["main_R@500(all targets)"] for r in loo_all], pct), ms([r["main_NDCG@10(all targets)"] for r in loo_all], num)],
        ["정답 범위 수정", "추천 가능 상품 정답만", "추천 가능 483,779개", f"{loo_all[0]['users']:,}",
         ms([r["R@500"] for r in loo_all], pct), ms([r["NDCG@10"] for r in loo_all], num)],
        ["정답 + 학습 데이터 수정", "추천 가능 상품 정답만", "추천 가능 483,779개", f"{loo_rec[0]['users']:,}",
         ms([r["R@500"] for r in loo_rec], pct), ms([r["NDCG@10"] for r in loo_rec], num)],
    ]
    scope_table = table(["조건", "정답", "순위를 매기는 상품", "평가 사용자", "SASRec R@500", "SASRec NDCG@10"],
                        scope_rows, "num")

    split_rows = []
    for p in ("loo", "tsp", "uh"):
        s = stats[f"{p}-all"]
        split_rows.append([f"<b>{PROTO[p]}</b>", f"{s['train_events']:,}", f"{s['train_pairs']:,}",
                           f"{s['trainable_items_for_test_model']:,}", f"{s['test']['users']:,}",
                           f"{s['test']['mean_history']:.1f}", pct(s["test"]["target_warm_rate"], 1),
                           pct(1 - s["test"]["target_recommendable_rate"], 1)])
    split_table = table(["자르는 방식", "학습 이벤트", "학습 쌍<br>(다음 상품)", "학습되는 상품", "test 사용자",
                         "평균 이력", "warm 정답", "추천 불가 정답"], split_rows, "num")

    loss_rows = []
    for d in ("all", "rec"):
        for p in ("loo", "tsp", "uh"):
            loss_rows.append([f"{PROTO_SHORT[p]} · {'전체 학습' if d == 'all' else '추천가능만 학습'}",
                              ms(g(p, d, "bce", "R@500"), pct), ms(g(p, d, "ce", "R@500"), pct),
                              ms(g(p, d, "bce", "NDCG@10"), num), ms(g(p, d, "ce", "NDCG@10"), num)])
    loss_table = table(["설정", "BCE R@500", "CE R@500", "BCE NDCG@10", "CE NDCG@10"], loss_rows, "num")

    union_rows = []
    for p in ("loo", "tsp", "uh"):
        u = union[p]
        union_rows.append([f"<b>{PROTO_SHORT[p]}</b>", pct(u["sasrec@500"]["all"]), pct(u["popularity@500"]["all"]),
                           pct(u["content@500"]["all"]), pct(u["content@500"]["cold"]),
                           f"<b>{pct(u['sasrec@250+content@250']['all'])}</b>"])
    union_table = table(["split", "SASRec 500개", "인기도 500개", "이미지 kNN 500개", "이미지 kNN<br>cold 정답만",
                         "SASRec 250 +<br>이미지 kNN 250"], union_rows, "num")

    hist_rows = []
    for b, v in seed1("loo", "all", "bce")["rec_view_by_history"].items():
        hist_rows.append([f"{b}개", f"{v['users']:,}", pct(v.get("R@500")), pct(v.get("pop_R@500")),
                          num(v.get("NDCG@10"))])
    hist_table = table(["이력 길이", "사용자", "SASRec R@500", "인기도 R@500", "SASRec NDCG@10"], hist_rows, "num")

    fl = factors["loo-all"]
    tc = fl["target_train_count_share"]
    ctx = {
        "N_SEEDS": str(n_seeds),
        "MAIN_TABLE": main_table, "SCOPE_TABLE": scope_table, "SPLIT_TABLE": split_table,
        "LOSS_TABLE": loss_table, "UNION_TABLE": union_table, "HIST_TABLE": hist_table,
        "CHART_DATA": json.dumps(chart, ensure_ascii=False),
        "ML_FULL_HR": f"{ml['test_full_ranking']['HR@10']:.3f}", "ML_FULL_NDCG": f"{ml['test_full_ranking']['NDCG@10']:.3f}",
        "ML_S_HR": f"{ml['test_100_sampled']['HR@10']:.3f}", "ML_S_NDCG": f"{ml['test_100_sampled']['NDCG@10']:.3f}",
        "V5_NDCG": num(v5["sasrec"]["main"]["NDCG@10"]), "V5_R500": pct(v5["sasrec"]["main"]["Recall@500"]),
        "V1_NDCG": num(float(np.mean([r["main_NDCG@10(all targets)"] for r in loo_all]))),
        "V1_R500": pct(float(np.mean([r["main_R@500(all targets)"] for r in loo_all]))),
        "LR3_NDCG": num(lr3["sasrec"]["main"]["NDCG@10"]) if lr3 else "–",
        "LR3_R500": pct(lr3["sasrec"]["main"]["Recall@500"]) if lr3 else "–",
        "LR3_EPOCH": str(lr3["best_epoch"]) if lr3 else "–",
        "COLD_LOO": pct(fl["target_cold"], 1), "TC0": pct(tc["0"], 1),
        "RELIST": pct(fl["cold_target_with_warm_same_title"], 1),
        "CAT_SHIFT": pct(1 - fl["target_category_in_history"], 1),
        "LEAK": pct(fl["train_events_after_target_mean_share"], 1),
        "OVERLAP": ms([r["overlap"] for r in loo_all], lambda x: pct(x, 0)),
        "OVERLAP_UH": ms(g("uh", "all", "bce", "overlap"), lambda x: pct(x, 0)),
        "KNN_COLD": pct(knn["loo-all"]["cold"]["R@500"], 1),
        "UNION_LOO": pct(union["loo"]["sasrec@250+content@250"]["all"]),
        "SAS_LOO": pct(union["loo"]["sasrec@500"]["all"]),
        "REC_R500": pct(float(np.mean([r["R@500"] for r in loo_all]))),
        "SCOPE_DIFF": f"{100 * (np.mean([r['R@500'] for r in loo_all]) - np.mean([r['main_R@500(all targets)'] for r in loo_all])):+.2f}%p",
        "UNION_GAIN": f"{100 * (union['loo']['sasrec@250+content@250']['all'] / union['loo']['sasrec@500']['all'] - 1):.0f}%",
        "UNION_GAIN_UH": f"{100 * (union['uh']['sasrec@250+content@250']['all'] / union['uh']['sasrec@500']['all'] - 1):.0f}%",
        "SAME_N": f"{int(same['loo']['n']):,}", "SAME_ALL": pct(same["loo"]["all_model"]),
        "SAME_REC": pct(same["loo"]["rec_model"]), "SAME_POP": pct(same["loo"]["pop_all"]),
    }
    page = Path(__file__).with_name("report_template.html").read_text()
    for k, v in ctx.items():
        page = page.replace("{{" + k + "}}", v)
    assert "{{" not in page, page[page.index("{{"):page.index("{{") + 40]
    (R / "report.html").write_text(page)
    print("wrote", R / "report.html", len(page), "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
