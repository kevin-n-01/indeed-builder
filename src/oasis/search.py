from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Job(BaseModel):
    id: str = ""
    title: str
    company: str
    location: str = ""
    salary: str = ""
    job_url: str = ""
    description: str = ""


def search_jobs(
    search_terms: list[str],
    locations: list[str],
    job_type: str = "fulltime",
    remote: bool = False,
    results_wanted: int = 50,
) -> list[Job]:
    from jobspy import scrape_jobs

    site_names = ["indeed", "linkedin"]
    jt = None if job_type == "any" else job_type

    # Run one search per (term, location) combination, then deduplicate by URL
    seen_urls: set[str] = set()
    jobs: list[Job] = []

    for term in search_terms:
        for loc in (locations or [""]):
            try:
                df = scrape_jobs(
                    site_name=site_names,
                    search_term=term,
                    location=loc,
                    job_type=jt,
                    is_remote=remote,
                    results_wanted=results_wanted,
                    country_indeed="USA",
                )
            except Exception:
                continue

            for _, row in df.iterrows():
                url = _str(row.get("job_url"))
                dedup_key = url or f"{_str(row.get('company'))}|{_str(row.get('title'))}"
                if dedup_key in seen_urls:
                    continue
                seen_urls.add(dedup_key)
                jobs.append(
                    Job(
                        title=_str(row.get("title")),
                        company=_str(row.get("company")),
                        location=_str(row.get("location")),
                        salary=_fmt_salary(row),
                        job_url=url,
                        description=_str(row.get("description")),
                    )
                )

    return jobs


def _str(val: Any) -> str:
    if val is None:
        return ""
    s = str(val)
    return "" if s in ("nan", "None") else s


def _fmt_salary(row: Any) -> str:
    import math
    lo = row.get("min_amount")
    hi = row.get("max_amount")
    # JobSpy returns NaN for missing salary values
    def valid(v: Any) -> bool:
        try:
            return v is not None and not math.isnan(float(v))
        except (TypeError, ValueError):
            return False
    if valid(lo) and valid(hi):
        return f"${int(float(lo)):,}–${int(float(hi)):,}"
    if valid(lo):
        return f"${int(float(lo)):,}+"
    return ""
