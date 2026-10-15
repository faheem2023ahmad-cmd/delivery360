#!/bin/sh
set -e
exec uvicorn backend:app --host 0.0.0.0 --port "${PORT:-8000}"
