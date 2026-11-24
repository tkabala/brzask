import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { ConversationMessageOut, ConversationOut } from '@/client/types.gen'
import { briefs, conversations } from '@/demo/data'
import { json, problem } from '@/test/fake-api'
import { renderApp } from '@/test/render'
import { loggedInApi } from '@/test/setup-screens'

const demo = conversations[0]
if (!demo) throw new Error('no demo conversation')
const talked: ConversationOut = demo
const id = talked.article.id
const quiet = briefs.find((b) => b.article.id !== id)?.article
if (!quiet) throw new Error('a second demo brief needed')
const chat = (articleId: number) => `/articles/${String(articleId)}/chat`

const empty: ConversationOut = { ...talked, messages: [] }
const at = '2026-11-24T08:00:00Z'
const row = (
  fields: Partial<ConversationMessageOut> & Pick<ConversationMessageOut, 'id' | 'role'>,
) =>
  ({
    text: null,
    answer: null,
    status: 'done',
    searched: false,
    note: null,
    error: null,
    created_at: at,
    ...fields,
  }) satisfies ConversationMessageOut
const question = row({ id: 11, role: 'user', text: 'Is it safe?' })
const answered = (fields: Partial<ConversationMessageOut> = {}) =>
  row({
    id: 12,
    role: 'assistant',
    answer: { paragraphs: [{ text: 'Mostly, yes.', sources: [1] }], enough: true, suggestions: [] },
    ...fields,
  })
const withRows = (...messages: ConversationMessageOut[]): ConversationOut => ({
  ...talked,
  messages,
})

async function questionField() {
  return screen.findByRole('textbox', { name: 'Ask about this article' })
}

