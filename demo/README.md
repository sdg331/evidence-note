# 공식 가이드 시연 데이터

- 원본: 고용노동부·한국산업인력공단, 『공감채용 가이드 핸드북』, 2024-02-26 초판 4쇄.
- 게시: <https://www.moel.go.kr/policy/policydata/view.do?bbs_seq=20240400051>
- PDF: <https://www.moel.go.kr/common/downloadFile.do?bbs_id=29&bbs_seq=20240400051&file_ext=pdf&file_seq=20240400107>
- 게시 페이지의 이용 조건: 공공누리 제1유형(출처 표시).

원본은 이미지형 92쪽 PDF입니다. 아래 **3쪽의 관련 문단만** OCR로 읽고 렌더링된 이미지와 대조해 시연용으로 요약했습니다. `guide_excerpts.json`의 `page`는 **인쇄 쪽수**, `pdfPage`는 파일 뷰어의 **PDF 쪽수**입니다. 저장한 내용은 원본 전체나 축자 전사가 아닙니다.

| 인쇄 쪽수 | PDF 쪽수 | 시연 주제 |
| --- | --- | --- |
| 53 | 55 | 불합격 사실을 알리는 방식과 개별 연락 권고 |
| 64 | 66 | 구직자의 기업 정보 획득 경로 |
| 70 | 72 | 서류전형 일정·결과 공유와 심사 기준 |

원본은 2024년 자료이므로 현재 법령이나 최신 채용 제도를 판단하는 데 사용하지 않습니다. 평가 질문은 `evaluation_cases.json`에 있으며, 작은 자체 작성 회귀 세트라는 한계가 있습니다.

OCR 재현에는 macOS Vision과 Poppler의 `pdftoppm`이 필요합니다. 예를 들어 원본 PDF를 `guide.pdf`로 저장한 뒤 `pdftoppm -f 55 -l 55 -r 180 -png -singlefile guide.pdf /tmp/guide-page-55`로 페이지를 렌더링하고 `swift scripts/ocr_page.swift /tmp/guide-page-55.png`로 텍스트를 확인할 수 있습니다. OCR 결과는 오인식이 있어 이미지를 보고 직접 교정·요약했습니다. 이 준비 과정은 앱 실행에 필요하지 않습니다.
