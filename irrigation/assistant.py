"""Farmer assistant: Llama 3.2 1B run by ExecuTorch (XNNPACK + KleidiAI) on the Pi's Arm CPU.

The model only explains; it never controls the valve. Every answer is grounded in the hub's own
status (today's decision, tank, soil, alerts), passed to the model as plain facts.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime

MODEL = "model.pte"
TOKENIZER = "tokenizer.model"
RUNNER = "llama_main"

_lock = threading.Lock()          # one generation at a time: the model uses all four cores


def installed(llm_dir: str) -> bool:
    return all(os.path.exists(os.path.join(llm_dir, f)) for f in (RUNNER, MODEL, TOKENIZER))


def facts(status: dict, tank_capacity_l: float) -> str:
    lines = [f"Time now: {status.get('updated')}"]
    f = status.get("field")
    if f:
        try:
            age = (datetime.strptime(status["updated"], "%Y-%m-%d %H:%M:%S")
                   - datetime.strptime(f["time"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
        except (KeyError, ValueError):
            age = 0
        online = status.get("field_online") and age < 30
        lines += [f"Last reading: {f['time']}, {age:.0f} minutes ago ({'field box online' if online else 'field box NOT reporting; values may be old'})",
                  f"Soil moisture: {f['soil_moisture_pct']} %",
                  f"Air temperature: {f['air_temp_c']} C",
                  f"Raining now: {'yes' if f['raining'] else 'no'}",
                  f"Header tank: {f['tank_l']} of {tank_capacity_l} litres",
                  f"Pond: {f['pond_l']} litres",
                  f"Valve: {f['valve']}"]
    else:
        lines.append("No field readings have arrived yet. Soil, tank and weather are unknown.")
    d = status.get("today")
    if d:
        lines.append(f"Today's plan by the hub: {d.get('action')}"
                     + (f", {d.get('minutes')} minutes, about {d.get('litres')} litres" if d.get("action") == "water" else ""))
        if d.get("reasons"):
            lines.append("Reasons: " + "; ".join(d["reasons"]))
        if d.get("days_left") is not None:
            lines.append(f"Stored water lasts about {d['days_left']} days")
    else:
        lines.append("Today's plan has not been made yet.")
    lines.append(f"Pipe check: {status.get('pipe_status')}")
    for a in status.get("alerts", [])[:3]:
        lines.append(f"Alert {a['ts']}: {a['message']}")
    return "\n".join(lines)


def prompt(question: str, lang: str, fact_text: str) -> str:
    language = "Hindi (Devanagari script)" if lang == "hi" else "simple English"
    system = (
        "You are the assistant of a small farm's drip irrigation system. "
        f"Answer in {language}, in at most four short sentences a farmer can understand. "
        "Use only the facts below for anything about this farm; never invent numbers. "
        "If a fact is unknown, say so. The hub decides watering and enforces safety; "
        "you cannot open or close the valve, but you can tell the farmer to use the Water tab.\n\n"
        "Facts from the hub:\n" + fact_text)
    return ("<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n" + system +
            "<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n" + question.strip() +
            "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n")


def _clean(stdout: str) -> str:
    text = stdout.split("<|start_header_id|>assistant<|end_header_id|>")[-1]
    text = re.split(r"<\|eot_id\|>|<\|end_of_text\|>|PyTorchObserver", text)[0]
    return text.strip()


def _speed(out: str):
    m = re.search(r"PyTorchObserver (\{.*\})", out)
    if not m:
        return None
    try:
        s = json.loads(m.group(1))
        return {"decode": round(s["decode_token_per_sec"], 1), "prefill": round(s["prefill_token_per_sec"], 1),
                "prompt_tokens": s["prompt_tokens"], "generated_tokens": s["generated_tokens"]}
    except (KeyError, ValueError, TypeError):
        return None


def ask(question: str, lang: str, fact_text: str, llm_dir: str, threads: int, max_new: int) -> dict:
    with _lock:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(prompt(question, lang, fact_text))
            pfile = f.name
        env = dict(os.environ, LD_LIBRARY_PATH=llm_dir + ":" + os.environ.get("LD_LIBRARY_PATH", ""))
        t0 = time.monotonic()
        try:
            r = subprocess.run(
                [os.path.join(llm_dir, RUNNER), "--model_path", os.path.join(llm_dir, MODEL),
                 "--tokenizer_path", os.path.join(llm_dir, TOKENIZER), "--prompt_file", pfile,
                 "--temperature", "0", "--max_new_tokens", str(max_new), "--cpu_threads", str(threads)],
                capture_output=True, text=True, timeout=180, env=env)
        finally:
            os.unlink(pfile)
        secs = round(time.monotonic() - t0, 1)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-400:])
    return {"answer": _clean(r.stdout), "seconds": secs, "speed": _speed(r.stdout + r.stderr)}
