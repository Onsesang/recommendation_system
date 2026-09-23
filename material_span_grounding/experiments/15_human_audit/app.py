#!/usr/bin/env python3
"""Single-reviewer, blind-first Streamlit UI for the v3 tactile audit."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from common import ANNOTATION_PATH, CONFIG_PATH, MANIFEST_PATH, read_json
from storage import ensure_annotation_csv, read_annotations, upsert_annotation


OBSERVABILITY_OPTIONS = {
    "Yes — 비교적 판단 가능": "yes",
    "Partial — 어느 정도 추측 가능": "partial",
    "No — 이미지로 판단하기 어려움": "no",
}
HUMAN_LABEL_OPTIONS = {
    "Present — 해당 특성이 있어 보임": "present",
    "Absent — 해당 특성이 없어 보임": "absent",
    "Uncertain — 판단 불확실": "uncertain",
}
REVIEW_LABEL_OPTIONS = {
    "Present evidence": "present_evidence",
    "Absent/opposite evidence": "absent_or_opposite_evidence",
    "Ambiguous": "ambiguous",
    "Not tactile / irrelevant": "not_tactile_irrelevant",
    "Insufficient context": "insufficient_context",
}


def _reverse(mapping: dict[str, str], value: str) -> str | None:
    return next((label for label, stored in mapping.items() if stored == value), None)


def _initial_index(items: list[dict], annotations: dict[str, dict[str, str]]) -> int:
    return next((number for number, item in enumerate(items) if item["item_id"] not in annotations), 0)


def _go_to(index: int, total: int) -> None:
    st.session_state.audit_index = max(0, min(index, total - 1))
    st.rerun()


def _base_annotation(item: dict) -> dict:
    return {
        "item_id": item["item_id"],
        "asin": item["asin"],
        "family_id": item["family_id"],
        "category": item["category"],
        "tactile_class": item["tactile_class"],
        "image_path": item["image_path"],
        "image_missing": item["image_missing"],
        "raw_target": item["raw_target"],
        "binary_target": item["binary_target"],
        "is_fractional_target": item["is_fractional_target"],
        "completed": "true",
    }


def main() -> None:
    st.set_page_config(page_title="Tactile Human Audit", layout="wide")
    if not MANIFEST_PATH.exists():
        st.error("audit_manifest.json이 없습니다. build_audit_manifest.py를 먼저 실행하세요.")
        st.stop()

    manifest = read_json(MANIFEST_PATH)
    config = read_json(CONFIG_PATH)
    items = manifest["items"]
    order = [item["item_id"] for item in items]
    ensure_annotation_csv(ANNOTATION_PATH)
    annotations = read_annotations(ANNOTATION_PATH)

    if "audit_index" not in st.session_state:
        st.session_state.audit_index = _initial_index(items, annotations)
    index = max(0, min(int(st.session_state.audit_index), len(items) - 1))
    item = items[index]
    saved = annotations.get(item["item_id"])
    completed = saved is not None and saved.get("completed", "").lower() == "true"

    completed_count = sum(row.get("completed", "").lower() == "true" for row in annotations.values())
    st.title("Tactile Human Audit")
    st.progress(completed_count / len(items), text=f"{completed_count} / {len(items)} completed")

    st.sidebar.header("Class progress")
    for class_name in config["primary_classes"]:
        class_items = [candidate for candidate in items if candidate["tactile_class"] == class_name]
        done = sum(candidate["item_id"] in annotations for candidate in class_items)
        st.sidebar.write(f"{class_name}: {done} / {len(class_items)}")
    st.sidebar.caption(f"현재 순서: {index + 1} / {len(items)}")

    previous_column, skip_column, unanswered_column = st.columns(3)
    with previous_column:
        if st.button("Previous", disabled=index == 0, use_container_width=True):
            _go_to(index - 1, len(items))
    with skip_column:
        if st.button("Skip", use_container_width=True):
            _go_to(index + 1 if index + 1 < len(items) else 0, len(items))
    with unanswered_column:
        unanswered_index = next(
            (number for number in range(index + 1, len(items)) if items[number]["item_id"] not in annotations),
            next((number for number, candidate in enumerate(items) if candidate["item_id"] not in annotations), None),
        )
        if st.button("Next unanswered", disabled=unanswered_index is None, use_container_width=True):
            _go_to(int(unanswered_index), len(items))

    # Blind stage: no category, evidence, target, probability, threshold, or prediction appears here.
    st.header(item["tactile_class"].upper())
    st.info(config["class_definitions"][item["tactile_class"]])
    image_path = Path(item["image_path"])
    if item["image_missing"] or not image_path.is_file():
        st.error("IMAGE MISSING")
    else:
        st.image(str(image_path), width=650)

    if not completed:
        with st.form(f"blind-form-{item['item_id']}"):
            observability_display = st.radio(
                "이 이미지 하나만 보고 이 촉감 특성을 어느 정도 판단할 수 있나요?",
                list(OBSERVABILITY_OPTIONS),
                index=None,
            )
            human_display = st.radio(
                "이미지만 보았을 때 이 상품에 해당 tactile property가 있다고 보이나요?",
                list(HUMAN_LABEL_OPTIONS),
                index=None,
            )
            confidence = st.select_slider(
                "Confidence (1 = 거의 확신 없음, 5 = 매우 높음)",
                options=[1, 2, 3, 4, 5],
                value=3,
            )
            note = st.text_area("Optional note", max_chars=500)
            submitted = st.form_submit_button("Save & Next", use_container_width=True)
        if submitted:
            if observability_display is None or human_display is None:
                st.error("관측 가능성과 tactile label을 모두 선택해야 저장할 수 있습니다.")
            else:
                row = _base_annotation(item)
                row.update(
                    {
                        "image_observability": OBSERVABILITY_OPTIONS[observability_display],
                        "human_label": HUMAN_LABEL_OPTIONS[human_display],
                        "confidence": confidence,
                        "note": note.strip(),
                        "review_human_label": "",
                        "review_confidence": "",
                    }
                )
                upsert_annotation(ANNOTATION_PATH, row, order)
                st.session_state[f"just_saved_{item['item_id']}"] = True
                st.rerun()
        st.caption("저장 전에는 reference, pseudo-label, category 및 모델 정보가 공개되지 않습니다.")
        return

    st.success("Blind image judgment saved. 이제 reference/model 정보를 확인할 수 있습니다.")
    with st.expander("Show reference/model info", expanded=bool(st.session_state.pop(f"just_saved_{item['item_id']}", False))):
        st.write(f"Category: `{item['category']}`")
        st.write(f"Review ID: `{item.get('review_id')}` / Span ID: `{item.get('span_id')}`")
        st.markdown("**Original span**")
        st.write(item.get("original_span_text") or "연결된 span 없음")
        st.markdown("**Original review**")
        st.write(item.get("original_review_text") or "연결된 review 없음")
        st.markdown("**Qwen grounding**")
        st.json(
            {
                "class": item.get("qwen_class"),
                "present_absent": item.get("qwen_present_absent"),
                "target_polarity": item.get("qwen_target_polarity"),
                "confidence": item.get("qwen_confidence"),
                "unmappable": item.get("qwen_unmappable"),
            }
        )
        st.markdown("**Target and fixed Last2 result**")
        st.json(
            {
                "raw_target": item["raw_target"],
                "binary_target": item["binary_target"],
                "is_fractional_target": item["is_fractional_target"],
                "last2_probability": item["last2_probability"],
                "development_threshold": item["last2_threshold"],
                "last2_binary_prediction": item["last2_binary_prediction"],
            }
        )

        previous_review_label = _reverse(REVIEW_LABEL_OPTIONS, saved.get("review_human_label", ""))
        review_index = list(REVIEW_LABEL_OPTIONS).index(previous_review_label) if previous_review_label else None
        with st.form(f"review-form-{item['item_id']}"):
            review_display = st.radio(
                "이 review가 해당 tactile property를 실제로 지지한다고 보나요?",
                list(REVIEW_LABEL_OPTIONS),
                index=review_index,
            )
            saved_review_confidence = saved.get("review_confidence", "")
            review_confidence = st.select_slider(
                "Review audit confidence",
                options=[1, 2, 3, 4, 5],
                value=int(saved_review_confidence) if saved_review_confidence else 3,
            )
            save_review = st.form_submit_button("Save review audit")
        if save_review:
            if review_display is None:
                st.error("Review evidence 판단을 선택하세요.")
            else:
                row = dict(saved)
                row.update(_base_annotation(item))
                row["review_human_label"] = REVIEW_LABEL_OPTIONS[review_display]
                row["review_confidence"] = review_confidence
                upsert_annotation(ANNOTATION_PATH, row, order)
                st.success("Review audit saved.")

    next_index = index + 1 if index + 1 < len(items) else 0
    if st.button("Continue to next item", use_container_width=True):
        _go_to(next_index, len(items))


if __name__ == "__main__":
    main()
