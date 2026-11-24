"""A search round the reader asked for under an answer.

One worker thread in the api runs rounds one at a time, in request order:
plan up to `WEB_QUERIES` web and `ARCHIVE_QUERIES` archive queries, gather
and read with the deep dive's functions, store what is new and answer
again. When nothing new was found, or anything fails, the earlier answer
stays with a note. The thread is a daemon: an api that stops leaves the
round, and the next start settles the row as interrupted.
"""

import contextvars
import queue
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from brzask import prompts
from brzask.clients.embeddings import Embedder
from brzask.clients.extractors import build_chain
from brzask.clients.extractors.adapters import PAGE_TIMEOUT
from brzask.clients.http import new_client, public_client
from brzask.clients.llm import LLMClient
from brzask.clients.usage import UsageMeter, combined
from brzask.clients.web_search import WebSearch, build_web_search
from brzask.config import get_settings
from brzask.config.settings import BudgetSettings
from brzask.db.models import ConversationSourceOrigin, MessageRole, MessageStatus
from brzask.log import get_logger
from brzask.prompts import Language
from brzask.repositories import BriefRepository, ContentRepository, ConversationRepository
from brzask.repositories.conversations import (
    AnswerInProgressError,
    NewSource,
    NotLatestAnswerError,
)
from brzask.services.conversation import context
from brzask.services.conversation.ask import (
    ANSWER_TIMEOUT,
    BUSY,
    AnswerBusyError,
    BoundedModel,
    BudgetReachedError,
    material,
    refusal,
    write,
)
from brzask.services.deep_dive.gather import archive_candidates, read_sources, web_candidates
from brzask.services.deep_dive.plan import QUERY_CHARS, Queries, clean_queries
from brzask.services.digest.extraction import TextExtractor
from brzask.services.embeddings import active_model
from brzask.services.errors import ConflictError, NotFoundError
from brzask.services.search import QueryEmbedder

log = get_logger(__name__)

# Real check (2026-11-24, 4 rounds): a round took 24-51 s and cost
# $0.012-0.013, of which the 2 web searches were $0.011; it added 4-6 sources
# and, with the new sources named in the prompt, the rewrite cited them in 2 of
# 2 rounds (0 of 1 before). More queries would add cost at the same rate.
WEB_QUERIES = 2
ARCHIVE_QUERIES = 1  # each keeps at most the deep dive's ARCHIVE_SOURCES (3) articles
WEB_PAGES = 5  # web results read
ERROR_CHARS = 300

NOTHING_NEW = "The search found nothing new."
NOTHING_USED = "The search found nothing that answers this."
_ORIGINS = {"archive": ConversationSourceOrigin.ARCHIVE, "web": ConversationSourceOrigin.WEB}


@dataclass(frozen=True, slots=True)
class SearchClients:
    llm: BoundedModel
    embedder: QueryEmbedder
    extractor: TextExtractor
    search: WebSearch | None  # None: WEB_SEARCH is not configured, the archive only
    language: Language
    clock: Callable[[], float] = field(default=time.monotonic)


def parse_search_queries(value: Any, question: str) -> Queries:
    """The model's queries, cleaned; the question itself when none is usable."""
    if not isinstance(value, dict):
        value = {}
    web = clean_queries(value.get("web"), WEB_QUERIES)
    archive = clean_queries(value.get("archive"), ARCHIVE_QUERIES)
    if not web and not archive:
        query = question.strip()[:QUERY_CHARS].strip()
        return Queries([query], [], [query]) if query else Queries()
    return Queries(web, [], archive)


def start_search(
    session: Session, message_id: int, budget: BudgetSettings | None, tz: tzinfo, now: datetime
) -> None:
    """Put the latest answer into `searching`; the worker then runs the round."""
    repository = ConversationRepository(session)
    message = repository.message(message_id)
    if message is None or message.role is not MessageRole.ASSISTANT:
        raise NotFoundError(f"no answer {message_id}")
    reason = refusal(session, message.conversation.article_id, budget, tz, now)
    if reason is not None:
        raise BudgetReachedError(reason)
    try:
        repository.begin(message_id, MessageStatus.SEARCHING)
    except NotLatestAnswerError:
        raise ConflictError("only the latest answer can be searched for") from None
    except AnswerInProgressError:
        raise AnswerBusyError(BUSY) from None


def search_round(
    sessions: sessionmaker[Session], clients: SearchClients, message_id: int, now: datetime
) -> None:
    """Search for answer `message_id` and answer again; never raises."""
    meter = UsageMeter()
    try:
        note = _search(sessions, clients, message_id, meter)
    except Exception as error:
        log.warning("conversation search failed", message_id=message_id, error=str(error))
        note = (str(error) or type(error).__name__)[:ERROR_CHARS]
    if note is None:
        return
    with sessions.begin() as session:
        repository = ConversationRepository(session)
        message = repository.message(message_id)
        if message is None:
            return
        usage = combined(message.usage, meter.summary()) if meter.calls else None
        repository.keep_with_note(message_id, note, usage, datetime.now(UTC))


