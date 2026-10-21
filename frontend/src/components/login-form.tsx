import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { z } from 'zod'

import { getSessionStateQueryKey, loginMutation } from '@/client/@tanstack/react-query.gen'
import { ProblemMessage } from '@/components/problem-message'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiProblem, setCsrfToken } from '@/lib/api'

const schema = z.object({ password: z.string().min(1) })
type Values = z.infer<typeof schema>

export function LoginForm() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { password: '' } })
  const login = useMutation({
    ...loginMutation(),
    onSuccess: (session) => {
      setCsrfToken(session.csrf_token)
      queryClient.setQueryData(getSessionStateQueryKey(), session)
      // Anything fetched while logged out is stale now.
      void queryClient.invalidateQueries()
    },
    onError: () => {
      form.resetField('password')
    },
  })

  const error = login.error
  const known =
    error instanceof ApiProblem && error.status === 401
      ? t('login.wrong')
      : error instanceof ApiProblem && error.status === 429
        ? t('login.locked', { minutes: Math.ceil((error.retryAfter ?? 60) / 60) })
        : null

  return (
    <Card className="mx-auto mt-16 w-full max-w-sm">
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl font-semibold">{t('login.title')}</h1>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4"
          noValidate
          onSubmit={(event) =>
            void form.handleSubmit((values) => {
              login.mutate({ body: values })
            })(event)
          }
        >
          <div className="grid gap-2">
            <Label htmlFor="password">{t('login.password')}</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              autoFocus
              aria-invalid={form.formState.errors.password ? true : undefined}
              aria-describedby={form.formState.errors.password ? 'password-error' : undefined}
              {...form.register('password')}
            />
            {form.formState.errors.password ? (
              <p id="password-error" className="text-sm text-destructive">
                {t('login.required')}
              </p>
            ) : null}
          </div>
          {known ? (
            <p role="alert" className="text-sm text-destructive">
              {known}
            </p>
          ) : error ? (
            <ProblemMessage error={error} />
          ) : null}
          <Button type="submit" disabled={login.isPending}>
            {login.isPending ? t('login.submitting') : t('login.submit')}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
