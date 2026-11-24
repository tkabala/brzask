import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  askQuestionMutation,
  getBriefQueryKey,
  getConversationOptions,
  getConversationQueryKey,
  retryAnswerMutation,
  searchAnswerMutation,
} from '@/client/@tanstack/react-query.gen'
import type { ConversationMessageOut, ConversationOut } from '@/client/types.gen'
import { ExportButtons } from '@/components/export-buttons'
import { Pending } from '@/components/pending'
import { ProblemMessage } from '@/components/problem-message'
import { Button } from '@/components/ui/button'
import { ApiProblem } from '@/lib/api'

import { AskField } from './ask-field'
import { BUSY_REFETCH_MS, isBusy, latestAnswer, markdownUrl } from './lib'
import { MessageList } from './message-list'
import { STARTERS } from './starters'

/** Rows shown while the question is on its way; the server's rows replace them. */
function pendingRows(text: string): ConversationMessageOut[] {
  const now = new Date().toISOString()
  const row = { answer: null, searched: false, note: null, error: null, created_at: now }
  return [
    { ...row, id: -1, role: 'user', text, status: 'done' },
    { ...row, id: -2, role: 'assistant', text: null, status: 'answering' },
  ]
}

/** Stands for a refusal because an answer is in progress; cleared when none is. */
const BUSY = Symbol('busy')

function withMessage(data: ConversationOut, message: ConversationMessageOut): ConversationOut {
  return {
    ...data,
    messages: data.messages.map((m) => (m.id === message.id ? message : m)),
  }
}

/** What the export holds changes with every finished answer and search round. */
const exportVersion = (messages: readonly ConversationMessageOut[]) =>
  messages
    .filter((m) => m.role === 'assistant' && m.status === 'done')
    .map((m) => `${String(m.id)}${m.searched ? 's' : ''}`)
    .join(',')

/** The conversation about an article: questions answered from its stored
 * material, a search round on request, and the Markdown export. */
