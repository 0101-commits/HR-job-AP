from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"
KST = timezone(timedelta(hours=9))

ROLE_RULES: dict[str, list[str]] = {
    "TA": ["채용", "리크루터", "인재영입", "recruiter", "talent acquisition", "sourcer", "recruiting", "ta"],
    "HRM": ["인사기획", "인사운영", "인사제도", "인사행정", "hrm", "hris", "people ops", "hr generalist", "human resources"],
    "HRD": ["교육", "육성", "리더십개발", "온보딩", "hrd", "l&d", "learning", "leadership development", "training"],
    "CB": ["보상", "평가", "성과관리", "복리후생", "c&b", "compensation", "benefits", "total rewards", "performance"],
    "ER": ["노무", "노사", "노무사", "employee relations", "labor", "labour"],
    "OD": ["조직문화", "조직개발", "조직진단", "컬쳐", "컬처", "od", "culture", "engagement", "organization design"],
    "BP": ["사업부 인사", "hrbp", "people partner", "business partner"],
    "PAY": ["급여", "4대보험", "급여정산", "payroll", "페이롤"],
    "HRC": [
        "hr컨설팅",
        "인사제도 컨설턴트",
        "조직설계",
        "직무분석",
        "human capital",
        "people consulting",
        "people & organization",
        "people and organization",
        "people & change",
        "workforce transformation",
        "hr advisory",
        "job architecture",
    ],
}

# 강신호: 제목에 있으면 제네럴리스트 HR로 확신(high) — "인사 담당자", "HR Manager" 류.
STRONG_HR_SIGNALS = ["인사", "피플", "hr", "people", "human resources", "chro"]
# 약신호: HR 인접이라 버리지 않되 검토 버킷(review)으로 — "총무", 영문 talent/organization 등.
WEAK_HR_SIGNALS = ["총무", "경영지원", "talent", "organization", "workforce", "ga"]
LEAD_SIGNALS = ["팀장", "리더", "총괄", "실장", "그룹장", "파트장", "head of", "head", "director", "principal", "practice lead", "lead", "chro"]
MID_SIGNALS = ["manager", "senior", "시니어", "책임", "수석", "선임"]

CONSULTING_GROUPS = {
    "aon", "mckinsey", "bcg", "bain", "딜로이트", "kpmg", "pwc", "ey",
    "mercer", "korn ferry", "콘페리", "wtw", "올리버와이먼",
}


def keyword_match(text: str, keyword: str) -> bool:
    """짧은 영문 약어(hr, od, ta 등)가 다른 단어 안에서 오탐하지 않게 토큰 경계 매칭."""
    if re.fullmatch(r"[a-z0-9&./+\- ]+", keyword):
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None
    return keyword in text


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(KST).replace(microsecond=0).isoformat()


def compact_text(*values: Any) -> str:
    return " ".join(str(value or "") for value in values).lower()


def normalize_key(value: str) -> str:
    normalized = re.sub(r"\s+", "", value or "").lower()
    normalized = re.sub(r"[^0-9a-z가-힣]", "", normalized)
    return normalized


def classify_job(job: dict[str, Any]) -> dict[str, Any] | None:
    # 직무 판정은 제목·카테고리·부서만 사용 — 본문은 상용구 오탐원
    # (예: "Model Training팀"→HRD, "as an organization"→OD).
    title_text = compact_text(job.get("title"), job.get("category"), job.get("department"))
    roles = [role for role, keywords in ROLE_RULES.items() if any(keyword_match(title_text, keyword.lower()) for keyword in keywords)]
    strong = any(keyword_match(title_text, signal) for signal in STRONG_HR_SIGNALS)
    weak = any(keyword_match(title_text, signal) for signal in WEAK_HR_SIGNALS)
    if not roles and not strong and not weak:
        return None

    enriched = dict(job)
    enriched["role"] = roles or ["HRM"]
    # 세부직무 키워드 or 제네럴리스트 강신호("인사 담당자", "HR Manager") = high.
    # 약신호(총무·GA 등 HR 인접)만 있으면 review — 사람이 훑는 검토 버킷.
    enriched["hr_confidence"] = "high" if (roles or strong) else "review"
    enriched["grade"] = enriched.get("grade") or infer_grade(title_text)

    # 연차는 본문에도 자주 적혀 있어 제목+본문 전체에서 파싱
    exp_min, exp_max = infer_experience(compact_text(job.get("title"), job.get("description")))
    if enriched.get("exp_min") is None:
        enriched["exp_min"] = exp_min
    if enriched.get("exp_max") is None:
        enriched["exp_max"] = exp_max
    return enriched


