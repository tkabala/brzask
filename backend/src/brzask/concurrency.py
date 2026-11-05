"""A thread pool that keeps the caller's context.

Threads start with an empty context, so work handed to a plain thread pool
loses the run ID of its log lines and the span its requests belong to. Each
task here runs in a copy of the context of the thread that submitted it.
"""

import contextvars
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor


class ContextThreadPoolExecutor(ThreadPoolExecutor):
    def submit[**P, T](self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        context = contextvars.copy_context()

        def call() -> T:
            return context.run(fn, *args, **kwargs)

        return super().submit(call)
