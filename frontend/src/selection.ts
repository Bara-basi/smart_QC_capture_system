export function rangeIdsInclusive(ids: string[], anchorId: string | null, targetId: string): string[] {
  const anchorIndex = anchorId ? ids.indexOf(anchorId) : -1
  const targetIndex = ids.indexOf(targetId)
  if (anchorIndex < 0 || targetIndex < 0) return [targetId]
  const start = Math.min(anchorIndex, targetIndex)
  const end = Math.max(anchorIndex, targetIndex)
  return ids.slice(start, end + 1)
}