def infer_grade(text: str) -> str:
    if any(keyword_match(text, signal) for signal in LEAD_SIGNALS):
        return "lead"
    if any(keyword_match(text, signal) for signal in MID_SIGNALS):
        return "mid"
    return "member"


def infer_experience(text: str) -> tuple[int | None, int | None]:
    range_match = re.search(r"(\d+)\s*(?:-|~|–|to)\s*(\d+)\s*(?:년|years?|yrs?)", text)
    if range_match:
        return int(range_match.group(1)), int(range_match.group(2))

    min_match = re.search(r"(\d+)\s*(?:년|years?|yrs?)\s*(?:이상|\+|over|plus)", text)
    if min_match:
        return int(min_match.group(1)), None

    return None, None


def dedupe_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for job in jobs:
        key = "::".join(
            [
                normalize_key(job.get("company", "")),
                normalize_key(job.get("title", "")),
                str(job.get("deadline") or ""),
            ]
        )
        if key not in merged:
            merged[key] = dict(job)
            continue

        previous = merged[key]
        also_on = set(previous.get("also_on") or [])
        if job.get("source") and job.get("source") != previous.get("source"):
            also_on.add(job["source"])
        also_on.update(job.get("also_on") or [])
        previous["also_on"] = sorted(also_on)

        if previous.get("hr_confidence") == "review" and job.get("hr_confidence") == "high":
            previous.update(job)
            previous["also_on"] = sorted(also_on)

    return sorted(merged.values(), key=lambda item: item.get("first_seen") or "", reverse=True)


