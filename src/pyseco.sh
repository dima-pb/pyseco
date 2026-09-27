#!/bin/sh
# Starts the controller in the background. Uses the project venv (../.venv) if it exists.
cd "$(dirname "$0")" || exit 1
PYTHON=../.venv/bin/python
[ -x "$PYTHON" ] || PYTHON=python3
"$PYTHON" pyseco.py </dev/null >pyseco.log 2>&1 &
