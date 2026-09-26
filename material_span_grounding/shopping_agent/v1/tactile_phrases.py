"""Turn image-predicted tactile probabilities into plain Korean phrases.

The tool-loop model only ever sees these phrases, never the raw numbers, so it
cannot read "0.81" or a "높음/낮음" grade aloud to a screen-reader user. Ranking
still uses the probabilities; this module is only for what the model is told.
"""

from __future__ import annotations

from typing import Any, Mapping


HIGH = 0.7
MID = 0.4

# (strong, some, not) in plain declarative form, so the model can conjugate and join them
# ("매우 얇고 까끌하지 않아요") instead of copying a fixed "~편" ending into every sentence.
PHRASES: dict[str, tuple[str, str, str]] = {
    "soft": ("부드럽다", "조금 부드럽다", "부드럽지 않다"),
    "firm": ("탄탄하다", "조금 탄탄하다", "탄탄하지 않다"),
    "smooth": ("매끄럽다", "조금 매끄럽다", "매끄럽지 않다"),
    "rough": ("까끌하다", "약간 까끌할 수 있다", "까끌하지 않다"),
    "non_elastic": ("거의 늘어나지 않는다", "조금만 늘어난다", "어느 정도 늘어난다"),
    "elastic": ("잘 늘어난다", "조금 늘어난다", "잘 늘어나지 않는다"),
    "thin": ("얇다", "조금 얇다", "얇지 않다"),
    "thick": ("도톰하다", "조금 도톰하다", "두껍지 않다"),
    "flexible": ("하늘하늘하다", "조금 하늘하늘하다", "하늘하늘하지 않다"),
    "stiff": ("뻣뻣하다", "약간 뻣뻣하다", "뻣뻣하지 않다"),
    "warm": ("따뜻하다", "조금 따뜻하다", "따뜻하지 않다"),
    "cool": ("시원하다", "조금 시원하다", "시원하지 않다"),
    "spongy": ("폭신하다", "조금 폭신하다", "폭신하지 않다"),
    "crisp": ("각이 잘 잡혀 있다", "조금 각이 잡혀 있다", "각이 잡혀 있지 않다"),
}


def phrase(tactile_class: str, probability: float) -> str:
    strong, some, weak = PHRASES[tactile_class]
    value = float(probability)
    return strong if value >= HIGH else some if value >= MID else weak


def phrases(predictions: Mapping[str, float], classes: list[str] | None = None) -> dict[str, str]:
    names = classes if classes is not None else list(predictions)
    return {name: phrase(name, predictions[name]) for name in names if name in predictions and name in PHRASES}


def split_common(products: list[dict[str, str]], size: int = 3) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Phrases shared by the first `size` products, and each product's remaining phrases.

    Answers used to repeat "매우 부드러워요" once per product; handing the shared part over
    separately lets the model say it once ("세 상품 모두 부드러워요") and then only the differences.
    """
    head = products[:size]
    if len(head) < 2:
        return {}, products
    common = {
        name: value for name, value in head[0].items()
        if all(other.get(name) == value for other in head[1:])
    }
    rest = [
        {name: value for name, value in row.items() if name not in common} if index < size else row
        for index, row in enumerate(products)
    ]
    return common, rest


def strongest(predictions: Mapping[str, float], limit: int = 5) -> list[str]:
    """The most pronounced traits, strongest first, as phrases."""
    ranked = sorted((item for item in predictions.items() if item[0] in PHRASES), key=lambda item: -item[1])
    return [phrase(name, value) for name, value in ranked[:limit]]


def _difference(spread: float) -> str:
    if spread < 0.05:
        return "비슷함"
    if spread < 0.15:
        return "조금 차이 남"
    return "뚜렷하게 차이 남"


def compare(items: list[dict[str, Any]], *, min_probability: float = MID) -> dict[str, Any]:
    """Per tactile class: each product's phrase, which one has more of it and how clear the gap is.

    Classes where every product is below `min_probability` are left out; saying that none of
    them is soft adds nothing to a comparison and only lengthens the answer.
    """
    predictions = {str(item["product_id"]): item.get("last2_predictions", {}) for item in items}
    classes: list[str] = []
    for name in PHRASES:
        values = [values[name] for values in predictions.values() if name in values]
        if len(values) == len(predictions) and max(values) >= min_probability:
            classes.append(name)
    comparison = {}
    for name in classes:
        values = {product_id: float(values[name]) for product_id, values in predictions.items()}
        most = max(values, key=values.get)
        spread = max(values.values()) - min(values.values())
        comparison[name] = {
            "phrases": {product_id: phrase(name, value) for product_id, value in values.items()},
            "more": most if spread >= 0.05 else None,
            "difference": _difference(spread),
        }
    return {
        "items": [
            {"product_id": str(item["product_id"]), "title": str(item.get("title", ""))[:120],
             "category": item.get("category")}
            for item in items
        ],
        "comparison": comparison,
    }