export function ConversationPage({ articleId }: { articleId: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [problem, setProblem] = useState<unknown>(null)
  const path = { path: { article_id: articleId } }
  const key = getConversationQueryKey(path)

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: key }),
      // The brief and the report show the number of questions.
      queryClient.invalidateQueries({ queryKey: getBriefQueryKey(path) }),
      queryClient.invalidateQueries({ queryKey: [{ _id: 'getDive' }] }),
    ])
  /** Stop refetches that would overwrite the rows set by hand, and keep the old data. */
  const hold = async () => {
    setProblem(null)
    await queryClient.cancelQueries({ queryKey: key })
    return { previous: queryClient.getQueryData<ConversationOut>(key) }
  }
  const restore = async (error: unknown, context?: { previous: ConversationOut | undefined }) => {
    if (context?.previous) queryClient.setQueryData(key, context.previous)
    if (error instanceof ApiProblem && error.status === 409) {
      // Refused while another tab's answer is written: say so, and let the
      // refetch show that answer coming in.
      await queryClient.refetchQueries({ queryKey: key })
      const latest = latestAnswer(queryClient.getQueryData<ConversationOut>(key)?.messages ?? [])
      if (latest && isBusy(latest)) {
        setProblem(BUSY)
        return
      }
    }
    setProblem(error)
  }

  const ask = useMutation({
    ...askQuestionMutation(),
    onMutate: async (variables) => {
      const context = await hold()
      if (context.previous) {
        queryClient.setQueryData(key, {
          ...context.previous,
          messages: [...context.previous.messages, ...pendingRows(variables.body.text)],
        })
      }
      return context
    },
    onSuccess: ({ question, answer }) => {
      queryClient.setQueryData<ConversationOut>(key, (data) =>
        data
          ? {
              ...data,
              messages: [
                ...data.messages.filter(
                  (m) => m.id > 0 && m.id !== question.id && m.id !== answer.id,
                ),
                question,
                answer,
              ],
            }
          : data,
      )
    },
    onError: async (error, variables, context) => {
      // The question is not lost: back in the field unless something new was typed.
      setText((current) => (current === '' ? variables.body.text : current))
      await restore(error, context)
    },
    onSettled: refresh,
  })
  const retry = useMutation({
    ...retryAnswerMutation(),
    onMutate: async (variables) => {
      const context = await hold()
      const row = context.previous?.messages.find((m) => m.id === variables.path.message_id)
      if (context.previous && row) {
        queryClient.setQueryData(
          key,
          withMessage(context.previous, { ...row, status: 'answering', error: null }),
        )
      }
      return context
    },
    onSuccess: (message) => {
      queryClient.setQueryData<ConversationOut>(key, (data) =>
        data ? withMessage(data, message) : data,
      )
    },
    onError: (error, _variables, context) => restore(error, context),
    onSettled: refresh,
  })
  const search = useMutation({
    ...searchAnswerMutation(),
    onMutate: hold,
    onSuccess: (message) => {
      queryClient.setQueryData<ConversationOut>(key, (data) =>
        data ? withMessage(data, message) : data,
      )
    },
    onError: (error, _variables, context) => restore(error, context),
    onSettled: refresh,
  })
  const sending = ask.isPending || retry.isPending

  const conversation = useQuery({
    ...getConversationOptions(path),
    // Another tab's answer, or a search round, ends on the server.
    refetchInterval: (query) => {
      const latest = query.state.data && latestAnswer(query.state.data.messages)
      return latest && isBusy(latest) && !sending ? BUSY_REFETCH_MS : false
    },
  })

  if (conversation.isPending) return <Pending query={conversation} />
  if (conversation.isError) {
    return <ProblemMessage error={conversation.error} onRetry={() => void conversation.refetch()} />
  }
  const data = conversation.data
  const latest = latestAnswer(data.messages)
  const busy = sending || search.isPending || (latest !== undefined && isBusy(latest))
  const canSend = data.can_ask && !busy
  const send = (question: string) => {
    ask.mutate({ ...path, body: { text: question } })
  }
  const shown = problem === BUSY && !busy ? null : problem

  return (
    <article className="mx-auto max-w-prose">
      <Link
        to="/articles/$id"
        params={{ id: String(articleId) }}
        className="text-sm text-muted-foreground hover:underline"
      >
        ← {t('conversation.back')}
      </Link>
      <h1 className="mt-3 mb-6 text-2xl leading-tight font-semibold tracking-tight">
        {data.article.title}
      </h1>
      {data.messages.length === 0 ? (
        <div className="flex flex-col items-start gap-2">
          {STARTERS.map((starter) => (
            <Button
              key={starter}
              variant="outline"
              disabled={!canSend}
              onClick={() => {
                send(t(starter))
              }}
            >
              {t(starter)}
            </Button>
          ))}
        </div>
      ) : (
        <MessageList
          messages={data.messages}
          sources={data.sources}
          canAsk={canSend}
          webSearch={data.web_search}
          onAsk={send}
          onRetry={(id) => {
            retry.mutate({ path: { message_id: id } })
          }}
          onSearch={(id) => {
            search.mutate({ path: { message_id: id } })
          }}
        />
      )}
      {shown ? (
        <div className="mt-4">
          {shown === BUSY ? (
            <p role="alert" className="text-sm">
              {t('conversation.busy')}
            </p>
          ) : (
            <ProblemMessage error={shown} />
          )}
        </div>
      ) : null}
      {exportVersion(data.messages) ? (
        <ExportButtons url={markdownUrl(articleId)} version={exportVersion(data.messages)} />
      ) : null}
      <AskField
        text={text}
        onText={setText}
        canSend={canSend}
        reason={data.can_ask ? null : data.reason}
        onSend={() => {
          const question = text.trim()
          setText('')
          send(question)
        }}
      />
    </article>
  )
}
