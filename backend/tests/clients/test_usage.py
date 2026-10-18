from concurrent.futures import ThreadPoolExecutor

from brzask.clients.usage import CallUsage, UsageMeter


def call(purpose: str, cost: float | None, tokens: int = 10) -> CallUsage:
    return CallUsage("m", purpose, tokens, tokens // 2, cost, 100)


def test_summary_totals_per_purpose() -> None:
    meter = UsageMeter()
    meter.add(call("ranking", 0.002, tokens=1000))
    meter.add(call("selection", 0.001, tokens=400))
    meter.add(call("selection", 0.0005, tokens=200))

    summary = meter.summary()

    assert summary["calls"] == 3
    assert summary["input_tokens"] == 1600
    assert summary["output_tokens"] == 800
    assert summary["cost_usd"] == 0.0035
    assert summary["duration_ms"] == 300
    assert summary["by_purpose"]["selection"] == {
        "calls": 2,
        "input_tokens": 600,
        "output_tokens": 300,
        "cost_usd": 0.0015,
        "duration_ms": 200,
    }


def test_cost_is_unknown_when_any_call_lacks_one() -> None:
    meter = UsageMeter()
    meter.add(call("ranking", 0.002))
    meter.add(call("embedding", None))

    summary = meter.summary()

    assert summary["cost_usd"] is None
    assert summary["by_purpose"]["ranking"]["cost_usd"] == 0.002
    assert summary["by_purpose"]["embedding"]["cost_usd"] is None


def test_empty_meter() -> None:
    assert UsageMeter().summary() == {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": None,
        "duration_ms": 0,
        "by_purpose": {},
    }


def test_calls_from_many_threads_are_all_counted() -> None:
    meter = UsageMeter()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: meter.add(call("embedding", 0.0001)), range(400)))

    assert meter.summary()["calls"] == 400
