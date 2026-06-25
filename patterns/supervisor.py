"""
Supervisor pattern: a Worker Agent generates analysis reports, and a
Supervisor Agent reviews the quality with scoring + retry loop.

Usage::

    from patterns.supervisor import supervisor
    result = supervisor("Analyze the pros and cons of microservices")
    print(result["output"])
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.model_client import chat


# ---------------------------------------------------------------------------
# JSON chat helper
# ---------------------------------------------------------------------------

def _chat_json(
    prompt: str,
    system_prompt: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> dict | list:
    json_system = (system_prompt or "") + "\nRespond with valid JSON only, no markdown fences."
    result = chat(
        prompt=prompt,
        system_prompt=json_system,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = result["content"].strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:]) if lines[-1].startswith("```") else "\n".join(lines[1:-1])
    return json.loads(content)


# ---------------------------------------------------------------------------
# Worker Agent: generates analysis report
# ---------------------------------------------------------------------------

WORKER_SYSTEM_PROMPT = """\
You are a research analyst. Given a task, produce a structured analysis report in JSON format with these keys:
- "summary": a concise summary of your findings (1-2 sentences)
- "key_points": a list of 3-5 bullet points with key insights
- "details": a more detailed analysis (2-4 paragraphs)
- "conclusion": final takeaway (1-2 sentences)"""


def _worker(task: str) -> dict:
    return _chat_json(
        prompt=f"Task: {task}",
        system_prompt=WORKER_SYSTEM_PROMPT,
        temperature=0.5,
    )


# ---------------------------------------------------------------------------
# Supervisor Agent: quality review
# ---------------------------------------------------------------------------

SUPERVISOR_SYSTEM_PROMPT = """\
You are a quality assurance reviewer. Evaluate the following analysis report on three dimensions:

1. Accuracy (1-10): Are the facts correct and well-supported?
2. Depth (1-10): Does the analysis go beyond surface-level?
3. Format (1-10): Is the JSON structure valid and well-organized?

Return a JSON object with these keys:
- "passed": true if (accuracy + depth + format) / 3 >= 7, else false
- "score": the average of the three scores rounded to the nearest integer (1-10)
- "accuracy": score for accuracy (1-10)
- "depth": score for depth (1-10)
- "format": score for format (1-10)
- "feedback": specific, actionable feedback for improvement (or "Good work." if passed)"""


def _supervisor_review(report: dict, task: str) -> dict:
    return _chat_json(
        prompt=f"Task: {task}\n\nReport to review:\n{json.dumps(report, ensure_ascii=False, indent=2)}",
        system_prompt=SUPERVISOR_SYSTEM_PROMPT,
        temperature=0.2,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def supervisor(task: str, max_retries: int = 3) -> dict:
    """Run the supervisor pattern: worker generates, supervisor reviews.

    The review loop continues until the supervisor passes the report
    (score >= 7) or the maximum number of retries is exhausted.

    Args:
        task: The analysis task for the worker agent.
        max_retries: Maximum redo attempts (default 3, meaning up to
            4 total attempts including the initial one).

    Returns:
        A dict with:
        - ``output``: the final worker report (dict)
        - ``attempts``: number of attempts made (int)
        - ``final_score``: the final review score (int)
        - ``warning``: present only if max_retries was exhausted (str)
    """
    feedback: str | None = None
    report: dict | None = None
    score: int = 0

    for attempt in range(1, max_retries + 2):
        if feedback:
            worker_prompt = (
                f"Original task: {task}\n\n"
                f"Your previous attempt was rejected. Reviewer feedback:\n{feedback}\n\n"
                f"Please revise your analysis addressing all the issues mentioned above."
            )
        else:
            worker_prompt = f"Task: {task}"

        report = _chat_json(
            prompt=worker_prompt,
            system_prompt=WORKER_SYSTEM_PROMPT,
            temperature=0.5,
        )

        review = _supervisor_review(report, task)
        passed: bool = review.get("passed", False)
        score = review.get("score", 0)
        feedback = review.get("feedback", "")

        if passed:
            return {
                "output": report,
                "attempts": attempt,
                "final_score": score,
            }

    return {
        "output": report,
        "attempts": max_retries + 1,
        "final_score": score,
        "warning": f"Max retries ({max_retries}) exceeded. Returning best-effort result.",
    }


# ============================================================================
# Self-test
# ============================================================================

if __name__ == "__main__":
    test_tasks = [
        "Analyze the pros and cons of microservices architecture",
        "Compare Python and Go for backend development",
    ]

    for task in test_tasks:
        print(f"\n{'=' * 60}")
        print(f"Task: {task}")
        try:
            result = supervisor(task, max_retries=3)
            print(f"Attempts: {result['attempts']}")
            print(f"Final score: {result['final_score']}")
            if "warning" in result:
                print(f"Warning: {result['warning']}")
            summary = result["output"].get("summary", "N/A")
            print(f"Summary: {summary[:200]}")
        except Exception as e:
            print(f"Error: {e}")
