#!/bin/bash
# 킨들 번역기 — 실행 스크립트

set -e

# 가상환경 확인
if [ ! -f "venv/bin/python3" ]; then
    echo "가상환경이 없습니다. 먼저 설치를 실행하세요:"
    echo "  ./install.sh"
    exit 1
fi

echo ""
echo "킨들 번역기 시작 중..."
echo "브라우저에서 http://localhost:7860 이 자동으로 열립니다."
echo "(종료: Ctrl+C)"
echo ""

./venv/bin/python3 app.py "$@"