def apply_coverage_guard(
    source_id: str,
    previous_jobs: list[dict[str, Any]],
    current_jobs: list[dict[str, Any]],
    previous_coverage: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    previous_count = len(previous_jobs)
    current_count = len(current_jobs)
    history = list((previous_coverage or {}).get("count_history") or [])
    status = "ok"
    note = "갱신 성공"
    retained = current_jobs

    if previous_count and current_count == 0:
        status = "warn"
        note = "0건 감지로 직전값 유지"
        retained = previous_jobs
        current_count = previous_count
    elif previous_count and current_count < previous_count * 0.5:
        status = "warn"
        note = "건수 급감으로 직전값 유지"
        retained = previous_jobs
        current_count = previous_count

    history.append(current_count)
    coverage = {
        "id": source_id,
        "label": (previous_coverage or {}).get("label", source_id),
        "status": status,
        "last_ok": now_iso() if status == "ok" else (previous_coverage or {}).get("last_ok"),
        "current_count": current_count,
        "count_history": history[-10:],
        "suspect_missing": 0,
        "parse_fail_rate": 0,
        "note": note,
    }
    return retained, coverage


def validate_jobs(jobs: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    required = ["id", "source", "url", "title", "company", "role", "first_seen", "hr_confidence"]
    for index, job in enumerate(jobs):
        for field in required:
            if field not in job or job[field] in ("", None, []):
                errors.append(f"jobs[{index}] missing {field}")
        if job.get("hr_confidence") not in {"high", "review"}:
            errors.append(f"jobs[{index}] has invalid hr_confidence")
    return errors


def refresh_metadata(jobs: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    updated = dict(meta)
    updated.pop("mode", None)  # v2.0 샘플 모드 잔재 제거
    updated["updated_at"] = now_iso()
    updated["total_jobs"] = len(jobs)
    updated["review_jobs"] = sum(1 for job in jobs if job.get("hr_confidence") == "review")
    updated["version"] = "2.1"
    return updated


# ---------------------------------------------------------------------------
# 수집 레이어 — 실제 채용 사이트/API에서 공고 상세 딥링크를 가져온다
# ---------------------------------------------------------------------------

def http_get(url: str, defaults: dict[str, Any], accept: str = "application/json") -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": defaults.get("user_agent", "HRJobRadar/2.1"),
            "Accept": accept,
            "Accept-Language": "ko, en;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=defaults.get("timeout_seconds", 20)) as response:
        return response.read()


def http_get_json(url: str, defaults: dict[str, Any]) -> Any:
    return json.loads(http_get(url, defaults).decode("utf-8"))


def polite_sleep(defaults: dict[str, Any]) -> None:
    time.sleep(defaults.get("request_delay_seconds", 2))


def parse_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    match = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    # epoch millis (wanted due_time 등)
    if text.isdigit() and len(text) >= 10:
        try:
            stamp = int(text[:10])
            return datetime.fromtimestamp(stamp, KST).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            return None
    return None


def collect_wanted(source: dict[str, Any], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    """원티드 v4 — HR 카테고리(tag 517) 전체. 상세 딥링크 = /wd/{id}."""
    jobs: list[dict[str, Any]] = []
    offset = 0
    while offset < 1000:
        payload = http_get_json(
            "https://www.wanted.co.kr/api/v4/jobs"
            f"?country=kr&tag_type_ids=517&limit=100&offset={offset}&job_sort=job.latest_order",
            defaults,
        )
        rows = payload.get("data") or []
        if not rows:
            break
        for row in rows:
            job_id = row.get("id")
            if not job_id:
                continue
            address = row.get("address") or {}
            jobs.append(
                {
                    "id": f"wanted-{job_id}",
                    "source": "wanted",
                    "source_label": "원티드",
                    "url": f"https://www.wanted.co.kr/wd/{job_id}",
                    "title": row.get("position") or "",
                    "company": (row.get("company") or {}).get("name") or "",
                    "location": address.get("location"),
                    "deadline": parse_date(row.get("due_time")),
                }
            )
        offset += 100
        polite_sleep(defaults)
    return jobs


def collect_kakao(source: dict[str, Any], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    """카카오 careers 공개 API — 전 직무 수집 후 후단 분류(recall 우선). 딥링크 = /jobs/{realId}."""
    jobs: list[dict[str, Any]] = []
    page = 1
    while page <= 40:
        payload = http_get_json(
            f"https://careers.kakao.com/public/api/job-list?part=&company=&keyword=&page={page}",
            defaults,
        )
        rows = payload.get("jobList") or []
        if not rows:
            break
        for row in rows:
            real_id = row.get("realId")
            if not real_id:
                continue
            company = row.get("companyNm") or row.get("company") or "카카오"
            jobs.append(
                {
                    "id": f"kakao-{real_id}",
                    "source": "kakao",
                    "source_label": "카카오 careers",
                    "url": f"https://careers.kakao.com/jobs/{real_id}",
                    "title": row.get("jobOfferTitle") or "",
                    "company": company,
                    "company_group": "카카오",
                    "description": re.sub(r"<[^>]+>", " ", row.get("introduction") or "")[:300],
                    "deadline": parse_date(row.get("endDate")),
                }
            )
        total_page = payload.get("totalPage") or payload.get("totalPages")
        if total_page and page >= int(total_page):
            break
        page += 1
        polite_sleep(defaults)
    return jobs


def collect_aon(source: dict[str, Any], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    """Aon — iCIMS/Jibe 공개 JSON. 서울 오피스 전 공고 수집 후 후단 분류."""
    jobs: list[dict[str, Any]] = []
    page = 1
    while page <= 10:
        payload = http_get_json(
            f"https://jobs.aon.com/api/jobs?location=Seoul%2C%20South%20Korea&page={page}",
            defaults,
        )
        rows = payload.get("jobs") or []
        if not rows:
            break
        for row in rows:
            data = row.get("data") or {}
            slug = data.get("slug") or data.get("req_id")
            url = (data.get("meta_data") or {}).get("canonical_url") or (
                f"https://jobs.aon.com/jobs/{slug}" if slug else None
            )
            if not slug or not url:
                continue
            jobs.append(
                {
                    "id": f"aon-{slug}",
                    "source": "aon",
                    "source_label": "Aon (Jibe)",
                    "url": url,
                    "title": data.get("title") or "",
                    "company": "Aon Korea",
                    "company_group": "Aon",
                    "location": data.get("city") or "서울",
                    "category": data.get("category") or "",
                    "description": re.sub(r"<[^>]+>", " ", data.get("description") or "")[:300],
                }
            )
        total = payload.get("totalCount") or 0
        if len(jobs) >= int(total):
            break
        page += 1
        polite_sleep(defaults)
    return jobs


def collect_saramin(source: dict[str, Any], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    """사람인 오픈 API 안전망 — Secrets에 SARAMIN_API_KEY 있을 때만 동작."""
    api_key = os.environ.get(source.get("secret", "SARAMIN_API_KEY"), "")
    if not api_key:
        raise RuntimeError("SARAMIN_API_KEY 미설정 — 안전망 비활성")

    jobs: list[dict[str, Any]] = []
    payload = http_get_json(
        "https://oapi.saramin.co.kr/job-search"
        f"?access-key={api_key}&keywords=%EC%9D%B8%EC%82%AC&count=110"
        "&fields=posting-date+expiration-date",
        defaults,
    )
    for row in ((payload.get("jobs") or {}).get("job") or []):
        job_id = row.get("id")
        position = row.get("position") or {}
        company = ((row.get("company") or {}).get("detail") or {}).get("name") or ""
        if not job_id or not row.get("url"):
            continue
        jobs.append(
            {
                "id": f"saramin-{job_id}",
                "source": "saramin",
                "source_label": "사람인",
                "url": row.get("url"),
                "title": (position.get("title") or ""),
                "company": company,
                "location": ((position.get("location") or {}).get("name") or "").split(",")[0] or None,
                "category": ((position.get("job-mid-code") or {}).get("name") or ""),
                "deadline": parse_date(row.get("expiration-date")),
            }
        )
    return jobs


COLLECTORS: dict[str, Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any]]]] = {
    "wanted_v4": collect_wanted,
    "kakao_api": collect_kakao,
    "jibe_json": collect_aon,
    "saramin_api": collect_saramin,
}


def apply_company_group(job: dict[str, Any], groups: dict[str, str]) -> dict[str, Any]:
    if not job.get("company_group"):
        group = groups.get(job.get("company", ""))
        if group:
            job["company_group"] = group

    # 기업구분: 컨설팅·외국계 / 대기업(공정위 대기업집단 매핑) / 스타트업·중소
    group_lower = (job.get("company_group") or "").lower()
    if group_lower in CONSULTING_GROUPS:
        job["company_type"] = "consulting"
    elif job.get("company_group"):
        job["company_type"] = "enterprise"
    else:
        job["company_type"] = "smb"
    return job


def drop_expired(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return [job for job in jobs if not job.get("deadline") or job["deadline"] >= today]


def collect_all() -> int:
    jobs_path = DATA_DIR / "jobs.json"
    coverage_path = DATA_DIR / "coverage.json"
    meta_path = DATA_DIR / "meta.json"
    registry = load_json(CONFIG_DIR / "registry.json", {})

    defaults = registry.get("defaults", {})
    groups = registry.get("company_groups", {})
    previous_jobs: list[dict[str, Any]] = load_json(jobs_path, [])
    previous_coverage = {row.get("id"): row for row in load_json(coverage_path, {}).get("sources", [])}
    first_seen_by_id = {job["id"]: job.get("first_seen") for job in previous_jobs if job.get("id")}
    previous_by_source: dict[str, list[dict[str, Any]]] = {}
    for job in previous_jobs:
        previous_by_source.setdefault(job.get("source", ""), []).append(job)

    all_jobs: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    failures: list[str] = []

    for source in registry.get("sources", []):
        source_id = source.get("id", "")
        label = source.get("label", source_id)
        prev_cov = previous_coverage.get(source_id) or {"label": label}
        prev_cov["label"] = label

        if not source.get("enabled"):
            coverage_rows.append(
                {
                    "id": source_id,
                    "label": label,
                    "status": "info",
                    "last_ok": prev_cov.get("last_ok"),
                    "current_count": 0,
                    "count_history": prev_cov.get("count_history", []),
                    "suspect_missing": 0,
                    "parse_fail_rate": 0,
                    "note": source.get("note") or "수집기 예정 (비활성)",
                }
            )
            continue

        collector = COLLECTORS.get(source.get("collector", ""))
        prev_source_jobs = previous_by_source.get(source_id, [])

        if collector is None:
            coverage_rows.append(
                {
                    "id": source_id, "label": label, "status": "fail",
                    "last_ok": prev_cov.get("last_ok"), "current_count": len(prev_source_jobs),
                    "count_history": prev_cov.get("count_history", []),
                    "suspect_missing": 0, "parse_fail_rate": 0,
                    "note": f"수집기 미구현: {source.get('collector')}",
                }
            )
            all_jobs.extend(prev_source_jobs)
            continue

        try:
            raw_jobs = collector(source, defaults)
            classified: list[dict[str, Any]] = []
            for raw in raw_jobs:
                enriched = classify_job(raw)
                if enriched is None:
                    if not source.get("hr_scope"):
                        continue
                    # 소스 피드 자체가 HR 카테고리(예: 원티드 tag 517)면 버리지 않고
                    # 검토 버킷으로 보존 — 누락 제로 원칙.
                    enriched = dict(raw)
                    enriched["role"] = ["HRM"]
                    enriched["hr_confidence"] = "review"
                    enriched["grade"] = infer_grade(compact_text(raw.get("title")))
                enriched.pop("category", None)
                enriched["first_seen"] = first_seen_by_id.get(enriched["id"]) or now_iso()
                classified.append(apply_company_group(enriched, groups))
            retained, coverage = apply_coverage_guard(source_id, prev_source_jobs, classified, prev_cov)
            coverage["label"] = label
            coverage_rows.append(coverage)
            all_jobs.extend(retained)
            print(f"[{source_id}] raw={len(raw_jobs)} hr={len(classified)} -> {coverage['status']}")
        except Exception as error:  # noqa: BLE001 — 소스 하나의 실패가 전체를 죽이면 안 됨
            failures.append(f"{source_id}: {error}")
            coverage_rows.append(
                {
                    "id": source_id, "label": label, "status": "fail",
                    "last_ok": prev_cov.get("last_ok"),
                    "current_count": len(prev_source_jobs),
                    "count_history": prev_cov.get("count_history", []),
                    "suspect_missing": 0, "parse_fail_rate": 0,
                    "note": f"수집 실패 — 직전값 유지: {str(error)[:80]}",
                }
            )
            all_jobs.extend(prev_source_jobs)

    # 가드로 직전값이 유지된 공고도 최신 그룹·기업구분을 갖도록 병합 후 일괄 적용
    merged = [apply_company_group(job, groups) for job in drop_expired(dedupe_jobs(all_jobs))]
    errors = validate_jobs(merged)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    write_json(jobs_path, merged)
    write_json(meta_path, refresh_metadata(merged, load_json(meta_path, {})))
    write_json(coverage_path, {"updated_at": now_iso(), "sources": coverage_rows})

    print(f"collected {len(merged)} HR jobs from {sum(1 for row in coverage_rows if row['status'] == 'ok')} sources")
    if failures:
        print("failures: " + "; ".join(failures), file=sys.stderr)
    return 0


def run(check_only: bool) -> int:
    jobs_path = DATA_DIR / "jobs.json"
    coverage_path = DATA_DIR / "coverage.json"
    meta_path = DATA_DIR / "meta.json"
    registry_path = CONFIG_DIR / "registry.json"

    jobs = load_json(jobs_path, [])
    coverage = load_json(coverage_path, {"sources": []})
    meta = load_json(meta_path, {})
    registry = load_json(registry_path, {})

    errors = validate_jobs(jobs)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    deduped = dedupe_jobs(jobs)
    if len(deduped) != len(jobs):
        jobs = deduped
        if not check_only:
            write_json(jobs_path, jobs)

    if not registry.get("sources"):
        print("registry has no sources", file=sys.stderr)
        return 1

    if not check_only:
        write_json(meta_path, refresh_metadata(jobs, meta))
        coverage["updated_at"] = now_iso()
        write_json(coverage_path, coverage)

    print(f"validated {len(jobs)} jobs, {len(coverage.get('sources', []))} coverage sources")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="HR job radar — collect and validate data")
    parser.add_argument("--check", action="store_true", help="validate without writing")
    parser.add_argument("--collect", action="store_true", help="run real collectors against live sources")
    args = parser.parse_args()
    if args.collect:
        return collect_all()
    return run(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
