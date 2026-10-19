"""The pipelines `run_pipeline` runs by default, by kind."""

from brzask.db.models import RunKind
from brzask.services.digest.pipeline import run_digest
from brzask.services.review import review_sources
from brzask.services.runs import Pipeline
from brzask.services.visited import run_visited

# Filled in as pipelines are added.
PIPELINES: dict[RunKind, Pipeline] = {
    RunKind.DIGEST: run_digest,
    RunKind.REVIEW: review_sources,
    RunKind.VISITED: run_visited,
}
