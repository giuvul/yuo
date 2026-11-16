"""Reviewer output (stage `review`) and how it maps to a gate verdict."""

from typing import Literal

from pydantic import BaseModel, Field

from yuo.core.enums import CheckVerdict


class Issue(BaseModel):
    severity: Literal["major", "minor"] = Field(
        description="major: wrong or misleading; minor: unclear or style"
    )
    where: str = Field(description="the block id (b1, b2, ...) or 'item'")
    claim: str = Field(description="the problematic text, quoted briefly")
    correction: str = Field(description="what is right instead")


class ReviewReport(BaseModel):
    verdict: Literal["pass", "fail"]
    issues: list[Issue]
    level_fit: Literal["too_easy", "fits", "too_hard"] = Field(description="against the path difficulty")


def gate_verdict(report: ReviewReport) -> CheckVerdict:
    """Any major issue fails, whatever the reviewer's own verdict says (rubber-stamp passes)."""
    if report.verdict == "fail" or any(i.severity == "major" for i in report.issues):
        return CheckVerdict.FAIL
    return CheckVerdict.WARN if report.issues else CheckVerdict.PASS


def review_rules(report: ReviewReport) -> list[str]:
    if report.verdict == "pass" and any(i.severity == "major" for i in report.issues):
        return ["verdict is pass but a major issue is listed: use fail, or mark the issue minor"]
    return []
