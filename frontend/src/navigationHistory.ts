import { onMounted, onUnmounted, watch } from 'vue'

// Track screens, not individual photos or task subtabs.
export function useNavigationHistory<T>(key: () => string, read: () => T, restore: (snapshot: T) => void) {
  const session = `qc-${Date.now()}-${Math.random()}`
  const entries: { key: string; snapshot: T }[] = []
  let index = 0
  let restoring = false
  let stop: (() => void) | undefined
  const state = () => ({ ...history.state, qcNavigation: { session, index } })
  function pop(event: PopStateEvent) {
    const target = event.state?.qcNavigation
    if (target?.session !== session || !entries[target.index]) return
    index = target.index
    restoring = true
    try { restore(entries[index].snapshot) } finally { restoring = false }
  }
  onMounted(() => {
    entries.push({ key: key(), snapshot: read() })
    history.replaceState(state(), '')
    window.addEventListener('popstate', pop)
    stop = watch(key, value => {
      if (restoring) return
      if (index > 0 && entries[index - 1].key === value) {
        history.back()
        return
      }
      entries.splice(index + 1)
      entries.push({ key: value, snapshot: read() })
      index += 1
      history.pushState(state(), '')
    }, { flush: 'sync' })
  })
  onUnmounted(() => {
    stop?.()
    window.removeEventListener('popstate', pop)
  })
}
