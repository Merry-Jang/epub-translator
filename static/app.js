/**
 * EPUB Translator Studio — Frontend Controller
 *
 * IIFE 모듈 패턴:
 * - State: 현재 앱 상태
 * - API: 서버 통신
 * - UI: DOM 업데이트
 * - SSE: EventSource 관리
 * - Init: 이벤트 바인딩
 */

const App = (() => {
    // ─── State ──────────────────────────────────
    const state = {
        taskId: null,
        eventSource: null,
        status: 'idle', // idle | uploading | running | completed | cancelled | failed
    };

    // ─── DOM References ─────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const dom = {
        // 업로드
        dropZone: $('#drop-zone'),
        fileInput: $('#file-input'),
        fileName: $('#file-name'),

        // 설정
        engineRadios: document.querySelectorAll('input[name="engine"]'),
        apiKeyInput: $('#api-key-input'),
        apiKeySection: $('#api-key-section'),
        endpointInput: $('#endpoint-input'),
        modelInput: $('#model-input'),
        chunkSlider: $('#chunk-slider'),
        chunkValue: $('#chunk-value'),
        resumeCheck: $('#resume-check'),

        // 액션 버튼
        translateBtn: $('#translate-btn'),
        cancelBtn: $('#cancel-btn'),
        downloadBtn: $('#download-btn'),

        // 진행률
        progressCircle: $('#progress-circle'),
        progressText: $('#progress-text'),
        progressDetail: $('#progress-detail'),
        bookTitle: $('#book-title'),

        // 로그
        logContainer: $('#log-container'),

        // 체크포인트
        checkpointList: $('#checkpoint-list'),
    };

    // SVG 원형 프로그레스 둘레 (r=58)
    const CIRCUMFERENCE = 2 * Math.PI * 58;

    // ─── API ────────────────────────────────────
    const api = {
        async startTranslation(formData) {
            const res = await fetch('/api/translate', {
                method: 'POST',
                body: formData,
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || '번역 시작 실패');
            }
            return res.json();
        },

        async cancelTranslation(taskId) {
            const res = await fetch(`/api/cancel/${taskId}`, { method: 'POST' });
            return res.json();
        },

        async getCheckpoints() {
            const res = await fetch('/api/checkpoints');
            return res.json();
        },

        downloadUrl(taskId) {
            return `/api/download/${taskId}`;
        },
    };

    // ─── SSE ────────────────────────────────────
    const sse = {
        connect(taskId) {
            if (state.eventSource) {
                state.eventSource.close();
            }

            let reconnectCount = 0;
            const es = new EventSource(`/api/progress/${taskId}`);
            state.eventSource = es;

            es.addEventListener('progress', (e) => {
                reconnectCount = 0; // 성공적인 이벤트 수신 시 리셋
                const data = JSON.parse(e.data);
                ui.updateProgress(data);
            });

            es.addEventListener('log', (e) => {
                const data = JSON.parse(e.data);
                ui.appendLog(data);
            });

            es.addEventListener('done', (e) => {
                const data = JSON.parse(e.data);
                if (data.status === 'cancelled') {
                    ui.setStatus('cancelled');
                    ui.appendLog({
                        time: _now(),
                        level: 'WARNING',
                        message: '번역이 사용자에 의해 취소되었습니다.',
                    });
                } else {
                    ui.setStatus('completed');
                    ui.appendLog({
                        time: _now(),
                        level: 'INFO',
                        message: '번역이 완료되었습니다! 결과를 다운로드하세요.',
                    });
                }
                es.close();
                state.eventSource = null;
                ui.loadCheckpoints();
            });

            es.addEventListener('error', (e) => {
                // 서버에서 보낸 error 이벤트
                if (e.data) {
                    const data = JSON.parse(e.data);
                    ui.showError(data.error || '알 수 없는 오류가 발생했습니다.');
                }
                ui.setStatus('failed');
                es.close();
                state.eventSource = null;
            });

            // 네트워크 에러 (재연결 5회 제한) [선택 #11]
            es.onerror = () => {
                reconnectCount++;
                if (reconnectCount > 5) {
                    es.close();
                    state.eventSource = null;
                    ui.showError('서버 연결이 불안정합니다. 페이지를 새로고침하세요.');
                    ui.setStatus('failed');
                }
            };
        },
    };

    // ─── UI ─────────────────────────────────────
    const ui = {
        updateProgress(data) {
            const pct = data.total > 0
                ? Math.round((data.completed / data.total) * 100)
                : 0;

            // SVG 원형 프로그레스
            const offset = CIRCUMFERENCE - (pct / 100) * CIRCUMFERENCE;
            dom.progressCircle.style.strokeDashoffset = offset;

            // 텍스트 업데이트
            dom.progressText.textContent = `${pct}%`;
            dom.progressDetail.innerHTML =
                `처리 중인 청크: <span class="text-primary font-bold">#${data.completed} / #${data.total}</span>`;

            if (data.book_title) {
                dom.bookTitle.textContent = data.book_title;
            }

            // 상태 반영
            if (data.status === 'pending') {
                dom.bookTitle.textContent = '대기 중 (다른 번역 진행 중)';
            }
        },

        appendLog(entry) {
            const levelStyles = {
                'INFO':    'bg-primary/10 text-primary',
                'WARNING': 'bg-[#ff9800]/10 text-[#ff9800]',
                'ERROR':   'bg-error/10 text-error',
                'DEBUG':   'bg-outline/10 text-outline',
            };
            const style = levelStyles[entry.level] || levelStyles['INFO'];

            const div = document.createElement('div');
            div.className = "flex gap-3 text-sm font-['Manrope']";
            div.innerHTML = `
                <span class="text-outline-variant font-mono whitespace-nowrap">${_escapeHtml(entry.time)}</span>
                <span class="px-1.5 py-0.5 rounded ${style} text-[10px] font-bold h-fit whitespace-nowrap">[${_escapeHtml(entry.level)}]</span>
                <p class="text-on-surface-variant">${_escapeHtml(entry.message)}</p>`;

            dom.logContainer.insertBefore(div, dom.logContainer.firstChild);

            // 최대 200개 로그 유지 (DOM 메모리 관리)
            while (dom.logContainer.children.length > 200) {
                dom.logContainer.removeChild(dom.logContainer.lastChild);
            }
        },

        setStatus(status) {
            state.status = status;
            const isRunning = (status === 'running' || status === 'uploading');

            // 번역 버튼
            dom.translateBtn.disabled = isRunning;
            if (isRunning) {
                dom.translateBtn.classList.add('opacity-50', 'cursor-not-allowed');
            } else {
                dom.translateBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            }

            // 취소 버튼
            if (isRunning) {
                dom.cancelBtn.classList.remove('hidden');
                dom.cancelBtn.classList.add('flex');
            } else {
                dom.cancelBtn.classList.add('hidden');
                dom.cancelBtn.classList.remove('flex');
            }

            // 다운로드 버튼
            if (status === 'completed') {
                dom.downloadBtn.classList.remove('hidden');
                dom.downloadBtn.classList.add('flex');
            } else {
                dom.downloadBtn.classList.add('hidden');
                dom.downloadBtn.classList.remove('flex');
            }
        },

        showError(message) {
            this.appendLog({
                time: _now(),
                level: 'ERROR',
                message: message,
            });
        },

        async loadCheckpoints() {
            try {
                const { checkpoints } = await api.getCheckpoints();
                if (!checkpoints || checkpoints.length === 0) {
                    dom.checkpointList.innerHTML = `
                        <div class="text-center text-on-surface-variant text-sm py-8">
                            저장된 체크포인트가 없습니다.
                        </div>`;
                    return;
                }

                dom.checkpointList.innerHTML = checkpoints.map(cp => {
                    const pct = cp.total > 0 ? Math.round((cp.completed / cp.total) * 100) : 0;
                    const icon = pct === 100 ? 'check_circle' : 'description';
                    return `
                        <div class="bg-surface-container-high p-4 rounded-xl border border-outline-variant/10 flex items-center gap-4 hover:bg-surface-variant transition-colors cursor-pointer group">
                            <div class="w-12 h-12 rounded-lg bg-surface-container-highest flex items-center justify-center text-primary group-hover:scale-110 transition-transform">
                                <span class="material-symbols-outlined">${icon}</span>
                            </div>
                            <div class="flex-1">
                                <p class="text-sm font-bold text-on-surface">${_escapeHtml(cp.filename || '(unknown)')}</p>
                                <div class="flex items-center gap-2 mt-1">
                                    <div class="flex-1 h-1 bg-surface-container rounded-full overflow-hidden">
                                        <div class="h-full bg-primary/60" style="width:${pct}%"></div>
                                    </div>
                                    <span class="text-[10px] font-bold text-primary">${pct}%</span>
                                </div>
                            </div>
                            <span class="material-symbols-outlined text-outline group-hover:text-primary">chevron_right</span>
                        </div>`;
                }).join('');
            } catch (e) {
                // 체크포인트 로드 실패 시 조용히 무시
            }
        },

        resetProgress() {
            dom.progressCircle.style.strokeDashoffset = CIRCUMFERENCE;
            dom.progressText.textContent = '0%';
            dom.progressDetail.textContent = 'EPUB 파일을 업로드하여 번역을 시작하세요';
            dom.bookTitle.textContent = '대기 중';
            dom.logContainer.innerHTML = '';
        },
    };

    // ─── Helpers ─────────────────────────────────
    function _now() {
        return new Date().toLocaleTimeString('ko-KR', { hour12: false });
    }

    function _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function _getSelectedEngine() {
        for (const radio of dom.engineRadios) {
            if (radio.checked) {
                return radio.value;
            }
        }
        return 'local';
    }

    function _toggleApiKeyField() {
        const engine = _getSelectedEngine();
        if (engine === 'local') {
            dom.apiKeySection.classList.add('hidden');
        } else {
            dom.apiKeySection.classList.remove('hidden');
        }
    }

    // ─── Init ───────────────────────────────────
    function init() {
        // 파일 드래그앤드롭
        dom.dropZone.addEventListener('click', () => dom.fileInput.click());

        dom.dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dom.dropZone.classList.add('border-primary/50');
        });

        dom.dropZone.addEventListener('dragleave', () => {
            dom.dropZone.classList.remove('border-primary/50');
        });

        dom.dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dom.dropZone.classList.remove('border-primary/50');
            if (e.dataTransfer.files.length) {
                dom.fileInput.files = e.dataTransfer.files;
                dom.fileName.textContent = e.dataTransfer.files[0].name;
            }
        });

        dom.fileInput.addEventListener('change', () => {
            if (dom.fileInput.files.length) {
                dom.fileName.textContent = dom.fileInput.files[0].name;
            }
        });

        // 엔진 선택 시 API 키 필드 토글
        dom.engineRadios.forEach(radio => {
            radio.addEventListener('change', _toggleApiKeyField);
        });
        _toggleApiKeyField(); // 초기 상태

        // 청크 슬라이더
        dom.chunkSlider.addEventListener('input', () => {
            dom.chunkValue.textContent = `${Number(dom.chunkSlider.value).toLocaleString()} words`;
        });

        // 번역 시작
        dom.translateBtn.addEventListener('click', async () => {
            if (!dom.fileInput.files.length) {
                ui.showError('EPUB 파일을 선택하세요.');
                return;
            }

            if (state.status === 'running' || state.status === 'uploading') {
                return; // 중복 클릭 방지
            }

            ui.resetProgress();
            ui.setStatus('uploading');

            const formData = new FormData();
            formData.append('file', dom.fileInput.files[0]);
            formData.append('provider', _getSelectedEngine());
            formData.append('api_key', dom.apiKeyInput.value);
            formData.append('endpoint', dom.endpointInput.value);
            formData.append('model', dom.modelInput.value);
            formData.append('max_words', dom.chunkSlider.value);
            formData.append('resume', dom.resumeCheck.checked);

            ui.appendLog({
                time: _now(),
                level: 'INFO',
                message: '파일 업로드 중...',
            });

            try {
                const result = await api.startTranslation(formData);
                state.taskId = result.task_id;
                ui.setStatus('running');
                ui.appendLog({
                    time: _now(),
                    level: 'INFO',
                    message: `번역 작업이 시작되었습니다. (Task: ${result.task_id})`,
                });
                sse.connect(result.task_id);
            } catch (e) {
                ui.showError(e.message);
                ui.setStatus('failed');
            }
        });

        // 취소
        dom.cancelBtn.addEventListener('click', async () => {
            if (state.taskId) {
                try {
                    await api.cancelTranslation(state.taskId);
                    ui.appendLog({
                        time: _now(),
                        level: 'WARNING',
                        message: '취소 신호를 보냈습니다. 현재 청크 완료 후 중단됩니다.',
                    });
                } catch (e) {
                    ui.showError(`취소 실패: ${e.message}`);
                }
            }
        });

        // 다운로드
        dom.downloadBtn.addEventListener('click', () => {
            if (state.taskId) {
                window.location.href = api.downloadUrl(state.taskId);
            }
        });

        // 초기 체크포인트 로드
        ui.loadCheckpoints();
    }

    // ─── Boot ───────────────────────────────────
    document.addEventListener('DOMContentLoaded', init);

    return { state, api, ui, sse };
})();
