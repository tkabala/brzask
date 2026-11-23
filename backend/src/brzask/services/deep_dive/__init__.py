"""Deep dives: a report on one article, written on the reader's request.

A fixed pipeline, not an agent loop: plan search queries (one LLM call),
gather candidates from the archive and the web, read them, write the report
(one LLM call). Third-party text only ever reaches the model as numbered,
marked sources; the report cites them by number (ADR 0023).
"""
