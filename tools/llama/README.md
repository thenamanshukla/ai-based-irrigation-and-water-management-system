# Llama assistant on the Raspberry Pi 5 (Arm CPU, ExecuTorch)

The phone app's **Ask** tab sends the farmer's question to `POST /api/ask` on the Pi.
The hub adds its own facts (today's plan, tank, soil, rain, pipe check, alerts) and runs
**Llama 3.2 1B Instruct** with **ExecuTorch 1.5** on the Pi's 4x Arm Cortex-A76 cores.
Weights are 4-bit, activations 8-bit (8da4w); XNNPACK runs the model and uses Arm **KleidiAI**
kernels on the Cortex-A76 (dot-product instructions). No internet is needed at run time.
The model only explains. It cannot open or close the valve.

## Files on the Pi (`~/llama`)

| File | From |
|---|---|
| `llama_main`, `libllama_runner.so` | ExecuTorch 1.5 runner, cross-compiled for Pi 5 (`-march=armv8.2-a+dotprod+fp16 -mtune=cortex-a76`, KleidiAI on) |
| `model.pte` | `export_on_mac.sh` (about 1 GB) |
| `tokenizer.model` | Llama 3.2 1B Instruct (`original/tokenizer.model`) |

## Steps

1. Mac: `bash tools/llama/export_on_mac.sh` (needs Python 3.12 and Hugging Face access to `meta-llama/Llama-3.2-1B-Instruct`).
2. Mac: `scp ~/llama-export/model.pte ~/llama-export/tokenizer.model pi@irrigation.local:~/llama/`
3. Pi: `sudo systemctl restart irrigation-api`, then `curl localhost:8080/api/health` shows `"assistant": true`.

Test on the Pi without the app:

```bash
curl -s -X POST localhost:8080/api/ask -d '{"question":"Should I water today?","lang":"en"}'
```

The reply includes `seconds` and `speed.decode` (tokens per second on the Arm CPU).
Settings (`service` in `settings.json`): `llm_dir` (default `/home/pi/llama`), `llm_threads` (4), `llm_max_new_tokens` (160).
