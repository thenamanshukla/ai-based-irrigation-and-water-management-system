#!/bin/bash
# Exports Llama 3.2 1B Instruct to an ExecuTorch file for the Raspberry Pi 5.
# 4-bit weights with 8-bit activations (8da4w), XNNPACK backend; on the Pi, XNNPACK uses Arm KleidiAI kernels.
# Run on the Mac:  bash tools/llama/export_on_mac.sh
# Needs: Python 3.12, a Hugging Face token with access to meta-llama/Llama-3.2-1B-Instruct, ~8 GB free disk.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$HOME/llama-export"
mkdir -p "$WORK" && cd "$WORK"

if [ ! -d venv ]; then
  python3.12 -m venv venv
fi
source venv/bin/activate
pip install -q --upgrade pip
pip install -q executorch==1.5.0 torch==2.14.0 huggingface_hub

if [ ! -f Llama-3.2-1B-Instruct/original/consolidated.00.pth ]; then
  echo "Paste your Hugging Face READ token when asked (it is not shown):"
  hf auth login
  hf download meta-llama/Llama-3.2-1B-Instruct --include "original/*" --local-dir Llama-3.2-1B-Instruct
fi

python -m executorch.extension.llm.export.export_llm \
  --config "$HERE/llama_xnnpack.yaml" \
  +base.model_class=llama3_2 \
  +base.checkpoint="$WORK/Llama-3.2-1B-Instruct/original/consolidated.00.pth" \
  +base.params="$WORK/Llama-3.2-1B-Instruct/original/params.json" \
  +export.max_seq_length=1024 +export.max_context_length=1024 \
  +export.output_name="$WORK/model.pte"

cp Llama-3.2-1B-Instruct/original/tokenizer.model "$WORK/tokenizer.model"
ls -lh "$WORK/model.pte" "$WORK/tokenizer.model"
echo
echo "Done. Copy to the Pi with:"
echo "  scp $WORK/model.pte $WORK/tokenizer.model pi@irrigation.local:~/llama/"
