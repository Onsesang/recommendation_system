from __future__ import annotations

from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from .agent_tools import TOOL_DEFINITIONS
from .contracts import AgentToolCall


class LocalConversationRouter:
    """Config-trained fallback model; no keyword or exact-message branches."""

    def __init__(self, config: dict[str, Any]) -> None:
        routing = config["conversation_routing"]
        examples = routing["training_examples"]
        allowed = {str(item["name"]) for item in TOOL_DEFINITIONS}
        texts: list[str] = []
        labels: list[str] = []
        for label, rows in examples.items():
            if label not in allowed:
                raise ValueError(f"Unknown routing training label: {label}")
            if not isinstance(rows, list) or not rows:
                raise ValueError(f"Routing examples must be a non-empty list: {label}")
            texts.extend(str(row) for row in rows)
            labels.extend([label] * len(rows))
        if set(labels) != allowed:
            raise ValueError("Routing examples must cover every registered conversation tool")
        self.model: Pipeline = Pipeline(
            [
                (
                    "features",
                    TfidfVectorizer(
                        analyzer="char_wb",
                        ngram_range=(2, 5),
                        lowercase=True,
                        sublinear_tf=True,
                    ),
                ),
                (
                    "classifier",
                    LogisticRegression(
                        C=float(routing.get("fallback_classifier_c", 8.0)),
                        class_weight="balanced",
                        max_iter=1000,
                        random_state=17,
                    ),
                ),
            ]
        )
        self.model.fit(texts, labels)

    def select(self, message: str) -> AgentToolCall:
        probabilities = self.model.predict_proba([message])[0]
        classifier: LogisticRegression = self.model.named_steps["classifier"]
        best = int(probabilities.argmax())
        name = str(classifier.classes_[best])
        arguments = {"query_text": message} if name == "search_products" else {}
        return AgentToolCall(
            name=name,
            arguments=arguments,
            source="local_intent_model",
            confidence=float(probabilities[best]),
        )

