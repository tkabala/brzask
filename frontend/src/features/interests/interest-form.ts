import { z } from 'zod'

export const interestSchema = z.object({
  topic: z.string().trim().min(1).max(200),
  keywords: z.string(),
  notes: z.string().max(10_000),
})
export type InterestValues = z.infer<typeof interestSchema>

/** "a, b , ,c" as the API takes keywords. */
export function splitKeywords(text: string): string[] {
  return text
    .split(',')
    .map((keyword) => keyword.trim())
    .filter(Boolean)
}
