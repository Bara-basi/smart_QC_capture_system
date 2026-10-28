import { rangeIdsInclusive } from '../frontend/src/selection.ts'

const cases = [
  ['forward range', rangeIdsInclusive(['a', 'b', 'c', 'd'], 'a', 'c'), ['a', 'b', 'c']],
  ['reverse range', rangeIdsInclusive(['a', 'b', 'c', 'd'], 'd', 'b'), ['b', 'c', 'd']],
  ['single anchor', rangeIdsInclusive(['a', 'b', 'c'], 'b', 'b'), ['b']],
  ['missing anchor', rangeIdsInclusive(['a', 'b', 'c'], 'missing', 'b'), ['b']],
  ['missing target', rangeIdsInclusive(['a', 'b', 'c'], 'a', 'missing'), ['missing']],
]

let failed = 0
for (const [name, actual, expected] of cases) {
  const passed = JSON.stringify(actual) === JSON.stringify(expected)
  if (!passed) failed += 1
  console.log(`[${passed ? 'PASS' : 'FAIL'}] ${name}: ${JSON.stringify(actual)}`)
}
process.exitCode = failed ? 1 : 0
