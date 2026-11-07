"""Benchmark translator settings (fp32 vs int8, beams 5/2/1) on a few sentences.
Run from backend/:  python ..\tests\bench_translator.py
"""
import sys, time, os
sys.path.insert(0, os.getcwd())
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
M = "facebook/nllb-200-distilled-600M"
S = ["Hello, I need help with my application form.", "Please bring your identity document to the clinic on Monday.",
     "Where is the nearest clinic?", "The meeting starts at nine in the morning.", "My child is sick and needs a doctor."]
tok = AutoTokenizer.from_pretrained(M); tok.src_lang = "eng_Latn"
t0 = time.perf_counter(); m = AutoModelForSeq2SeqLM.from_pretrained(M).eval(); print(f"fp32 load {time.perf_counter()-t0:.1f}s", flush=True)

def run(model, beams, label):
    outs = []; ts = []
    for s in S:
        x = tok(s, return_tensors="pt"); t0 = time.perf_counter()
        with torch.inference_mode():
            y = model.generate(**x, forced_bos_token_id=tok.convert_tokens_to_ids("zul_Latn"), max_new_tokens=128, num_beams=beams, no_repeat_ngram_size=3, repetition_penalty=1.1)
        ts.append(time.perf_counter() - t0); outs.append(tok.batch_decode(y, skip_special_tokens=True)[0])
    print(f"{label}: mean {sum(ts)/len(ts):.2f}s (first {ts[0]:.2f}s)", flush=True)
    for o in outs: print("   ", o.encode("ascii", "replace").decode(), flush=True)
    return outs

run(m, 1, "fp32 greedy "); run(m, 2, "fp32 beams=2 "); run(m, 5, "fp32 beams=5 ")
q = torch.quantization.quantize_dynamic(m, {torch.nn.Linear}, dtype=torch.qint8)
run(q, 1, "int8 greedy "); run(q, 2, "int8 beams=2 "); run(q, 5, "int8 beams=5 ")
print("DONE", flush=True)
