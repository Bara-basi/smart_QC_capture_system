import { onMounted, onUnmounted, watch } from 'vue'

// Track screens, not individual photos or task subtabs.
export function useNavigationHistory<T>(key: () => string, read: () => T, restore: (snapshot: T) => void,
  exit?: { confirm: () => Promise<boolean>; leave: () => void }) {
  const session = `qc-${Date.now()}-${Math.random()}`
  const entries: { key: string; snapshot: T }[] = []
  let index = 0
  let restoring = false
  let stop: (() => void) | undefined
  let returningFromGuard = false
  let prompting = false
  const state = () => ({ ...history.state, qcNavigation: { session, index } })
  function pop(event: PopStateEvent) {
    const target = event.state?.qcNavigation
    if (target?.session === session && target.index === -1 && exit) {
      returningFromGuard = true
      history.forward()
      return
    }
    if (target?.session !== session || !entries[target.index]) return
    if (returningFromGuard) {
      returningFromGuard = false
      if (!prompting) {
        prompting = true
        void exit!.confirm().then(allowed => {
          if (allowed) {
            window.removeEventListener('popstate', pop)
            exit!.leave()
          }
        }).finally(() => { prompting = false })
      }
      return
    }
    index = target.index
    restoring = true
    try { restore(entries[index].snapshot) } finally { restoring = false }
  }
  onMounted(() => {
    entries.push({ key: key(), snapshot: read() })
    if (exit) {
      history.replaceState({ ...history.state, qcNavigation: { session, index: -1 } }, '')
      history.pushState(state(), '')
    } else history.replaceState(state(), '')
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
