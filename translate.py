#!/usr/bin/env python3
"""킨들 영문 EPUB → 한국어 번역 CLI 파이프라인."""

import argparse
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from src.epub_parser import parse_epub
from src.chunker import chunk_chapter
from src.providers import LLMClient, DEFAULT_MODELS
from src.translator import translate_chunk, TranslationError
from src.checkpoint import save_progress, load_progress
from src.epub_builder import build_epub

logger = logging.getLogger(__name__)


def _check_server(endpoint: str) -> bool:
    """MLX-LM 로컬 서버 연결을 확인한다."""
    import httpx
    try:
        resp = httpx.get(f"{endpoint}/models", timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False


def _map_translation_to_blocks(
    translated_text: str,
    chunk,
) -> dict[int, str]:
    """
    translate_chunk() 반환값을 block_index → translated_text 매핑으로 변환한다.

    1. \\n\\n으로 분할
    2. 분할 수 == block_indices 수 → 1:1 매핑
    3. 불일치 시:
       - 블록 1개 → 전체 텍스트 할당
       - 블록 여러 개 → 첫 블록에 합치고 나머지 빈 문자열
    """
    parts = translated_text.split("\n\n")
    result = {}

    if len(parts) == len(chunk.block_indices):
        # 1:1 매핑
        for idx, block_index in enumerate(chunk.block_indices):
            result[block_index] = parts[idx]
    elif len(chunk.block_indices) == 1:
        # 블록 1개 — 전체 텍스트 할당
        result[chunk.block_indices[0]] = translated_text
    else:
        # 불일치 — 전체를 첫 블록에 합침
        logger.warning("WARNING: Paragraph count mismatch in %s — "
                       "expected %d, got %d. Merging to first block.",
                       chunk.id, len(chunk.block_indices), len(parts))
        result[chunk.block_indices[0]] = translated_text
        for block_index in chunk.block_indices[1:]:
            result[block_index] = ""

    return result


def _build_translated_chapters(
    checkpoint_data: dict,
    all_chunks: list,
) -> dict[str, dict[int, str]]:
    """
    체크포인트의 완료된 청크들을 build_epub()이 요구하는 구조로 조립한다.

    Returns:
        {chapter_id: {block_index: translated_html}}
    """
    translated_chapters: dict[str, dict[int, str]] = defaultdict(dict)

    # chunk id → Chunk 객체 매핑
    chunks_by_id = {c.id: c for c in all_chunks}

    chunk_data = checkpoint_data.get("chunks", {})

    for chunk_id, info in chunk_data.items():
        if info.get("status") != "done":
            continue

        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue

        translated_text = info.get("translated", "")
        if not translated_text:
            continue

        block_map = _map_translation_to_blocks(translated_text, chunk)
        translated_chapters[chunk.chapter_id].update(block_map)

    return dict(translated_chapters)


def run_pipeline(
    input_path: str,
    output_path: str,
    model: str,
    checkpoint_path: str,
    resume: bool,
    max_words: int,
    client: LLMClient,
) -> None:
    """
    번역 파이프라인 메인 루프.

    1. parse_epub() → chapters
    2. chunk_chapter() → all_chunks
    3. checkpoint 로드/초기화
    4. 각 chunk 번역 + checkpoint 저장
    5. build_epub() → 출력 파일
    """
    start_time = time.time()

    # 출력 경로 안전성 확인 (리뷰 #7)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        logger.warning("출력 파일이 이미 존재하며 덮어씌워집니다: %s", output_path)

    # 1. EPUB 파싱
    logger.info("EPUB 파싱 시작: %s", input_path)
    chapters = parse_epub(input_path)

    if not chapters:
        logger.error("파싱된 챕터가 없습니다.")
        return

    # 2. 청크 분할
    all_chunks = []
    for chapter in chapters:
        chunks = chunk_chapter(chapter, max_words=max_words)
        all_chunks.extend(chunks)

    total_chunks = len(all_chunks)
    logger.info("총 %d 챕터, %d 청크 생성", len(chapters), total_chunks)

    # 3. 체크포인트 로드 또는 초기화
    checkpoint_data = None
    if resume:
        checkpoint_data = load_progress(checkpoint_path)

    if checkpoint_data is None:
        # 초기 체크포인트 생성
        checkpoint_data = {
            "source": input_path,
            "model": model,
            "max_words": max_words,
            "started_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "total_chunks": total_chunks,
            "completed_chunks": 0,
            "failed_chunks": 0,
            "chapters": {},
            "chunks": {},
        }

        # 챕터 정보 초기화
        for chapter in chapters:
            checkpoint_data["chapters"][chapter.id] = {
                "title": chapter.title,
                "total_blocks": len(chapter.text_blocks),
                "status": "pending",
            }

        # 청크 정보 초기화
        for chunk in all_chunks:
            checkpoint_data["chunks"][chunk.id] = {
                "status": "pending",
                "block_indices": chunk.block_indices,
            }

        save_progress(checkpoint_path, checkpoint_data)
    else:
        # --resume 시 max_words 변경 경고 (리뷰 #4)
        saved_max_words = checkpoint_data.get("max_words")
        if saved_max_words and saved_max_words != max_words:
            logger.warning(
                "WARNING: Checkpoint was created with max_words=%d, current value is %d. "
                "Chunk IDs may not match. Use --max-words %d to resume correctly, "
                "or delete checkpoint to restart.",
                saved_max_words, max_words, saved_max_words,
            )

    # 4. 번역 루프
    completed = checkpoint_data.get("completed_chunks", 0)
    failed = checkpoint_data.get("failed_chunks", 0)

    # tqdm 진행률 표시
    pbar = tqdm(total=total_chunks, initial=completed, desc="번역 진행", unit="chunk")

    for chunk in all_chunks:
        chunk_info = checkpoint_data["chunks"].get(chunk.id, {})
        status = chunk_info.get("status", "pending")

        # 완료된 청크 스킵
        if status == "done":
            continue

        # resume 모드가 아닌데 failed 상태면 스킵
        if status == "failed" and not resume:
            continue

        try:
            translated_text = translate_chunk(
                chunk=chunk,
                client=client,
                model=model,
            )

            # 번역 성공
            checkpoint_data["chunks"][chunk.id] = {
                "status": "done",
                "block_indices": chunk.block_indices,
                "translated": translated_text,
            }
            completed += 1
            checkpoint_data["completed_chunks"] = completed

        except TranslationError as e:
            logger.warning("번역 실패: %s", e)
            checkpoint_data["chunks"][chunk.id] = {
                "status": "failed",
                "block_indices": chunk.block_indices,
                "error": str(e),
                "retry_count": e.retry_count,
            }
            failed += 1
            checkpoint_data["failed_chunks"] = failed

        # 매 청크 완료 시 체크포인트 저장
        checkpoint_data["updated_at"] = datetime.now().isoformat()
        save_progress(checkpoint_path, checkpoint_data)
        pbar.update(1)

    pbar.close()

    # 챕터 상태 업데이트
    for chapter in chapters:
        chapter_chunks = [c for c in all_chunks if c.chapter_id == chapter.id]
        statuses = [checkpoint_data["chunks"].get(c.id, {}).get("status") for c in chapter_chunks]
        if all(s == "done" for s in statuses):
            checkpoint_data["chapters"][chapter.id]["status"] = "done"
        elif any(s == "failed" for s in statuses):
            checkpoint_data["chapters"][chapter.id]["status"] = "partial"
        else:
            checkpoint_data["chapters"][chapter.id]["status"] = "in_progress"

    save_progress(checkpoint_path, checkpoint_data)

    # 5. EPUB 빌드
    logger.info("EPUB 빌드 시작...")
    translated_chapters = _build_translated_chapters(checkpoint_data, all_chunks)
    build_epub(input_path, translated_chapters, output_path)

    # 최종 통계
    elapsed = time.time() - start_time
    logger.info("=" * 50)
    logger.info("번역 완료!")
    logger.info("  소요 시간: %.1f초 (%.1f분)", elapsed, elapsed / 60)
    logger.info("  완료 청크: %d / %d", completed, total_chunks)
    if failed > 0:
        logger.info("  실패 청크: %d (--resume로 재시도 가능)", failed)
    logger.info("  출력 파일: %s", output_path)


def main():
    """CLI 인터페이스."""
    parser = argparse.ArgumentParser(
        description="킨들 영문 EPUB을 한국어로 번역합니다.",
    )
    parser.add_argument("input", help="입력 EPUB 파일 경로")
    parser.add_argument("--output", help="출력 EPUB 경로 (기본: input_kr.epub)")
    parser.add_argument(
        "--provider",
        choices=["local", "openai", "claude"],
        default="local",
        help="번역 엔진 선택: local(MLX-LM), openai, claude (기본: local)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="모델 이름 (기본: 프로바이더별 자동 선택)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API 키 (미입력 시 OPENAI_API_KEY / ANTHROPIC_API_KEY 환경변수 사용)",
    )
    parser.add_argument("--checkpoint", help="체크포인트 파일 경로")
    parser.add_argument("--resume", action="store_true", help="기존 체크포인트에서 이어하기")
    parser.add_argument(
        "--max-words",
        type=int,
        default=800,
        help="청크당 최대 단어 수 (기본: 800)",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="로컬 서버 엔드포인트 (기본: http://localhost:8080/v1, --provider=local 전용)",
    )

    args = parser.parse_args()

    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # 입력 파일 확인
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("입력 파일을 찾을 수 없습니다: %s", args.input)
        sys.exit(1)

    if not input_path.suffix.lower() == ".epub":
        logger.error("EPUB 파일만 지원합니다: %s", args.input)
        sys.exit(1)

    # 출력 경로
    output_path = args.output or str(input_path.with_stem(f"{input_path.stem}_kr"))

    # 체크포인트 경로
    checkpoint_path = args.checkpoint or f"checkpoints/{input_path.stem}_progress.json"

    # 모델 기본값
    model = args.model or DEFAULT_MODELS[args.provider]

    # LLM 클라이언트 생성
    endpoint = args.endpoint or ("http://localhost:8080/v1" if args.provider == "local" else None)
    try:
        client = LLMClient(provider=args.provider, api_key=args.api_key, endpoint=endpoint)
    except Exception as e:
        logger.error("클라이언트 초기화 실패: %s", e)
        sys.exit(1)

    # 로컬 서버 연결 확인 (cloud 프로바이더는 스킵)
    if args.provider == "local" and not client.check_connection():
        logger.error(
            "ERROR: MLX-LM 서버에 연결할 수 없습니다 (%s)\n"
            "서버를 먼저 시작하세요: mlx_lm.server --model %s --port 8080",
            endpoint,
            model,
        )
        sys.exit(1)

    logger.info("프로바이더: %s / 모델: %s", args.provider, model)

    run_pipeline(
        input_path=str(input_path),
        output_path=output_path,
        model=model,
        checkpoint_path=checkpoint_path,
        resume=args.resume,
        max_words=args.max_words,
        client=client,
    )


if __name__ == "__main__":
    main()
