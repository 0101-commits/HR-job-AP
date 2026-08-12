import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from collect import apply_coverage_guard, classify_job, dedupe_jobs


class ClassifierTests(unittest.TestCase):
    def test_korean_compensation_role(self):
        job = {
            "title": "보상기획 팀장",
            "description": "성과관리와 복리후생 제도를 담당합니다.",
        }
        classified = classify_job(job)
        self.assertIsNotNone(classified)
        self.assertIn("CB", classified["role"])
        self.assertEqual(classified["grade"], "lead")
        self.assertEqual(classified["hr_confidence"], "high")

    def test_english_hr_consulting_role(self):
        job = {
            "title": "Human Capital Consultant",
            "description": "Workforce transformation and job architecture projects",
        }
        classified = classify_job(job)
        self.assertIsNotNone(classified)
        self.assertIn("HRC", classified["role"])

    def test_non_hr_job_is_rejected(self):
        job = {
            "title": "Backend Engineer",
            "description": "Python API development",
        }
        self.assertIsNone(classify_job(job))

    def test_dedupe_merges_parallel_sources(self):
        jobs = [
            {"title": "HRBP 담당", "company": "LG전자", "deadline": "2026-08-30", "source": "lg"},
            {"title": "HRBP 담당", "company": "LG전자", "deadline": "2026-08-30", "source": "wanted"},
        ]
        merged = dedupe_jobs(jobs)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["also_on"], ["wanted"])

    def test_coverage_guard_retains_previous_on_zero(self):
        previous = [{"id": "a"}, {"id": "b"}]
        retained, coverage = apply_coverage_guard("sk", previous, [])
        self.assertEqual(retained, previous)
        self.assertEqual(coverage["status"], "warn")
        self.assertEqual(coverage["current_count"], 2)


if __name__ == "__main__":
    unittest.main()
