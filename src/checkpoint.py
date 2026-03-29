"""체크포인트 저장/로드 모듈 — atomic write로 크래시 안전성 확보."""

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def save_progress(checkpoint_path: str, data: dict) -> None:
    """
    체크포인트 데이터를 atomic write로 저장한다.

    1. 디렉토리가 없으면 자동 생성
    2. tempfile로 임시 파일에 JSON 쓰기
    3. os.replace()로 원자적 치환
    """
    path = Path(checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 같은 디렉토리에 임시 파일 생성 (os.replace 원자성 보장)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        suffix=".tmp",
        prefix=".checkpoint_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(path))
        logger.debug("체크포인트 저장: %s", checkpoint_path)
    except Exception:
        # 임시 파일 정리
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def load_progress(checkpoint_path: str) -> dict | None:
    """
    체크포인트 파일을 로드한다.

    Returns:
        체크포인트 딕셔너리. 파일 없으면 None.
    """
    path = Path(checkpoint_path)
    if not path.exists():
        logger.debug("체크포인트 파일 없음: %s", checkpoint_path)
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("체크포인트 로드: %s (완료 %d/%d 청크)",
                     checkpoint_path,
                     data.get("completed_chunks", 0),
                     data.get("total_chunks", 0))
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("체크포인트 파일 손상: %s — %s", checkpoint_path, e)
        return None
