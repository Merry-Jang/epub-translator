#!/bin/bash
# EPUB Translator Studio — 실행 스크립트

set -e

# 가상환경 확인
if [ ! -f "venv/bin/python3" ]; then
    echo "가상환경이 없습니다. 먼저 설치를 실행하세요:"
    echo "  ./install.sh"
    exit 1
fi

echo ""
echo "EPUB Translator Studio 시작 중..."
echo "브라우저에서 http://localhost:8000 을 열어주세요."
echo "(종료: Ctrl+C)"
echo ""

./venv/bin/python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
