import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from brzask.concurrency import ContextThreadPoolExecutor


def test_tasks_see_the_submitting_threads_context() -> None:
    tracer = TracerProvider().get_tracer("test")
    with (
        structlog.contextvars.bound_contextvars(run_id="r1"),
        tracer.start_as_current_span("run") as run,
        ContextThreadPoolExecutor(max_workers=2) as pool,
    ):
        seen = list(
            pool.map(
                lambda _: (
                    trace.get_current_span().get_span_context().span_id,
                    structlog.contextvars.get_contextvars().get("run_id"),
                ),
                range(4),
            )
        )

    assert seen == [(run.get_span_context().span_id, "r1")] * 4


def test_a_task_does_not_change_the_callers_context() -> None:
    def bind(_: int) -> None:
        structlog.contextvars.bind_contextvars(leaked=True)

    with ContextThreadPoolExecutor(max_workers=1) as pool:
        list(pool.map(bind, range(2)))

    assert "leaked" not in structlog.contextvars.get_contextvars()
