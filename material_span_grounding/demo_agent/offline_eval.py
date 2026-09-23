from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import TactileAgent
from .recommender import ExplicitTactileRecommender


QUERIES = (
    "부드러운 니트 추천해줘",
    "얇고 시원한 셔츠 사고 싶어",
    "두껍고 따뜻한 자켓 보여줘",
    "까슬하지 않고 유연한 옷을 추천해줘",
    "신축성 있는 바지를 찾고 있어",
)


def evaluate() -> dict:
    recommender = ExplicitTactileRecommender()
    agent = TactileAgent(recommender)
    rows = []
    for message in QUERIES:
        response = agent.handle({"message": message})
        for product in response["products"]:
            recommender.validate_reason(product)
        query = response["interpreted_query"]
        rows.append(
            {
                "message": message,
                "category": query["category"],
                "positive": [x["tactile_class"] for x in query["constraints"]],
                "negative": [x["tactile_class"] for x in query["negative_constraints"]],
                "candidate_count": response["retrieval"]["candidate_count"],
                "result_count": response["result_count"],
                "all_images_present": all(bool(x["image_url"]) for x in response["products"]),
                "all_reasons_verified": True,
            }
        )
    return {
        "status": "pass" if all(row["result_count"] > 0 for row in rows) else "fail",
        "queries": rows,
        "catalog_last2_items": len(recommender.iids),
        "load_seconds": recommender.load_seconds,
        "mutated_research_artifacts": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate()
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        allowed_root = Path(__file__).resolve().parent
        target = args.output.resolve()
        if not target.is_relative_to(allowed_root):
            raise ValueError("offline evaluation output must stay inside demo_agent/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    print(text, end="")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
