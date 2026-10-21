/** The screens against the shared demo API alone, as Storybook shows them. */
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DEMO_PASSWORD, logOutDemo } from '@/demo/handlers'
import { initI18n } from '@/i18n'
import { renderApp } from '@/test/render'

beforeEach(() => {
  initI18n('en')
})

it('logs in with the demo password and shows the digest', async () => {
  logOutDemo()
  const user = userEvent.setup()
  renderApp('/')

  await user.type(await screen.findByLabelText('Password'), DEMO_PASSWORD)
  await user.click(screen.getByRole('button', { name: 'Log in' }))

  expect(await screen.findByRole('link', { name: /PostgreSQL 19 beta/ })).toBeInTheDocument()
})

it('moves an approved source out of the pending list', async () => {
  const user = userEvent.setup()
  renderApp('/sources')

  const pending = await screen.findByRole('region', { name: 'Waiting for a decision' })
  await user.click(within(pending).getByRole('button', { name: "Read it: Maurice's Blog" }))

  await vi.waitFor(() => {
    expect(within(pending).queryByText("Maurice's Blog")).not.toBeInTheDocument()
  })
  const all = screen.getByRole('region', { name: 'All sources' })
  expect(within(all).getByText("Maurice's Blog")).toBeInTheDocument()
})

it('pauses and resumes', async () => {
  const user = userEvent.setup()
  renderApp('/status')

  await user.type(await screen.findByLabelText('Pause until'), '2099-01-01')
  await user.click(screen.getByRole('button', { name: 'Pause' }))
  await user.click(await screen.findByRole('button', { name: 'Resume now' }))

  expect(await screen.findByText('The digest runs every day.')).toBeInTheDocument()
})

it('answers a missing feed as the server does', async () => {
  const user = userEvent.setup()
  renderApp('/sources')

  await user.type(await screen.findByLabelText('Feed or any page of the site'), 'nofeed')
  await user.click(screen.getByRole('button', { name: 'Add' }))

  expect(await screen.findByText('no RSS or Atom feed found for nofeed')).toBeInTheDocument()
})
