from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shopping_agent.evaluation.pairwise_app import PairwiseApp, build_pairs, summarize


def _row(turn: int, products: list[str]) -> dict:
    return {"scenario": "S", "title": "t", "turn": turn, "message": f"m{turn}", "note": "",
            "tool_calls": [{"name": "search_products", "arguments": {"category": "skirt", "want": ["flexible"]}}],
            "top_products": [{"number": n, "product_id": p, "title": p, "remote_image_url": ""} for n, p in enumerate(products, 1)]}


REPORT = {"results": [
    {"model": "baseline", "rows": [_row(1, ["a", "b", "c", "d"]), _row(2, ["x", "y", "z"])]},
    {"model": "texture", "rows": [_row(1, ["b", "e", "a", "c"]), _row(2, ["y", "x", "z"])]},
]}


class PairwiseTests(unittest.TestCase):
    def test_pairs_only_where_top3_differs_and_sides_are_stable(self) -> None:
        pairs = build_pairs(REPORT, "baseline", ["texture"])
        self.assertEqual([pair["turn"] for pair in pairs], ["S-1"])  # S-2 has the same top-3 set
        pair = pairs[0]
        self.assertEqual({pair["a_is"], pair["b_is"]}, {"baseline", "texture"})
        self.assertEqual(len(pair["a"]), 3)
        self.assertEqual(build_pairs(REPORT, "baseline", ["texture"])[0]["a_is"], pair["a_is"])
        with self.assertRaises(ValueError):
            build_pairs(REPORT, "baseline", ["missing"])

    def test_summary_decodes_blind_choices(self) -> None:
        pairs = build_pairs(REPORT, "baseline", ["texture"])
        pair = pairs[0]
        candidate_side = "A" if pair["a_is"] == "texture" else "B"
        result = summarize(pairs, {pair["id"]: {"choice": candidate_side}}, "baseline")
        self.assertEqual(result["texture"], {"pairs": 1, "judged": 1, "candidate": 1, "baseline": 0, "tie": 0})
        self.assertEqual(summarize(pairs, {pair["id"]: {"choice": "TIE"}}, "baseline")["texture"]["tie"], 1)

    def test_store_validates_and_data_hides_side_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            results = Path(directory) / "results.json"
            results.write_text(json.dumps(REPORT), encoding="utf-8")
            app = PairwiseApp(results, "baseline", ["texture"])
            data = app.data()
            self.assertNotIn("a_is", data["pairs"][0])
            pair_id = data["pairs"][0]["id"]
            app.store.update(pair_id, {"choice": "B", "memo": "B가 더 하늘하늘"}, app.valid)
            for bad in ({"choice": "C"}, {"score": 1}):
                with self.assertRaises(ValueError):
                    app.store.update(pair_id, bad, app.valid)
            with self.assertRaises(KeyError):
                app.store.update("nope", {"choice": "A"}, app.valid)
            saved = json.loads((Path(directory) / "pairwise_judgments.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["items"][pair_id]["choice"], "B")
            self.assertEqual(PairwiseApp(results, "baseline", ["texture"]).summary()["settings"]["texture"]["judged"], 1)


if __name__ == "__main__":
    unittest.main()
