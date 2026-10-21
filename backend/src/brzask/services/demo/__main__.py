"""Prints the demo instance as JSON, shaped like the API's answers.

The web app's stories and tests read it from frontend/src/demo/instance.gen.json;
run `just demo-json` after changing the demo, as a test fails while the file
is stale. The day is fixed so the file only changes with the demo itself.
"""

import json
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from brzask.services.demo.content import INTERESTS
from brzask.services.demo.plan import PlannedSource, demo_plan

DAY = date(2026, 10, 21)
ZONE = ZoneInfo("UTC")


def render() -> str:
    plan = demo_plan(DAY, ZONE)
    data = {
        "day": DAY.isoformat(),
        "sources": [_source(source) for source in plan.sources],
        "interests": [
            {
                "id": n,
                "topic": i.topic,
                "keywords": list(i.keywords),
                "notes": i.notes,
                "active": i.active,
            }
            for n, i in enumerate(INTERESTS, start=1)
        ],
        "articles": [
            {
                "id": a.id,
                "source_id": a.source_id,
                "link": a.link,
                "title": a.title,
                "summary": a.summary,
                "why_it_matters": a.why_it_matters,
                "topic": a.topic,
                "published_at": _time(a.published_at),
                "first_seen_at": _time(a.first_seen_at),
                "rank": a.rank,
                "digest_date": a.digest_date.isoformat() if a.digest_date else None,
                "position": a.position,
                "shown_at": _time(a.shown_at),
                "opened_at": _time(a.opened_at),
            }
            for a in plan.articles
        ],
        "runs": [
            {
                "id": str(r.id),
                "kind": r.kind.value,
                "status": r.status.value,
                "started_at": _time(r.started_at),
                "finished_at": _time(r.finished_at),
                "stats": r.stats,
                "error": r.error,
            }
            for r in sorted(plan.runs, key=lambda r: r.started_at, reverse=True)
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _source(source: PlannedSource) -> dict[str, Any]:
    spec = source.spec
    failures = source.failures
    return {
        "id": source.id,
        "name": spec.name,
        "url": f"https://{spec.host}/feed.xml",
        "site_url": f"https://{spec.host}/",
        "status": spec.status.value,
        "origin": spec.origin.value,
        "origin_detail": spec.origin_detail,
        "note": spec.note,
        "created_at": _time(source.created_at),
        "health": {
            "fetched_at": _time(source.fetched_at),
            "failing_since": _time(failures[0]) if failures else None,
            "permanent_failing_since": _time(failures[0]) if failures and spec.permanent else None,
            "failed_at": _time(failures[-1]) if failures else None,
            "fetch_failures": len(failures),
            "fetch_error": spec.error if failures else None,
        },
    }


def _time(moment: datetime | None) -> str | None:
    return moment.isoformat().replace("+00:00", "Z") if moment else None


if __name__ == "__main__":
    print(render(), end="")
