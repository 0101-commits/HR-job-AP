# HR 채용 레이더

기업 채용 사이트를 원천으로 삼는 HR 직무 채용공고 애그리게이터입니다. 이 저장소는 GitHub Pages 정적 앱, 데이터 스키마, 분류 엔진, 커버리지 가드, Actions cron 골격을 포함합니다.

## 구성

- `index.html` - GitHub Pages 진입점
- `assets/styles.css` - astryx 기준의 neutral row UI
- `assets/app.js` - 목록, 필터, 북마크, 읽음, 커버리지 탭
- `data/jobs.json` - 공고 데이터
- `data/coverage.json` - 소스별 커버리지 상태
- `data/meta.json` - 갱신 메타데이터
- `config/registry.json` - 수집 대상과 collector 매핑
- `scripts/collect.py` - 분류, 중복 병합, 커버리지 가드, 데이터 검증
- `.github/workflows/collect.yml` - KST 09, 13, 17시 갱신 및 Pages 배포

## 로컬 실행

```powershell
python -m http.server 8000
```

브라우저에서 `http://localhost:8000`을 엽니다. `file://`로 열면 브라우저 보안 정책 때문에 JSON 로딩이 막힐 수 있습니다.

## 데이터 검증

```powershell
python scripts/collect.py --check
python -m unittest discover -s tests
```

## 운영 메모

- 사람인 API 키는 `SARAMIN_API_KEY` secret으로 등록하면 L3 안전망 collector를 연결할 수 있습니다.
- 산업군/협회 채용게시판: 금융투자협회(KOFIA), 한국벤처캐피탈협회(KVCA), 한국표준협회(KSA), 한국보건산업진흥원(KHIDI) 수집기가 활성화되어 있습니다. KVCA는 VC업계 회원사 공고, KSA는 표준·품질·교육 산업 공고, KHIDI는 보건산업 채용공고(접수기간 마감일 기준)를 가져옵니다.
- 실제 사이트별 직수집은 `config/registry.json`의 source를 활성화하고 `scripts/collect.py`의 collector 함수를 채우는 방식으로 확장합니다.
