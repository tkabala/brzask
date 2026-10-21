/** The `index`-th item, failing the test when there is none. */
export function nth<T>(items: readonly T[], index: number): T {
  const item = items[index]
  if (item === undefined) throw new Error(`no item ${String(index)} among ${String(items.length)}`)
  return item
}
