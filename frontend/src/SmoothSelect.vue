<script setup lang="ts" generic="T extends string | number">
import { computed, nextTick, onMounted, onUnmounted, ref, useId } from 'vue'
const props = defineProps<{ options: { value: T; label: string }[]; label: string; variant?: 'task' }>()
const value = defineModel<T>({ required: true })
const emit = defineEmits<{ change: [] }>()
const id = useId()
const trigger = ref<HTMLButtonElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const open = ref(false)
const active = ref(0)
const position = ref<Record<string, string>>({})
const selectedLabel = computed(() => props.options.find(option => option.value === value.value)?.label || '')
function close(focus = false) {
  open.value = false
  if (focus) trigger.value?.focus({ preventScroll: true })
}
async function show() {
  if (open.value) { close(); return }
  const rect = trigger.value!.getBoundingClientRect()
  const height = Math.min(props.options.length * (props.variant === 'task' ? 49 : 36) + 16, props.variant === 'task' ? 320 : 280)
  const width = Math.min(Math.max(rect.width, 148), window.innerWidth - 24)
  const top = rect.bottom + height + 8 <= window.innerHeight ? rect.bottom + 6 : Math.max(12, rect.top - height - 6)
  position.value = { left: `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`, top: `${top}px`, width: `${width}px`, maxHeight: `${Math.min(props.variant === 'task' ? 320 : 280, window.innerHeight - top - 12)}px` }
  active.value = Math.max(0, props.options.findIndex(option => option.value === value.value))
  open.value = true
  await nextTick()
  panel.value?.focus({ preventScroll: true })
  panel.value?.children[active.value]?.scrollIntoView({ block: 'nearest' })
}
function choose(index: number) {
  const option = props.options[index]
  if (!option) return
  const changed = value.value !== option.value
  value.value = option.value
  close(true)
  if (changed) emit('change')
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); close(true); return }
  if (event.key === 'Tab') { close(true); return }
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(active.value); return }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  active.value = event.key === 'Home' ? 0 : event.key === 'End' ? props.options.length - 1 : (active.value + (event.key === 'ArrowDown' ? 1 : -1) + props.options.length) % props.options.length
  panel.value?.children[active.value]?.scrollIntoView({ block: 'nearest' })
}
function outside(event: PointerEvent) {
  if (!trigger.value?.contains(event.target as Node) && !panel.value?.contains(event.target as Node)) close()
}
function scroll(event: Event) {
  if (!panel.value?.contains(event.target as Node)) close()
}
const resize = () => close()
onMounted(() => {
  document.addEventListener('pointerdown', outside)
  window.addEventListener('scroll', scroll, true)
  window.addEventListener('resize', resize)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', outside)
  window.removeEventListener('scroll', scroll, true)
  window.removeEventListener('resize', resize)
})
</script>

<template>
  <span class="smooth-select">
    <button ref="trigger" type="button" class="select-trigger" :class="{ open, 'task-select-trigger': variant === 'task' }" :aria-label="`${label}：${selectedLabel}`" aria-haspopup="listbox" :aria-expanded="open" :aria-controls="open ? id : undefined" @click="show" @keydown.down.prevent="show" @keydown.up.prevent="show">
      <span><slot name="selected">{{ selectedLabel }}</slot></span><svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="m4 6 4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <Teleport to="body">
      <Transition name="select-panel">
        <div v-if="open" :id="id" ref="panel" class="smooth-options" :class="{ 'task-options': variant === 'task' }" :style="position" role="listbox" :aria-label="label" :aria-activedescendant="`${id}-${active}`" tabindex="-1" @keydown="keydown">
          <div v-for="(option, index) in options" :id="`${id}-${index}`" :key="option.value" class="smooth-option" :class="{ selected: option.value === value, active: index === active }" role="option" :aria-selected="option.value === value" @pointermove="active = index" @click="choose(index)">
            <slot name="option" :option="option" :index="index"><span>{{ option.label }}</span><svg v-if="option.value === value" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m5 12 4.5 4.5L19 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></slot>
          </div>
        </div>
      </Transition>
    </Teleport>
  </span>
</template>

<style scoped>
.smooth-select{display:inline-flex;min-width:0;color:#596575;font-size:12px}
.smooth-select .select-trigger{display:flex;align-items:center;justify-content:space-between;gap:16px;width:100%;min-width:100px;height:34px;padding:0 11px;border:1px solid #e1e7ef;border-radius:10px;background:#fff;color:#596575;font:inherit;cursor:pointer;transition:border-color .16s,box-shadow .16s}
.select-trigger>span{min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.select-trigger svg{width:14px;height:14px;flex:none;color:#8795a6;transition:transform .18s}
.smooth-select .select-trigger:hover{border-color:#b8c3cf}.smooth-select .select-trigger.open,.smooth-select .select-trigger:focus{outline:none;box-shadow:none}.smooth-select .select-trigger:focus-visible{outline:2px solid #8d9aaa;outline-offset:3px}.select-trigger.open svg{transform:rotate(180deg)}
.smooth-options{position:fixed;z-index:160;overflow-y:auto;overscroll-behavior:contain;touch-action:pan-y;-webkit-overflow-scrolling:touch;padding:6px;border:1px solid #e5eaf2;border-radius:14px;background:#fff;color:#445063;box-shadow:0 12px 36px #2237561c,0 3px 8px #2237560a;font:13px/1.4 Inter,"PingFang SC","Microsoft YaHei",sans-serif;outline:none}
.smooth-option{display:flex;align-items:center;justify-content:space-between;gap:14px;min-height:36px;padding:7px 10px;border-radius:9px;cursor:pointer}.smooth-option.active{background:#f3f6fb}.smooth-option.selected{background:#edf3ff;color:#2863db;font-weight:600}.smooth-option svg{width:17px;height:17px;flex:none}
.select-panel-enter-active,.select-panel-leave-active{transition:opacity .14s,transform .14s}.select-panel-enter-from,.select-panel-leave-to{opacity:0;transform:translateY(-4px)}
@media(prefers-reduced-motion:reduce){.select-panel-enter-active,.select-panel-leave-active{transition:none}}

.smooth-select .select-trigger.task-select-trigger{min-width:0;gap:8px;padding:0 10px;border-color:#dfe5ec;border-radius:8px;color:#596573;text-align:left}
.smooth-select .task-select-trigger.open{border-color:#dfe5ec;background:#fff;color:#596573}
.task-select-trigger>span{flex:1}.task-select-trigger svg{width:12px;height:12px}
.task-options{padding:8px;border-radius:16px;box-shadow:0 10px 28px #17233c1a}
.task-options .smooth-option{display:block;min-height:46px;padding:0;border-radius:10px}
.task-options .smooth-option+.smooth-option{margin-top:3px}
.task-options .smooth-option.selected{background:#eaf1ff}

.smooth-select,.smooth-select *,.smooth-options,.smooth-options *{-webkit-tap-highlight-color:transparent}
</style>
