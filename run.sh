# Run app: bash run.sh
#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -f ".venv/bin/activate" ]; then
  echo "Không tìm thấy .venv/bin/activate"
  echo "Hãy tạo virtualenv trước: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

source ".venv/bin/activate"
exec python3 app.py "$@"

