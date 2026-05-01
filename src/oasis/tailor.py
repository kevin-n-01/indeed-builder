from __future__ import annotations

import json

import anthropic
from pydantic import BaseModel

_SYSTEM_PROMPT = (
    "You are an expert resume and cover letter writer. "
    "Your job is to tailor documents to a specific job and company. "
    "NEVER fabricate experience, credentials, or skills. "
    "Only reframe, reorder, or emphasize real content to best match the role. "
    "Keep changes professional and concise. "
    "Preserve the candidate's authentic voice."
)

_USER_TEMPLATE = """\
JOB TITLE: {title}
COMPANY: {company}
JOB DESCRIPTION:
{description}

COMPANY MISSION / VALUES:
{company_info}

---
RESUME (each line is: para_INDEX: text)
{resume_paragraphs}

---
COVER LETTER (each line is: para_INDEX: text)
{cover_paragraphs}

---
Return ONLY valid JSON in this exact format (no markdown, no explanation):
{{
  "resume_changes": [{{"index": N, "new_text": "..."}}],
  "cover_letter_changes": [{{"index": N, "new_text": "..."}}]
}}
Only include paragraphs that genuinely need updating. Omit unchanged paragraphs entirely.
"""


class TailoringResult(BaseModel):
    resume_changes: list[dict]
    cover_letter_changes: list[dict]


def tailor_documents(
    api_key: str,
    job_title: str,
    company: str,
    job_description: str,
    company_info: str,
    resume_paragraphs: list[str],
    cover_paragraphs: list[str],
) -> TailoringResult:
    client = anthropic.Anthropic(api_key=api_key)

    resume_text = "\n".join(f"para_{i}: {t}" for i, t in enumerate(resume_paragraphs) if t.strip())
    cover_text = "\n".join(f"para_{i}: {t}" for i, t in enumerate(cover_paragraphs) if t.strip())

    user_msg = _USER_TEMPLATE.format(
        title=job_title,
        company=company,
        description=job_description[:3000],
        company_info=company_info[:2000] if company_info else "Not available.",
        resume_paragraphs=resume_text,
        cover_paragraphs=cover_text,
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if Claude wraps in them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)
    return TailoringResult.model_validate(data)
