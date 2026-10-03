import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react';

type DocumentItem = {
  id: string;
  title: string;
  characters: number;
};

type Source = {
  documentId: string;
  title: string;
  excerpt: string;
  score: number;
  page?: number | null;
};

type DocumentDetail = DocumentItem & {
  content: string;
  pages: { page: number; content: string }[];
  contentComplete: boolean;
};

type Answer = {
  answer: string;
  mode: 'retrieval' | 'llm';
  sources: Source[];
};

type ModelProvider = 'ollama' | 'openai' | null;

const SAMPLE_TITLE = '가상-팀-온보딩-가이드.md';
const GUIDE_ID_PREFIX = 'gonggam-guide-2024-page-';
const GUIDE_SOURCE_URL = 'https://www.moel.go.kr/policy/policydata/view.do?bbs_seq=20240400051';
const SAMPLE_TEXT = `# 가상 팀 온보딩 가이드

이 문서는 서비스 시연을 위해 만든 가상의 예시입니다. 실제 회사 정책이 아닙니다.

## 첫 주 일정
신규 구성원은 첫 주에 팀 소개 미팅에 참여하고, 개발 환경을 설정하고, 작은 문서 수정 작업을 완료합니다. 매일 퇴근 전 막힌 점을 온보딩 담당자에게 공유합니다.

## 계정 및 권한
계정 권한은 입사 첫날 온보딩 담당자에게 요청합니다. 담당자는 필요한 시스템만 확인한 뒤 권한을 부여합니다. 비밀번호나 API 키는 채팅 메시지로 공유하지 않습니다.

## 코드 리뷰
작업을 마치면 변경 목적, 테스트 방법, 남은 위험을 풀 리퀘스트 설명에 적습니다. 다른 구성원 한 명의 리뷰를 받은 뒤 병합합니다.

## 문의
가이드에 없는 규정은 추측하지 말고 담당자에게 확인합니다.`;

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, options);
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new Error('서버에 연결하지 못했습니다. 백엔드가 실행 중인지 확인해 주세요.');
  }

  if (!response.ok) {
    let message = `요청에 실패했습니다. (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') message = body.detail;
    } catch {
      // Keep the status message for non-JSON server errors.
    }
    throw new Error(message);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '알 수 없는 오류가 발생했습니다.';
}

export default function App() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loadingDocuments, setLoadingDocuments] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [question, setQuestion] = useState('');
  const [askedQuestion, setAskedQuestion] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [asking, setAsking] = useState(false);
  const [modelAvailable, setModelAvailable] = useState(false);
  const [modelProvider, setModelProvider] = useState<ModelProvider>(null);
  const [useModel, setUseModel] = useState(false);
  const [uploadsAvailable, setUploadsAvailable] = useState(false);
  const [publicDemo, setPublicDemo] = useState(false);
  const [loadingCapabilities, setLoadingCapabilities] = useState(true);
  const [capabilitiesError, setCapabilitiesError] = useState(false);
  const [selectedSource, setSelectedSource] = useState<Source | null>(null);
  const [documentDetail, setDocumentDetail] = useState<DocumentDetail | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [inspectionError, setInspectionError] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const questionRequest = useRef<AbortController | null>(null);
  const inspectionRequest = useRef<AbortController | null>(null);
  const inspectionPanel = useRef<HTMLElement | null>(null);
  const lastSourceButton = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    let active = true;
    request<{ documents: DocumentItem[] }>('/documents')
      .then((data) => {
        if (active) setDocuments(data.documents);
      })
      .catch((cause) => {
        if (active) setError(errorMessage(cause));
      })
      .finally(() => {
        if (active) setLoadingDocuments(false);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => () => {
    questionRequest.current?.abort();
    inspectionRequest.current?.abort();
  }, []);

  useEffect(() => {
    let active = true;
    request<{ modelAvailable: boolean; modelProvider?: ModelProvider; uploadsAvailable?: boolean; publicDemo?: boolean }>('/capabilities')
      .then((data) => {
        if (active) {
          setModelAvailable(data.modelAvailable);
          setModelProvider(data.modelProvider ?? null);
          setUploadsAvailable(data.uploadsAvailable ?? true);
          setPublicDemo(data.publicDemo ?? false);
        }
      })
      .catch(() => {
        if (active) setCapabilitiesError(true);
      })
      .finally(() => {
        if (active) setLoadingCapabilities(false);
      });
    return () => { active = false; };
  }, []);

  function clearQuestionResult() {
    questionRequest.current?.abort();
    questionRequest.current = null;
    setAsking(false);
    setAnswer(null);
    inspectionRequest.current?.abort();
    inspectionRequest.current = null;
    setSelectedSource(null);
    setDocumentDetail(null);
    setInspecting(false);
    setInspectionError('');
  }

  async function upload(file: File) {
    setError('');
    setNotice('');
    if (!uploadsAvailable) {
      setError('공개 체험에서는 문서를 추가할 수 없습니다. 제공된 문서로 질문해 주세요.');
      return;
    }
    if (!/\.(txt|md|pdf)$/i.test(file.name)) {
      setError('TXT, MD, PDF 파일만 올릴 수 있습니다.');
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setError('파일 크기는 5MB 이하여야 합니다.');
      return;
    }

    setUploading(true);
    try {
      const body = new FormData();
      body.append('file', file);
      const added = await request<DocumentItem>('/documents', { method: 'POST', body });
      setDocuments((current) => [added, ...current]);
      clearQuestionResult();
      setNotice(`“${added.title}” 문서를 추가했습니다.`);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) void upload(file);
  }

  async function removeDocument(document: DocumentItem) {
    if (!uploadsAvailable || asking) return;
    if (!window.confirm(`“${document.title}” 문서를 삭제할까요?`)) return;
    clearQuestionResult();
    setError('');
    setNotice('');
    try {
      await request<void>(`/documents/${encodeURIComponent(document.id)}`, { method: 'DELETE' });
      setDocuments((current) => current.filter((item) => item.id !== document.id));
      setNotice('문서를 삭제했습니다.');
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || asking || documents.length === 0) return;
    setError('');
    setNotice('');
    clearQuestionResult();
    setAskedQuestion(trimmed);
    setAsking(true);
    const controller = new AbortController();
    questionRequest.current = controller;
    try {
      const result = await request<Answer>('/questions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: trimmed, useModel }),
        signal: controller.signal,
      });
      if (!controller.signal.aborted) setAnswer(result);
    } catch (cause) {
      if (!controller.signal.aborted) setError(errorMessage(cause));
    } finally {
      if (questionRequest.current === controller) {
        questionRequest.current = null;
        setAsking(false);
      }
    }
  }

  async function inspectSource(source: Source) {
    inspectionRequest.current?.abort();
    const controller = new AbortController();
    inspectionRequest.current = controller;
    setSelectedSource(source);
    setDocumentDetail(null);
    setInspectionError('');
    setInspecting(true);
    try {
      const detail = await request<DocumentDetail>(`/documents/${encodeURIComponent(source.documentId)}`, { signal: controller.signal });
      if (!controller.signal.aborted) {
        setDocumentDetail(detail);
        requestAnimationFrame(() => inspectionPanel.current?.focus());
      }
    } catch (cause) {
      if (!controller.signal.aborted) setInspectionError(errorMessage(cause));
    } finally {
      if (inspectionRequest.current === controller) {
        inspectionRequest.current = null;
        setInspecting(false);
      }
    }
  }

  const sampleExists = documents.some((document) => document.title === SAMPLE_TITLE);
  const guideDocuments = documents.filter((document) => document.id.startsWith(GUIDE_ID_PREFIX));
  const modelDescription = loadingCapabilities ? 'AI 설정을 확인하고 있습니다.' : capabilitiesError ? 'AI 설정을 확인하지 못했습니다.' : publicDemo ? '공개 체험에서는 AI 생성을 사용하지 않습니다.' : modelProvider === 'ollama' && modelAvailable ? '선택 시 서버의 로컬 Ollama 모델이 근거 문장으로 답합니다.' : modelProvider === 'openai' && modelAvailable ? '선택 시 질문과 관련 문장이 OpenAI API로 전송됩니다.' : '모델이 연결되지 않아 문서 검색만 사용합니다.';
  const privacyDescription = publicDemo ? '공개 체험에서는 문서 변경과 AI 생성을 사용하지 않습니다.' : modelProvider === 'ollama' ? 'AI 답변을 선택하면 질문과 근거 문장이 서버의 Ollama 모델로 전달됩니다.' : modelProvider === 'openai' ? 'AI 답변을 선택하면 질문과 근거 문장이 OpenAI API로 전송됩니다.' : '모델이 연결되면 답변 전송 대상을 화면에 표시합니다.';
  const inspectedPage = selectedSource?.page != null ? documentDetail?.pages.find((item) => item.page === selectedSource.page) : null;
  const inspectedContent = inspectedPage?.content ?? documentDetail?.content ?? '';
  const previewText = inspectedContent.length > 30000 ? inspectedContent.slice(0, 30000) : inspectedContent;

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="근거노트 맨 위로">
          <span className="brand-mark" aria-hidden="true">N</span>
          <span>근거노트</span>
        </a>
        <span className="header-tag">AI SERVICE PORTFOLIO · 01</span>
      </header>

      <main id="top">
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-copy">
            <p className="eyebrow"><span className="eyebrow-line" /> DOCUMENT QUESTION ANSWERING</p>
            <h1 id="hero-title">문서 안에서 답을 찾고,<br /><em>근거를 보여줍니다.</em></h1>
            <p className="hero-description">{publicDemo ? '준비된 자료에 질문해 보세요. 관련 문장과 쪽수를 찾아 출처와 함께 보여줍니다. 근거가 부족하면 모른다고 말합니다.' : '문서를 올리고 질문해 보세요. 관련 문장을 찾아 답과 함께 출처를 보여줍니다. 근거가 부족하면 모른다고 말합니다.'}</p>
            {guideDocuments.length > 0 && <p className="hero-proof"><span>공식 자료 시연</span><a href={GUIDE_SOURCE_URL} target="_blank" rel="noreferrer">2024 공감채용 가이드 · 검수한 3쪽 <span aria-hidden="true">↗</span></a></p>}
          </div>
          <div className="hero-side" aria-label="서비스 흐름">
            <span className="side-kicker">HOW IT WORKS</span>
            <ol>
              <li><span>01</span> {publicDemo ? '자료 선택' : '문서 추가'}</li>
              <li><span>02</span> 질문 입력</li>
              <li><span>03</span> 답과 근거 확인</li>
            </ol>
          </div>
        </section>

        <div className="workspace-heading">
          <div>
            <p className="section-kicker">WORKSPACE</p>
            <h2>직접 사용해 보기</h2>
          </div>
          <p>{publicDemo ? '준비된 자료를 검색하고, 발췌 요약과 공식 원문을 비교해 보세요.' : '기본 모드는 문장 검색입니다. AI 답변을 선택하면 결과에 별도 표시합니다.'}</p>
        </div>

        {(error || notice) && (
          <div className={`feedback ${error ? 'feedback-error' : 'feedback-success'}`} role={error ? 'alert' : 'status'}>
            <span>{error || notice}</span>
            <button type="button" onClick={() => { setError(''); setNotice(''); }} aria-label="알림 닫기">×</button>
          </div>
        )}

        <div className="workspace-grid">
          <aside className="panel documents-panel" aria-labelledby="documents-title">
            <div className="panel-title-row">
              <div>
                <p className="panel-step">STEP 01</p>
                <h3 id="documents-title">내 문서</h3>
              </div>
              <span className="count-pill">{documents.length}</span>
            </div>
            <p className="panel-description">{loadingCapabilities ? '사용 가능한 기능을 확인하고 있습니다.' : capabilitiesError ? '서버 기능을 확인하지 못했습니다. 새로고침해 주세요.' : publicDemo ? '준비된 자료를 골라 질문해 보세요. 공개 체험에서는 자료를 변경할 수 없습니다.' : '질문에 참고할 문서를 추가하세요. TXT, MD, PDF · 최대 5MB'}</p>
            {uploadsAvailable && (
              <>
                <input ref={fileInput} className="visually-hidden" id="document-file" type="file" accept=".txt,.md,.pdf" onChange={onFileChange} disabled={uploading || asking} />
                <label className={`upload-button ${uploading || asking ? 'disabled' : ''}`} htmlFor="document-file">
                  <span aria-hidden="true">＋</span>{uploading ? '문서 처리 중...' : '파일 선택하기'}
                </label>
                {!sampleExists && (
                  <button className="sample-button" type="button" disabled={uploading || asking} onClick={() => void upload(new File([SAMPLE_TEXT], SAMPLE_TITLE, { type: 'text/markdown' }))}>
                    가상 예시 문서로 시작하기 <span aria-hidden="true">↗</span>
                  </button>
                )}
              </>
            )}
            <div className="document-list" aria-live="polite">
              {loadingDocuments ? (
                <p className="list-placeholder">문서를 불러오는 중입니다.</p>
              ) : documents.length === 0 ? (
                <div className="empty-documents"><span className="empty-illustration" aria-hidden="true">▤</span><strong>아직 문서가 없습니다</strong><p>{publicDemo ? '시연 자료가 준비되지 않았습니다.' : '파일을 올리거나 가상 예시로 시작해 보세요.'}</p></div>
              ) : (
                <ul>
                  {documents.map((document) => (
                    <li key={document.id} className="document-item">
                      <span className="document-icon" aria-hidden="true">D</span>
                      <span className="document-info"><strong title={document.title}>{document.title}</strong><small>{document.characters.toLocaleString()}자</small></span>
                      {uploadsAvailable && <button type="button" className="remove-button" disabled={asking} onClick={() => void removeDocument(document)} aria-label={`${document.title} 삭제`}>×</button>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {guideDocuments.length > 0 && (
              <div className="dataset-note">
                <strong>공식 자료 기반 시연</strong>
                <p>고용노동부·한국산업인력공단의 2024년 『공감채용 가이드 핸드북』 중 3쪽을 검수해 요약했습니다. 전체 문서 검색이나 현행 법률 안내는 아닙니다.</p>
                <a href={GUIDE_SOURCE_URL} target="_blank" rel="noreferrer">공식 원문 보기 <span aria-hidden="true">↗</span></a>
              </div>
            )}
          </aside>

          <section className="panel question-panel" aria-labelledby="question-title">
            <div className="panel-title-row">
              <div>
                <p className="panel-step">STEP 02</p>
                <h3 id="question-title">문서에 질문하기</h3>
              </div>
              <span className="status-dot" title={publicDemo ? '공개 체험' : '로컬 데모'} aria-label={publicDemo ? '공개 체험' : '로컬 데모'} />
            </div>
            <p className="panel-description">답변의 출처를 확인하고, 원문과 비교해 보세요.</p>
            <form onSubmit={(event) => void ask(event)}>
              <label className="input-label" htmlFor="question">질문</label>
              <textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={loadingDocuments ? '자료를 불러오는 중입니다.' : documents.length === 0 ? publicDemo ? '시연 자료가 준비되지 않았습니다.' : '먼저 문서를 추가해 주세요.' : guideDocuments.length > 0 ? '예: 채용 불합격 통지 방법은?' : '예: 첫 주에 해야 할 일은 무엇인가요?'} maxLength={500} rows={3} disabled={documents.length === 0 || asking} />
              <label className={`model-option ${modelAvailable ? '' : 'model-option-disabled'}`}>
                <input type="checkbox" checked={useModel} disabled={!modelAvailable || asking} onChange={(event) => setUseModel(event.target.checked)} />
                <span className="model-option-copy"><strong>AI 답변 생성 <small>선택</small></strong><span>{modelDescription}</span></span>
              </label>
              <div className="form-footer"><span>{question.length} / 500</span><button className="ask-button" type="submit" disabled={!question.trim() || documents.length === 0 || asking}>{asking ? '근거 찾는 중...' : '답변 확인하기'} <span aria-hidden="true">→</span></button></div>
            </form>
            {!answer && !asking && guideDocuments.length > 0 && (
              <div className="suggestions"><span>공식 자료 질문</span><button type="button" onClick={() => setQuestion('채용 불합격 통지 방법은?')}>불합격 통지 방법</button><button type="button" onClick={() => setQuestion('구직자는 기업 정보를 어디서 얻나요?')}>기업 정보 탐색</button><button type="button" onClick={() => setQuestion('채용 단계 진행 상황을 공유하는 방법은?')}>결과 안내 방법</button></div>
            )}
            {!answer && !asking && guideDocuments.length === 0 && sampleExists && (
              <div className="suggestions"><span>가상 예시 질문</span><button type="button" onClick={() => setQuestion('첫 주에 해야 할 일은?')}>첫 주에 해야 할 일은?</button><button type="button" onClick={() => setQuestion('계정 권한은 언제 요청하나요?')}>계정 권한은 언제 요청하나요?</button></div>
            )}
            <div className="answer-area" aria-live="polite">
              {asking ? (
                <div className="answer-placeholder"><span className="loading-ring" aria-hidden="true" /><p>문서에서 관련 근거를 찾고 있습니다.</p></div>
              ) : answer ? (
                <div className="answer-content">
                  <div className="answer-topline"><span className="answer-label">ANSWER</span><span className="mode-badge">{answer.mode === 'llm' ? modelProvider === 'ollama' ? '로컬 AI 생성 답변' : 'AI 생성 답변' : '문서 검색 결과'}</span></div>
                  <p className="asked-question">“{askedQuestion}”</p>
                  <p className="answer-text">{answer.answer}</p>
                  <div className="sources">
                    <h4>확인한 근거 <span>{answer.sources.length}</span></h4>
                    {answer.sources.length === 0 ? (
                      <p className="no-sources">일치하는 근거가 없습니다. 다른 질문이나 문서를 시도해 보세요.</p>
                    ) : (
                      <ol>{answer.sources.map((source, index) => (
                        <li key={`${source.documentId}-${index}`}>
                          <div className="source-heading"><span className="source-number">{String(index + 1).padStart(2, '0')}</span><strong>{source.title}{source.page && !source.title.includes(`${source.page}쪽`) ? ` · ${source.page}쪽` : ''}</strong></div>
                          <p>{source.excerpt}</p>
                          <button className="source-open" type="button" onClick={(event) => { lastSourceButton.current = event.currentTarget; void inspectSource(source); }}>{source.documentId.startsWith(GUIDE_ID_PREFIX) ? '검수한 발췌 요약 확인' : '저장된 문서 내용 확인'} <span aria-hidden="true">↗</span></button>
                        </li>
                      ))}</ol>
                    )}
                    {selectedSource && (
                      <section className="source-inspector" ref={inspectionPanel} tabIndex={-1} aria-labelledby="inspection-title">
                        <div className="inspector-heading">
                          <div><span className="section-kicker">SOURCE VIEW</span><h5 id="inspection-title">{selectedSource.title}{selectedSource.page && !selectedSource.title.includes(`${selectedSource.page}쪽`) ? ` · ${selectedSource.page}쪽` : ''}</h5></div>
                          <button type="button" onClick={() => { inspectionRequest.current?.abort(); setSelectedSource(null); setDocumentDetail(null); lastSourceButton.current?.focus(); }} aria-label="원문 확인 닫기">×</button>
                        </div>
                        {inspecting ? <p className="inspector-message">원문을 불러오는 중입니다.</p> : inspectionError ? <p className="inspector-message inspector-error" role="alert">{inspectionError}</p> : documentDetail && (
                          <>
                            {!documentDetail.contentComplete && <p className="inspector-message">이전에 추가한 문서라 원문 일부가 누락되었을 수 있습니다.</p>}
                            {selectedSource.documentId.startsWith(GUIDE_ID_PREFIX) && <p className="inspector-message">2024년 공식 가이드의 해당 쪽을 요약한 시연 자료입니다. <a href={GUIDE_SOURCE_URL} target="_blank" rel="noreferrer">PDF 원문은 공식 게시 페이지에서 확인하세요.</a></p>}
                            <pre className="inspector-content">{previewText}</pre>
                            {inspectedContent.length > previewText.length && <p className="inspector-message">긴 문서는 앞부분 3만 자만 표시합니다.</p>}
                          </>
                        )}
                      </section>
                    )}
                  </div>
                </div>
              ) : (
                <div className="answer-placeholder"><span className="placeholder-mark" aria-hidden="true">↗</span><p>질문을 입력하면 답과 출처가 여기에 나타납니다.</p></div>
              )}
            </div>
          </section>
        </div>

        <p className="privacy-note">가상 예시 문서는 실제 회사 자료가 아닙니다. 공식 자료 발췌는 2024년 판본의 일부입니다. {!publicDemo && '업로드한 문서는 서버의 저장소에 보관됩니다. '}{privacyDescription} {!publicDemo && '민감한 정보는 올리지 마세요.'}</p>
      </main>
      <footer className="site-footer"><span>근거노트</span><span>출처를 확인하는 문서 질문 데모</span></footer>
    </div>
  );
}
