"""체크포인트 저장/로드 단위 테스트."""

import json
from pathlib import Path

import pytest

from src.checkpoint import save_progress, load_progress


def test_save_and_load_basic(tmp_path):
    """save_progress/load_progress 기본 동작 — 저장한 데이터를 그대로 복원."""
    path = str(tmp_path / "checkpoint.json")
    data = {
        "completed_chunks": 5,
        "total_chunks": 10,
        "translations": {"ch00": {"0": "안녕"}},
    }

    save_progress(path, data)
    loaded = load_progress(path)

    assert loaded == data


def test_save_creates_directory(tmp_path):
    """존재하지 않는 중첩 디렉토리도 자동 생성."""
    nested_path = str(tmp_path / "deep" / "nested" / "checkpoint.json")

    save_progress(nested_path, {"key": "value"})

    assert Path(nested_path).exists()


def test_atomic_write_no_leftover_tmp(tmp_path):
    """atomic write 후 .tmp 임시 파일이 남지 않음."""
    path = str(tmp_path / "checkpoint.json")

    save_progress(path, {"attempt": 1})

    tmp_files = list(tmp_path.glob(".checkpoint_*.tmp"))
    assert len(tmp_files) == 0
    assert Path(path).exists()


def test_save_overwrites_existing(tmp_path):
    """기존 파일을 덮어쓰기 — 마지막 저장 값이 로드됨."""
    path = str(tmp_path / "checkpoint.json")

    save_progress(path, {"version": 1})
    save_progress(path, {"version": 2})

    loaded = load_progress(path)
    assert loaded == {"version": 2}


def test_load_missing_file_returns_none(tmp_path):
    """존재하지 않는 파일 → None 반환."""
    path = str(tmp_path / "nonexistent.json")

    result = load_progress(path)

    assert result is None


def test_load_corrupted_json_returns_none(tmp_path):
    """손상된 JSON 파일 → None 반환 (JSONDecodeError 처리)."""
    path = tmp_path / "corrupted.json"
    path.write_text("{invalid json content", encoding="utf-8")

    result = load_progress(str(path))

    assert result is None


def test_save_and_load_unicode(tmp_path):
    """유니코드(한국어) 데이터 저장/로드."""
    path = str(tmp_path / "checkpoint.json")
    data = {"translations": {"ch00": {"0": "안녕하세요, 세계!"}}}

    save_progress(path, data)
    loaded = load_progress(path)

    assert loaded == data


def test_load_empty_file_returns_none(tmp_path):
    """빈 파일 → None 반환."""
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")

    result = load_progress(str(path))

    assert result is None