def _search(
    sessions: sessionmaker[Session], clients: SearchClients, message_id: int, meter: UsageMeter
) -> str | None:
    """The round; returns the note to keep the earlier answer with, None when it was rewritten."""
    with sessions() as session:
        repository = ConversationRepository(session)
        message = repository.message(message_id)
        if message is None:
            raise NotFoundError(f"no answer {message_id}")
        conversation_id = message.conversation_id
        article = message.conversation.article
        content = ContentRepository(session).get(article.id)
        if content is None:
            raise NotFoundError("the article has no stored text")
        earlier = [m for m in repository.messages(conversation_id) if m.id < message_id]
        question = next((m.text for m in reversed(earlier) if m.role is MessageRole.USER), "")
        brief = BriefRepository(session).get(article.id)
        prompt = prompts.render(
            "conversation_search",
            title=article.title,
            gist=brief.gist if brief is not None else None,
            history=context.history(earlier),
            question=question or "",
            language=clients.language,
        )

    queries = _plan(clients, prompt, question or "", meter)
    web = (
        web_candidates(queries, clients.search, article.link, meter)[0]
        if clients.search is not None
        else []
    )
    with sessions() as session:
        archive = archive_candidates(session, clients.embedder, queries.archive, article.id)
        contents = {
            item.id: stored.text
            for item in archive
            if (stored := ContentRepository(session).get(item.id)) is not None
        }
    found = read_sources(article, content, archive, contents, web[:WEB_PAGES], clients.extractor)
    new = [
        NewSource(s.url, s.title, _ORIGINS[s.origin], s.article_id, s.text)
        for s in found
        if s.origin != "article"
    ]
    with sessions.begin() as session:
        changed = ConversationRepository(session).add_sources(conversation_id, new)
    if not changed:
        return NOTHING_NEW

    started = clients.clock()
    with sessions() as session:
        material_ = material(session, message_id, clients.language, sorted(s.n for s in changed))
    answer, model = write(clients.llm, material_, meter, clients.clock, started)
    cited = {n for paragraph in answer.paragraphs for n in paragraph.sources}
    # The answer is kept as rewritten either way; the note says when the new
    # sources did not help, so the reader does not take it as searched for.
    note = None if cited & {s.n for s in changed} else NOTHING_USED
    with sessions.begin() as session:
        ConversationRepository(session).finish(
            message_id,
            answer=answer.as_json(),
            model=model,
            usage=combined(material_.usage, meter.summary()),
            searched=True,
            note=note,
            at=datetime.now(UTC),
        )
    return None


def _plan(clients: SearchClients, prompt: str, question: str, meter: UsageMeter) -> Queries:
    try:
        value, _ = clients.llm.bounded(ANSWER_TIMEOUT).complete_json(
            prompt, purpose="conversation_search", meter=meter
        )
    except Exception as error:
        log.warning("conversation search plan failed; searching for the question", error=str(error))
        value = None
    return parse_search_queries(value, question)


@contextmanager
def search_clients(sessions: sessionmaker[Session]) -> Iterator[SearchClients]:
    """Clients for one round, built from the settings and closed after it."""
    settings = get_settings()
    with ExitStack() as stack:
        with sessions() as session:
            model = active_model(session, settings.embedding.model)
        proxy = settings.fetch.proxy_target()
        pages = public_client(PAGE_TIMEOUT, settings.fetch.allowed_private_networks, proxy=proxy)
        stack.callback(pages.close)
        services = new_client(PAGE_TIMEOUT)
        stack.callback(services.close)
        llm = LLMClient.from_settings(settings.llm)
        stack.callback(llm.client.close)
        embedder = Embedder.from_settings(settings, model)
        stack.callback(embedder.client.close)
        search = build_web_search(settings)
        if search is not None:
            stack.callback(search.close)
        yield SearchClients(
            llm=llm,
            embedder=embedder,
            extractor=build_chain(settings.extractors, pages, services, proxy),
            search=search,
            language=prompts.language(settings.digest.language),
        )


class SearchWorker:
    """Runs search rounds one at a time, in the order they were asked for."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        clients: Callable[
            [sessionmaker[Session]], AbstractContextManager[SearchClients]
        ] = search_clients,
        round_: Callable[
            [sessionmaker[Session], SearchClients, int, datetime], None
        ] = search_round,
    ) -> None:
        self.sessions = sessions
        self.clients = clients
        self.round = round_
        self._queue: queue.Queue[tuple[int, contextvars.Context] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def submit(self, message_id: int) -> None:
        """Queue a round; each runs in its own caller's context (trace, log fields)."""
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._work, name="conversation-search", daemon=True
                )
                self._thread.start()
        self._queue.put((message_id, contextvars.copy_context()))

    def close(self, grace: float = 5.0) -> None:
        """Take nothing new; give the running round `grace` seconds, then leave it."""
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(grace)

    def _work(self) -> None:
        while (item := self._queue.get()) is not None:
            message_id, caller = item
            caller.run(self._run, message_id)

    def _run(self, message_id: int) -> None:
        try:
            with self.clients(self.sessions) as clients:
                self.round(self.sessions, clients, message_id, datetime.now(UTC))
        except Exception as error:
            # search_round never raises; a failure building the clients still must
            # not stop the rounds queued after this one.
            log.warning("conversation search not run", message_id=message_id, error=str(error))
