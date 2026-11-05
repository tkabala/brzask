import { onlineManager } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'

/** Whether the browser says it is online, as the query client sees it. */
export function useOnline(): boolean {
  return useSyncExternalStore(
    (onChange) => onlineManager.subscribe(onChange),
    () => onlineManager.isOnline(),
  )
}

/** The query client assumes it starts online and only hears changes; an app
 * opened without a connection must say so from the start. */
export function followBrowserOnline(): void {
  onlineManager.setOnline(navigator.onLine)
}
