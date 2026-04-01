#!/bin/bash
# 킨들 번역기 — 원클릭 설치 스크립트

set -e

echo ""
echo "=================================="
echo "  킨들 영문 EPUB 번역기 설치"
echo "=================================="
echo ""

# Python 버전 확인
if ! command -v python3 &>/dev/null; then
    echo "오류: python3 가 설치되어 있지 않습니다."
    echo "https://www.python.org/downloads/ 에서 Python 3.10+ 설치 후 다시 실행하세요."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
REQUIRED="3.10"

if python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo "Python $PYTHON_VERSION 확인"
else
    echo "오류: Python $REQUIRED 이상이 필요합니다. (현재: $PYTHON_VERSION)"
    exit 1
fi

# 가상환경 생성
if [ -d "venv" ]; then
    echo "기존 가상환경 재사용"
else
    echo "가상환경 생성 중..."
    python3 -m venv venv
fi

# 의존성 설치
echo "패키지 설치 중..."
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q

echo ""
echo "=================================="
echo "  설치 완료!"
echo ""
echo "  실행 방법:"
echo "    ./run.sh"
echo "=================================="
echo ""
