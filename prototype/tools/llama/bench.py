"""Benchmark Llama 3.2 1B (ExecuTorch, XNNPACK + KleidiAI) on the Raspberry Pi 5.

Run on the Pi:   python3 tools/llama/bench.py
Writes bench_results.json and prints a Markdown table for the report.
Uses the same prompt format and hub facts as the app's Ask tab.
"""
import json
import os
import re
import resource
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from irrigation import assistant  # noqa: E402

LLM = os.environ.get("LLM_DIR", "/home/pi/llama")
FACTS = ("No field readings have arrived yet. Soil, tank and weather are unknown.\n"
         "Today's plan has not been made yet.\nPipe check: not yet checked")
POINT = assistant.key_point({})
QUESTIONS = [("en", "Should I water today?"),
             ("en", "How many days will the stored water last?"),
             ("en", "Why is drip irrigation better than flood irrigation?"),
             ("hi", "क्या आज पानी देना है?"),
             ("hi", "ड्रिप सिंचाई के क्या फायदे हैं?")]


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def temp_c():
    m = re.search(r"([\d.]+)", sh(["vcgencmd", "measure_temp"]))
    return float(m.group(1)) if m else None


def freq_mhz():
    try:
        return int(open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq").read()) // 1000
    except OSError:
        return None


def run(lang, q, threads, max_new=120):
    pf = "/tmp/bench_prompt.txt"
    open(pf, "w").write(assistant.prompt(q, lang, FACTS, POINT))
    env = dict(os.environ, LD_LIBRARY_PATH=LLM)
    t0 = time.monotonic()
    r = subprocess.run([os.path.join(LLM, "llama_main"), "--model_path", os.path.join(LLM, "model.pte"),
                        "--tokenizer_path", os.path.join(LLM, "tokenizer.model"), "--prompt_file", pf,
                        "--temperature", "0", "--max_new_tokens", str(max_new), "--cpu_threads", str(threads)],
                       capture_output=True, text=True, env=env, timeout=300)
    wall = time.monotonic() - t0
    out = r.stdout + r.stderr
    m = re.search(r"PyTorchObserver (\{.*\})", out)
    s = json.loads(m.group(1)) if m else {}
    return {"lang": lang, "question": q, "threads": threads, "wall_s": round(wall, 2),
            "load_s": round((s.get("model_load_end_ms", 0) - s.get("model_load_start_ms", 0)) / 1000, 2),
            "first_token_s": round((s.get("first_token_ms", 0) - s.get("inference_start_ms", 0)) / 1000, 2),
            "prompt_tokens": s.get("prompt_tokens"), "generated_tokens": s.get("generated_tokens"),
            "prefill_tok_s": round(s.get("prefill_token_per_sec", 0), 1),
            "decode_tok_s": round(s.get("decode_token_per_sec", 0), 1),
            "temp_after_c": temp_c(), "freq_after_mhz": freq_mhz(),
            "answer": assistant._clean(r.stdout)[:300], "ok": r.returncode == 0}


def main():
    info = {"model": "Llama 3.2 1B Instruct, 8da4w (int4 weights, int8 dynamic activations), group 128",
            "runtime": "ExecuTorch 1.5, XNNPACK backend, KleidiAI on, -march=armv8.2-a+dotprod+fp16 -mtune=cortex-a76",
            "pte_mb": round(os.path.getsize(os.path.join(LLM, "model.pte")) / 2**20, 1),
            "cpu": sh(["bash", "-c", "lscpu | grep 'Model name' | head -1"]).split(":")[-1].strip(),
            "kernel": sh(["uname", "-r"]), "ram_total_mb": int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**20),
            "temp_idle_c": temp_c(), "throttled_before": sh(["vcgencmd", "get_throttled"])}
    runs = []
    print("Warm-up run...")
    run("en", "Hello", 4, 8)
    for lang, q in QUESTIONS:
        print(f"[4 threads] {q}")
        runs.append(run(lang, q, 4))
    for th in (1, 2):
        print(f"[{th} thread(s)] scaling test")
        runs.append(run("en", QUESTIONS[0][1], th))
    peak_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    info["peak_rss_mb"] = round(peak_kb / 1024, 1)
    info["throttled_after"] = sh(["vcgencmd", "get_throttled"])
    json.dump({"info": info, "runs": runs}, open("bench_results.json", "w"), ensure_ascii=False, indent=2)

    print("\n" + json.dumps(info, indent=2, ensure_ascii=False))
    print("\n| Threads | Lang | Prompt tok | Gen tok | Load s | First token s | Prefill tok/s | Decode tok/s | Total s | Temp C |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in runs:
        print(f"| {r['threads']} | {r['lang']} | {r['prompt_tokens']} | {r['generated_tokens']} | {r['load_s']} | "
              f"{r['first_token_s']} | {r['prefill_tok_s']} | {r['decode_tok_s']} | {r['wall_s']} | {r['temp_after_c']} |")
    print("\nSaved bench_results.json")


if __name__ == "__main__":
    main()