describe('conversation page', () => {
  it('an empty conversation offers three starters and sends the tapped one', async () => {
    const api = loggedInApi({ 'GET /api/v1/articles/:id/conversation': () => json(empty) })
    renderApp(chat(id))
    expect(await screen.findByRole('button', { name: 'Explain it more simply' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'What are the weak points?' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'What does this mean for me?' }))
    await waitFor(() => {
      expect(api.sent('POST /api/v1/articles/:id/conversation/messages')).toHaveLength(1)
    })
    const [sent] = api.sent('POST /api/v1/articles/:id/conversation/messages')
    expect(await sent?.json()).toEqual({ text: 'What does this mean for me?' })
  })

  it('the question appears at once with a writing row', async () => {
    let answer: (response: Response) => void = () => undefined
    let stored = false
    loggedInApi({
      'GET /api/v1/articles/:id/conversation': () =>
        json(stored ? withRows(question, answered()) : empty),
      'POST /api/v1/articles/:id/conversation/messages': () =>
        new Promise<Response>((resolve) => {
          answer = (response) => {
            stored = true
            resolve(response)
          }
        }),
    })
    const user = userEvent.setup()
    renderApp(chat(id))
    const field = await questionField()
    await user.type(field, 'Is it safe?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('Is it safe?')).toBeInTheDocument()
    expect(screen.getByText('Writing…')).toBeInTheDocument()
    expect(field).toHaveValue('')
    expect(field).toHaveFocus()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    answer(json({ question, answer: answered() }))
    expect(await screen.findByText('Mostly, yes.')).toBeInTheDocument()
    expect(screen.queryByText('Writing…')).not.toBeInTheDocument()
  })

  it('an answer renders paragraphs and source buttons that expand to title and link', async () => {
    loggedInApi({})
    renderApp(chat(id))
    const first = talked.messages[1]?.answer?.paragraphs[0]
    if (!first) throw new Error('demo answer without paragraphs')
    expect(await screen.findByText(first.text)).toBeInTheDocument()
    const [button] = screen.getAllByRole('button', { name: 'Source 1' })
    if (!button) throw new Error('no source button')
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: talked.article.title })).not.toBeInTheDocument()
    await userEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: talked.article.title })).toBeInTheDocument()
  })

  it('archive sources open through open_url, web sources in a new tab with noopener noreferrer', async () => {
    loggedInApi({})
    renderApp(chat(id))
    await userEvent.click(await screen.findByRole('button', { name: 'Source 2' }))
    const archive = screen.getByRole('link', { name: 'The previous release' })
    expect(archive).toHaveAttribute('href', `/open?id=${String(id)}`)
    await userEvent.click(screen.getByRole('button', { name: 'Source 4' }))
    const web = screen.getByRole('link', { name: 'Proxy overhead benchmark' })
    expect(web).toHaveAttribute('href', 'https://bench.example/proxy')
    expect(web).toHaveAttribute('target', '_blank')
    expect(web).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('suggestions send their text', async () => {
    const api = loggedInApi({})
    renderApp(chat(id))
    const list = await screen.findByRole('list', { name: 'Ask next' })
    await userEvent.click(
      within(list).getByRole('button', { name: 'Can the proxy run next to each client?' }),
    )
    await waitFor(() => {
      expect(api.sent('POST /api/v1/articles/:id/conversation/messages')).toHaveLength(1)
    })
    const [sent] = api.sent('POST /api/v1/articles/:id/conversation/messages')
    expect(await sent?.json()).toEqual({ text: 'Can the proxy run next to each client?' })
  })

  it('send is disabled when can_ask is false, with the reason', async () => {
    loggedInApi({
      'GET /api/v1/articles/:id/conversation': () =>
        json({ ...empty, can_ask: false, reason: 'the daily spending limit is reached' }),
    })
    const user = userEvent.setup()
    renderApp(chat(id))
    expect(await screen.findByText('the daily spending limit is reached')).toBeInTheDocument()
    await user.type(await questionField(), 'Anything?')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Explain it more simply' })).toBeDisabled()
  })

  it('send is disabled while an answer is in progress', async () => {
    loggedInApi({
      'GET /api/v1/articles/:id/conversation': () =>
        json(withRows(question, answered({ status: 'answering', answer: null }))),
    })
    const user = userEvent.setup()
    renderApp(chat(id))
    expect(await screen.findByText('Writing…')).toBeInTheDocument()
    await user.type(await questionField(), 'Another?')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('the search control is a link when enough, a primary button with the line when not', async () => {
    loggedInApi({})
    const { unmount } = renderApp(chat(id))
    const link = await screen.findByRole('button', { name: 'Search the web and the archive' })
    expect(link).toHaveAttribute('data-variant', 'link')
    expect(screen.queryByText('The material does not answer this.')).not.toBeInTheDocument()
    unmount()

    const thin = answered({
      answer: {
        paragraphs: [{ text: 'Not covered.', sources: [] }],
        enough: false,
        suggestions: [],
      },
    })
    loggedInApi({ 'GET /api/v1/articles/:id/conversation': () => json(withRows(question, thin)) })
    renderApp(chat(id))
    expect(await screen.findByText('The material does not answer this.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Search the web and the archive' })).toHaveAttribute(
      'data-variant',
      'default',
    )
  })

  it('its label follows web_search', async () => {
    loggedInApi({
      'GET /api/v1/articles/:id/conversation': () => json({ ...talked, web_search: false }),
    })
    renderApp(chat(id))
    expect(await screen.findByRole('button', { name: 'Search the archive' })).toBeInTheDocument()
  })

  it('searching refetches every 5 s until done and then shows the answer with its note', async () => {
    let calls = 0
    const api = loggedInApi({
      'GET /api/v1/articles/:id/conversation': () => {
        calls += 1
        return json(
          calls === 1
            ? withRows(question, answered())
            : calls === 2
              ? withRows(question, answered({ status: 'searching' }))
              : withRows(
                  question,
                  answered({
                    searched: true,
                    note: 'The search found nothing new.',
                  }),
                ),
        )
      },
      'POST /api/v1/conversation-messages/:id/search': () =>
        json(answered({ status: 'searching' }), 202),
    })
    renderApp(chat(id))
    await userEvent.click(
      await screen.findByRole('button', { name: 'Search the web and the archive' }),
    )
    expect(await screen.findByText('Searching…')).toBeInTheDocument()
    expect(api.sent('POST /api/v1/conversation-messages/12/search')).toHaveLength(1)
    expect(
      await screen.findByText('The search found nothing new.', {}, { timeout: 8000 }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Searching…')).not.toBeInTheDocument()
    expect(screen.getByText('Mostly, yes.')).toBeInTheDocument()
  }, 10_000)

  it('a failed answer offers try again', async () => {
    const failed = answered({ status: 'failed', answer: null, error: 'the model took too long' })
    const api = loggedInApi({
      'GET /api/v1/articles/:id/conversation': () => json(withRows(question, failed)),
      'POST /api/v1/conversation-messages/:id/retry': () => json(answered()),
    })
    renderApp(chat(id))
    expect(await screen.findByText('the model took too long')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => {
      expect(api.sent('POST /api/v1/conversation-messages/12/retry')).toHaveLength(1)
    })
  })

  it('a 409 shows the in-progress message and keeps the typed text', async () => {
    let posted = false
    loggedInApi({
      'GET /api/v1/articles/:id/conversation': () =>
        json(
          posted
            ? withRows(question, answered({ status: 'answering', answer: null }))
            : withRows(question, answered()),
        ),
      'POST /api/v1/articles/:id/conversation/messages': () => {
        posted = true
        return problem(409, 'Conflict', 'an answer is still being written')
      },
    })
    const user = userEvent.setup()
    renderApp(chat(id))
    const field = await questionField()
    await screen.findByText('Mostly, yes.')
    await user.type(field, 'And the cost?{Enter}')
    expect(await screen.findByText('An answer is still being written.')).toBeInTheDocument()
    expect(field).toHaveValue('And the cost?')
  })

  it("export buttons use the conversation's markdown endpoint", async () => {
    loggedInApi({})
    renderApp(chat(id))
    expect(await screen.findByRole('link', { name: 'Download .md' })).toHaveAttribute(
      'href',
      expect.stringMatching(new RegExp(`/articles/${String(id)}/conversation/markdown$`)) as string,
    )
  })

  it('has no export before an answer', async () => {
    loggedInApi({ 'GET /api/v1/articles/:id/conversation': () => json(empty) })
    renderApp(chat(id))
    await screen.findByRole('button', { name: 'Explain it more simply' })
    expect(screen.queryByRole('link', { name: 'Download .md' })).not.toBeInTheDocument()
  })
})

describe('ask entry', () => {
  it('the brief page shows Ask with the question count', async () => {
    loggedInApi({})
    renderApp(`/articles/${String(id)}`)
    expect(await screen.findByRole('link', { name: 'Ask (2)' })).toHaveAttribute('href', chat(id))
  })

  it('shows plain Ask without questions', async () => {
    loggedInApi({})
    renderApp(`/articles/${String(quiet.id)}`)
    expect(await screen.findByRole('link', { name: 'Ask' })).toBeInTheDocument()
  })

  it('the report page offers Ask too', async () => {
    loggedInApi({})
    renderApp('/deep-dives/1')
    expect(await screen.findByRole('link', { name: 'Ask (2)' })).toBeInTheDocument()
  })
})
