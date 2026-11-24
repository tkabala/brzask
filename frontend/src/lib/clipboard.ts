/** False on plain-http origins, where browsers leave the clipboard out. */
export const canCopy = () => typeof navigator !== 'undefined' && 'clipboard' in navigator
