import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/')({
  component: TodayPage,
})

function TodayPage() {
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Today</h1>
      <p className="mt-2 text-muted-foreground">No digest yet.</p>
    </section>
  )
}
