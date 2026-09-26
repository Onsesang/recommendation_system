"""Compare ranking settings on the demo searches without calling the LLM.

The search conditions the agent produced in a scenario run (category, want, avoid,
keywords) are replayed through the same search → personalised ranking path the
server uses, once per ranking variant. Holding the model's output fixed isolates
the effect of the ranking weights and costs no API calls.

Each variant is scored automatically first:
  - judged precision: products already labelled in an earlier review (O=1, PARTIAL=0.5, X=0)
  - colour hit rate: top-5 titles naming the requested colour, on searches that asked for one
  - tactile fit: top-5 products whose predictions satisfy every want (>= 0.4) and avoid (< 0.4)

The run writes results.json in the review_app format plus judgments.json pre-filled
with every earlier label, so the review UI only asks about products nobody judged yet.

    python -m shopping_agent.evaluation.ranking_variants \\
        --source shopping_agent/evaluation/results/20260926_step8_regression_mini/results.json \\
        --judgments shopping_agent/evaluation/results/20260926_step4_reco/judgments.json
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from demo_agent.models import SUPPORTED_CATEGORIES, Constraint, StructuredQuery
from recommendation_api.tactile_models import TactileIntent

from shopping_agent.v1.config import AGENT_ROOT, AgentSettings
from shopping_agent.v1.full_catalog import COLOR_TITLE_PATTERNS, title_keywords
from shopping_agent.v1.preferences import COLOR_PATTERNS


DEFAULT_VARIANTS = AGENT_ROOT / "evaluation/ranking_variants.json"
RESULTS_ROOT = AGENT_ROOT / "evaluation/results"
TOP_K = 5
SCORE = {"O": 1.0, "PARTIAL": 0.5, "X": 0.0}


def search_turns(source: dict[str, Any], run: int = 1) -> list[dict[str, Any]]:
    """Search turns of one run: the conditions the agent actually sent to search_products."""
    result = next(item for item in source["results"] if item["run"] == run)
    turns = []
    for row in result["rows"]:
        calls = [call for call in row.get("tool_calls", []) if call["name"] == "search_products"]
        if calls:
            turns.append({"row": row, "arguments": calls[-1]["arguments"]})
    return turns


def rank_turn(app: Any, user_id: str, arguments: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """The server's search path (_ToolTurn.search_products) minus the model and session state."""
    category = arguments.get("category") if arguments.get("category") in SUPPORTED_CATEGORIES else None
    avoid = list(dict.fromkeys(arguments.get("avoid", [])))
    want = [value for value in dict.fromkeys(arguments.get("want", [])) if value not in avoid]
    keywords = [str(value) for value in arguments.get("keywords", []) if str(value).strip()][:8]
    query_text = str(arguments.get("query_text") or "").strip()
    structured = StructuredQuery(
        category=category,
        constraints=tuple(Constraint(value) for value in want),
        negative_constraints=tuple(Constraint(value) for value in avoid),
        source="openai_tool_loop",
        original_message=query_text,
    )
    intent = TactileIntent(category=category, query_text=query_text, desired_more=tuple(want), avoid=tuple(avoid),
                           source="explicit_structured", confidence=0.9)
    pool = int(app.settings.config["ranking"]["candidate_pool_size"])
    search = app.tools.tactile.search(query_text, limit=pool, structured=structured, keywords=keywords)
    ranked = app.ranker.rank(user_id, search["items"], intent=intent, limit=limit)
    return ranked["results"]


def tactile_fit(row: dict[str, Any], want: list[str], avoid: list[str]) -> bool | None:
    predictions = row.get("last2_predictions") or {}
    if not (want or avoid) or not predictions:
        return None
    return all(predictions.get(name, 0.0) >= 0.4 for name in want) and all(
        predictions.get(name, 1.0) < 0.4 for name in avoid
    )


def color_hit(title: str, colors: list[str]) -> bool:
    patterns = [COLOR_TITLE_PATTERNS.get(color, rf"\b{re.escape(color)}\b") for color in colors]
    return bool(re.search("|".join(patterns), title.casefold()))


def product_key(turn_id: str, product_id: str) -> str:
    return f"product|{turn_id}|{product_id}"


