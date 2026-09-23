from __future__ import annotations

from transformers import AutoProcessor
from vllm import LLM, SamplingParams

from material_span.common import ROOT, load_config, read_jsonl
from material_span.extract import _local_model_path, parse_extraction, render_prompt


def main() -> None:
    cfg = load_config()
    model_path = _local_model_path(cfg["model_id"])
    processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
    review = read_jsonl(ROOT / "data" / "input" / "reviews_pilot.jsonl")[0]
    template = (ROOT / "prompts" / "span_extraction_v2_surface.txt").read_text(
        encoding="utf-8"
    )
    prompt = render_prompt(template, review["review_id"], review["text"])
    rendered = processor.apply_chat_template(
        [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        tokenize=False,
        add_generation_prompt=True,
    )
    llm = LLM(
        model=model_path,
        dtype="bfloat16",
        quantization="bitsandbytes",
        load_format="bitsandbytes",
        max_model_len=4096,
        max_num_seqs=32,
        gpu_memory_utilization=0.90,
        enforce_eager=True,
        seed=42,
    )
    output = llm.generate(
        [rendered],
        SamplingParams(temperature=0.0, max_tokens=480, seed=42),
        use_tqdm=False,
    )[0].outputs[0].text.strip()
    parsed = parse_extraction(output, review["review_id"], review["text"], max_items=20)
    print(f"raw={output}")
    print(f"status={parsed['status']} evidence={len(parsed['evidence'])}")


if __name__ == "__main__":
    main()
