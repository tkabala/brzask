"""Conversations about articles: questions, answers and the sources they cite."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brzask.db.models import (
    Conversation,
    ConversationMessage,
    ConversationSource,
    ConversationSourceOrigin,
    MessageRole,
    MessageStatus,
)
from brzask.repositories.usage import usage_cost

IN_PROGRESS = (MessageStatus.ANSWERING, MessageStatus.SEARCHING)
INTERRUPTED = "interrupted"


class AnswerInProgressError(Exception):
    """An answer of the conversation is still being written or searched for."""


class NotLatestAnswerError(Exception):
    """Only the conversation's latest answer can be answered again or searched for."""


@dataclass(frozen=True, slots=True)
class NewSource:
    url: str
    title: str
    origin: ConversationSourceOrigin
    article_id: int | None = None
    text: str | None = None


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def for_article(self, article_id: int) -> Conversation | None:
        return self.session.scalar(
            select(Conversation).where(Conversation.article_id == article_id)
        )

    def get_or_create(self, article_id: int) -> Conversation:
        """The article's conversation; two first questions at once share one."""
        conversation = self.for_article(article_id)
        if conversation is None:
            self.session.execute(
                insert(Conversation)
                .values(article_id=article_id)
                .on_conflict_do_nothing(index_elements=[Conversation.article_id])
            )
            conversation = self.session.scalars(
                select(Conversation).where(Conversation.article_id == article_id)
            ).one()
        return conversation

    def messages(self, conversation_id: int) -> Sequence[ConversationMessage]:
        """Oldest first, in the order they were accepted."""
        return self.session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.id)
        ).all()

    def message(self, message_id: int) -> ConversationMessage | None:
        return self.session.get(ConversationMessage, message_id)

    def latest_answer(self, conversation_id: int) -> ConversationMessage | None:
        return self.session.scalar(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.role == MessageRole.ASSISTANT,
            )
            .order_by(ConversationMessage.id.desc())
            .limit(1)
            # A row this session read before the lock keeps its old status otherwise.
            .execution_options(populate_existing=True)
        )

    def add_question(
        self, conversation_id: int, text: str, at: datetime
    ) -> tuple[ConversationMessage, ConversationMessage]:
        """The question and its answer row, in progress; refused while another answer is."""
        latest = self._locked_latest(conversation_id)
        if latest is not None and latest.status in IN_PROGRESS:
            raise AnswerInProgressError(conversation_id)
        question = ConversationMessage(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            text=text,
            status=MessageStatus.DONE,
            created_at=at,
            finished_at=at,
        )
        self.session.add(question)
        self.session.flush()  # the question's id comes first: ids are the order
        answer = ConversationMessage(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            status=MessageStatus.ANSWERING,
            created_at=at,
        )
        self.session.add(answer)
        self.session.flush()
        return question, answer

    def begin(self, message_id: int, status: MessageStatus) -> None:
        """Put the latest answer back in progress, to answer again or to search."""
        message = self.message(message_id)
        if message is None or message.role is not MessageRole.ASSISTANT:
            raise NotLatestAnswerError(message_id)
        latest = self._locked_latest(message.conversation_id)
        if latest is None or latest.id != message.id:
            raise NotLatestAnswerError(message_id)
        if latest.status in IN_PROGRESS:
            raise AnswerInProgressError(message.conversation_id)
        message.status = status
        message.note = None
        message.error = None
        self.session.flush()

    def finish(
        self,
        message_id: int,
        *,
        answer: dict[str, Any],
        model: str,
        usage: dict[str, Any],
        searched: bool,
        note: str | None,
        at: datetime,
    ) -> None:
        message = self._get(message_id)
        message.status = MessageStatus.DONE
        message.answer = answer
        message.model = model
        message.usage = usage
        message.searched = searched
        message.note = note
        message.error = None
        message.finished_at = at
        self.session.flush()

    def fail(self, message_id: int, error: str, usage: dict[str, Any] | None, at: datetime) -> None:
        message = self._get(message_id)
        message.status = MessageStatus.FAILED
        message.error = error
        if usage is not None:
            message.usage = usage
        message.finished_at = at
        self.session.flush()

    def keep_with_note(
        self, message_id: int, note: str, usage: dict[str, Any] | None, at: datetime
    ) -> None:
        """End the work on an answer and keep what it had: done with the note when
        there is an answer, else failed with the note as the error."""
        message = self._get(message_id)
        if message.answer is None:
            self.fail(message_id, note, usage, at)
            return
        message.status = MessageStatus.DONE
        message.note = note
        message.error = None
        if usage is not None:
            message.usage = usage
        message.finished_at = at
        self.session.flush()

    def sources(self, conversation_id: int) -> Sequence[ConversationSource]:
        return self.session.scalars(
            select(ConversationSource)
            .where(ConversationSource.conversation_id == conversation_id)
            .order_by(ConversationSource.n)
        ).all()

    def add_sources(
        self, conversation_id: int, new: Sequence[NewSource]
    ) -> list[ConversationSource]:
        """Add sources under the next free numbers, a URL once; a known URL keeps its
        number and gains the text it lacked. Returns the sources added or given text."""
        # Numbers are taken under the conversation's lock, so two writers never
        # take the same one.
        self._lock(conversation_id)
        known = {source.url: source for source in self.sources(conversation_id)}
        next_n = max((source.n for source in known.values()), default=0) + 1
        changed: dict[int, ConversationSource] = {}
        for item in new:
            source = known.get(item.url)
            if source is None:
                source = ConversationSource(
                    conversation_id=conversation_id,
                    n=next_n,
                    url=item.url,
                    title=item.title,
                    origin=item.origin,
                    article_id=item.article_id,
                    text=item.text,
                )
                self.session.add(source)
                known[item.url] = source
                next_n += 1
            elif source.text is None and item.text is not None:
                source.text = item.text
            else:
                continue
            changed[source.n] = source
        self.session.flush()
        return sorted(changed.values(), key=lambda source: source.n)

    def question_counts(self, article_ids: Iterable[int]) -> dict[int, int]:
        """Questions asked about each article; articles without any are left out."""
        ids = list(article_ids)
        if not ids:
            return {}
        rows = self.session.execute(
            select(Conversation.article_id, func.count())
            .join(ConversationMessage)
            .where(
                Conversation.article_id.in_(ids),
                ConversationMessage.role == MessageRole.USER,
            )
            .group_by(Conversation.article_id)
        ).all()
        return {article_id: count for article_id, count in rows}

    def settle_interrupted(self, at: datetime) -> int:
        """Answers left in progress by a stopped api: kept with a note, or failed."""
        stuck = self.session.scalars(
            select(ConversationMessage.id).where(ConversationMessage.status.in_(IN_PROGRESS))
        ).all()
        for message_id in stuck:
            self.keep_with_note(message_id, INTERRUPTED, None, at)
        return len(stuck)

    def spending(self, day_start: datetime, month_start: datetime) -> tuple[Decimal, Decimal, int]:
        """Reported cost of answers since `day_start` and since `month_start`, and the
        number of answers since `month_start` with calls that reported no cost.

        An answer counts on the day its last call ended (a search round adds to an
        older answer); one never finished counts on the day it was asked.
        """
        at = func.coalesce(ConversationMessage.finished_at, ConversationMessage.created_at)
        cost, unpriced = usage_cost(ConversationMessage.usage)
        today, month, unpriced_answers = self.session.execute(
            select(
                func.coalesce(func.sum(cost).filter(at >= day_start), 0),
                func.coalesce(func.sum(cost), 0),
                func.count().filter(unpriced),
            ).where(ConversationMessage.role == MessageRole.ASSISTANT, at >= month_start)
        ).one()
        return Decimal(today), Decimal(month), int(unpriced_answers)

    def _get(self, message_id: int) -> ConversationMessage:
        message = self.message(message_id)
        if message is None:
            raise LookupError(f"no conversation message {message_id}")
        return message

    def _locked_latest(self, conversation_id: int) -> ConversationMessage | None:
        """The latest answer, read after locking the conversation's row: a second
        request waits for the first to commit, then sees its answer."""
        self._lock(conversation_id)
        return self.latest_answer(conversation_id)

    def _lock(self, conversation_id: int) -> None:
        self.session.execute(
            select(Conversation.id).where(Conversation.id == conversation_id).with_for_update()
        )