def evaluate(variants: list[dict[str, Any]], turns: list[dict[str, Any]], app: Any, user_id: str,
             labels: dict[str, str], limit: int) -> list[dict[str, Any]]:
    tools_config = app.tools.tactile.config
    ranking_config = app.settings.config["ranking"]
    base_tools, base_ranking = copy.deepcopy(tools_config), copy.deepcopy(ranking_config)
    results = []
    for variant in variants:
        # Mutate in place: the index and ranker hold references to these dicts.
        tools_config.clear(); tools_config.update(copy.deepcopy(base_tools))
        tools_config["relevance"].update(variant.get("relevance", {}))
        ranking_config.clear(); ranking_config.update(copy.deepcopy(base_ranking))
        ranking_config.update(variant.get("ranking", {}))
        rows_out, judged, colour, fit = [], [], [], []
        for turn in turns:
            row, arguments = turn["row"], turn["arguments"]
            turn_id = f"{row['scenario']}-{row['turn']}"
            ranked = rank_turn(app, user_id, arguments, limit)
            want, avoid = arguments.get("want", []), arguments.get("avoid", [])
            colors = [word for word in title_keywords(" ".join(arguments.get("keywords", []))) if word in COLOR_PATTERNS]
            for item in ranked[:TOP_K]:
                label = labels.get(product_key(turn_id, item["product_id"]))
                if label in SCORE:
                    judged.append(SCORE[label])
                if colors:
                    colour.append(color_hit(str(item.get("title", "")), colors))
                satisfied = tactile_fit(item, want, avoid)
                if satisfied is not None:
                    fit.append(satisfied)
            rows_out.append({
                "scenario": row["scenario"], "title": row["title"], "turn": row["turn"], "message": row["message"],
                "note": row.get("note", ""), "answer": f"[순위 비교: {variant['name']}] 모델 답변 없음",
                "action": "search_products", "tool_calls": [{"name": "search_products", "arguments": arguments, "ok": True}],
                "latency_seconds": 0.0, "llm_requests": 0, "chars": 0, "sentences": 0,
                "passed": True, "failures": [], "warnings": [],
                "top_products": [
                    {"number": number, "product_id": item["product_id"], "title": item.get("title", ""),
                     "category": item.get("category"), "evidence_source": item.get("tactile_target_source"),
                     "remote_image_url": item.get("remote_image_url"),
                     "tactile_terms": item.get("score_breakdown", {}).get("tactile_terms", [])}
                    for number, item in enumerate(ranked[:10], 1)
                ],
            })
        mean = lambda values: round(sum(values) / len(values), 3) if values else None
        results.append({
            "model": variant["name"], "reasoning_effort": None, "run": 1,
            "description": variant.get("description", ""),
            "metrics": {
                "judged_top5": len(judged), "judged_precision": mean(judged),
                "color_hit_rate": mean([float(value) for value in colour]), "color_samples": len(colour),
                "tactile_fit_rate": mean([float(value) for value in fit]), "tactile_samples": len(fit),
            },
            "turns": len(rows_out), "passed": len(rows_out), "rows": rows_out,
        })
    tools_config.clear(); tools_config.update(base_tools)
    ranking_config.clear(); ranking_config.update(base_ranking)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="tool_agent_scenarios results.json")
    parser.add_argument("--run", type=int, default=1, help="which repeat of the source run to replay")
    parser.add_argument("--variants", type=Path, default=DEFAULT_VARIANTS)
    parser.add_argument("--only", nargs="+", help="variant names to include")
    parser.add_argument("--judgments", type=Path, nargs="*", default=[], help="earlier review judgments.json files")
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()

    from shopping_agent.v1.server import AgentApplication  # loads the full catalog

    variants = json.loads(args.variants.read_text(encoding="utf-8"))["variants"]
    if args.only:
        variants = [variant for variant in variants if variant["name"] in args.only]
    labels: dict[str, str] = {}
    carried: dict[str, Any] = {}
    for path in args.judgments:
        for key, item in json.loads(path.read_text(encoding="utf-8")).get("items", {}).items():
            if key.startswith("product|") and item.get("relevance"):
                labels[key] = item["relevance"]
                carried[key] = item
    turns = search_turns(json.loads(args.source.read_text(encoding="utf-8")), args.run)

    temporary = tempfile.TemporaryDirectory()
    settings = replace(AgentSettings.load(), database_path=Path(temporary.name) / "agent.sqlite3",
                       llm_provider="deterministic", openai_api_key="", catalog_mode="full")
    app = AgentApplication(settings)
    user_id = app.auth.register(email="ranking@example.com", password="password123", display_name="순위").user["user_id"]
    # The ranker's exploration term hashes the user id, and a fresh temporary user gets a new id
    # every run. Pin it to a fixed id so repeated runs rank identically and stay comparable.
    exploration = app.ranker._exploration
    app.ranker._exploration = lambda _user, product_id: exploration("ranking-eval-fixed-user", product_id)
    results = evaluate(variants, turns, app, user_id, labels, limit=30)
    temporary.cleanup()

    out_dir = args.out_dir or RESULTS_ROOT / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_ranking")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "scenario_file": str(args.source), "kind": "ranking_variants", "results": results}
    (out_dir / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if carried:
        (out_dir / "judgments.json").write_text(
            json.dumps({"reviewer": "", "carried_from": [str(path) for path in args.judgments], "items": carried},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{'variant':24} {'judged':>7} {'precision':>9} {'color':>7} {'tactile':>8}")
    for result in results:
        metric = result["metrics"]
        print(f"{result['model']:24} {metric['judged_top5']:>7} {str(metric['judged_precision']):>9} "
              f"{str(metric['color_hit_rate']):>7} {str(metric['tactile_fit_rate']):>8}")
    print(out_dir)


if __name__ == "__main__":
    main()
