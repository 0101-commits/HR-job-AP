from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"
KST = timezone(timedelta(hours=9))

ROLE_RULES: dict[str, list[str]] = {
    "TA": ["채용", "리크루터", "인재영입", "recruiter", "talent acquisition", "sourcer", "recruiting"],
    "HRM": ["인사기획", "인사운영", "인사제도", "인사행정", "hrm", "people ops", "hr generalist", "human resources"],
    "HRD": ["교육", "육성", "리더십개발", "온보딩", "hrd", "l&d", "learning", "leadership development"],
    "CB": ["보상", "평가", "성과관리", "복리후생", "c&b", "compensation", "benefits", "total rewards", "performance"],
    "ER": ["노무", "노사", "노무사", "employee relations", "labor", "labour"],
    "OD": ["조직문화", "조직개발", "조직진단", "od", "culture", "engagement", "organization design"],
    "BP": ["사업부 인사", "hrbp", "people partner", "business partner"],
    "PAY": ["급여", "4대보험", "급여정산", "payroll"],
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

BROAD_HR_SIGNALS = ["인사", "hr", "people", "human resources", "talent", "organization", "workforce"]
LEAD_SIGNALS = ["팀장", "리더", "총괄", "head of", "director", "principal", "partner", "practice lead"]
MID_SIGNALS = ["manager", "senior manager", "lead", "책임", "수석", "선임"]


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
    text = compact_text(job.get("title"), job.get("description"), job.get("category"), job.get("department"))
    roles = [role for role, keywords in ROLE_RULES.items() if any(keyword.lower() in text for keyword in keywords)]

    if not roles and not any(signal in text for signal in BROAD_HR_SIGNALS):
        return None

    enriched = dict(job)
    enriched["role"] = roles or ["HRM"]
    enriched["hr_confidence"] = "high" if roles else "review"
    enriched["grade"] = enriched.get("grade") or infer_grade(text)

    exp_min, exp_max = infer_experience(text)
    if enriched.get("exp_min") is None:
        enriched["exp_min"] = exp_min
    if enriched.get("exp_max") is None:
        enriched["exp_max"] = exp_max
    return enriched


def infer_grade(text: str) -> str:
    if any(signal in text for signal in LEAD_SIGNALS):
        return "lead"
    if any(signal in text for signal in MID_SIGNALS):
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
    updated["updated_at"] = now_iso()
    updated["total_jobs"] = len(jobs)
    updated["review_jobs"] = sum(1 for job in jobs if job.get("hr_confidence") == "review")
    updated["version"] = "2.0"
    return updated


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
    parser = argparse.ArgumentParser(description="Validate and prepare HR job radar data")
    parser.add_argument("--check", action="store_true", help="validate without writing")
    args = parser.parse_args()
    return run(check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
