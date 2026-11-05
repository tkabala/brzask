import { formatDay, nextDay, runBudget } from './format'

describe('formatDay', () => {
  it('names the day without shifting it', () => {
    expect(formatDay('2026-10-21', 'en-US')).toBe('Wednesday, October 21, 2026')
  })

  it('gives back what is not a day instead of throwing', () => {
    expect(formatDay('yesterday', 'en-US')).toBe('yesterday')
  })
})

describe('nextDay', () => {
  it('is the local day after, across a month and a year', () => {
    expect(nextDay(new Date(2026, 9, 21, 23, 30))).toBe('2026-10-22')
    expect(nextDay(new Date(2026, 11, 31, 8))).toBe('2027-01-01')
  })
})

describe('runBudget', () => {
  it('reads the budget a run recorded', () => {
    expect(
      runBudget({
        budget: { over: true, skipped: ['ranking', 'deduplication_judge'], unpriced_runs: 2 },
      }),
    ).toEqual({ over: true, skipped: ['ranking', 'deduplication_judge'], unpriced: 2 })
  })

  it('is null without a usable budget', () => {
    expect(runBudget({})).toBeNull()
    expect(runBudget({ budget: 'over' })).toBeNull()
    expect(runBudget({ budget: { skipped: 'all' } })).toBeNull()
  })
})
