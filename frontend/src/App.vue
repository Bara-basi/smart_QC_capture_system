<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import DesktopGallery from './DesktopGallery.vue'
import { cleanExpiredDrafts, draftsForContract, removeDraft, removeDrafts, saveDraft, type PhotoDraft } from './drafts'

type Order = { contract_no: string; started_at: string; task_count: number; pending_count: number; status: string; products: string[]; task_ids: string[] }
type Requirement = { name: string; mandatory: boolean }
type SavedPhoto = { id: string; inspection_item: string; name: string }
type ProductTask = { feishu_record_id: string; product_type: string; specification: string; inspection_stage: string; sequence_no: string | null; uploaded: boolean; requirements: Requirement[]; photos: SavedPhoto[] }
type CaptureTask = { contract_no: string; tasks: ProductTask[] }
type Dashboard = { user: { name: string }; pending_task_count: number; orders: Order[] }
type Photo = { name: string; tone: string; url: string; draftId?: string; recordId?: string }
type GalleryPhoto = { id: string; name: string; contract_no: string; product_type: string; specification: string; inspection_item: string; captured_at: string; photographer_name: string }
type GalleryResponse = { photos: GalleryPhoto[]; count: number }
type FeishuChooseImageResult = { tempFilePaths?: string[]; localIds?: string[] }
type FileSystemManager = { readFile: (options: { filePath: string; encoding?: 'base64'; success: (result: { data: string | ArrayBuffer }) => void; fail: (error: unknown) => void }) => void }

declare global {
  interface Window {
    h5sdk?: { config: (options: Record<string, unknown>) => void; ready: (callback: () => void) => void; error?: (callback: (error: unknown) => void) => void }
    tt?: { chooseImage: (options: { count: number; sourceType: string[]; sizeType?: string[]; success: (result: FeishuChooseImageResult) => void; fail: (error: unknown) => void }) => void; getFileSystemManager?: () => FileSystemManager }
  }
}

const page = ref<'home' | 'capture' | 'gallery'>('home')
const isDesktopGalleryRoute = window.location.pathname === '/gallery' || window.location.pathname === '/gallery/'
const dashboard = ref<Dashboard | null>(null)
const activeTask = ref<CaptureTask | null>(null)
const isLoading = ref(true)
const error = ref('')
const openSubtask = ref(0)
const photos = ref<Record<string, Photo[]>>({})
const cameraError = ref('')
const submitError = ref('')
const isSubmitting = ref(false)
const uploadedTaskIds = ref<Set<string>>(new Set())
const submitStatus = ref<'idle' | 'uploading' | 'success' | 'error'>('idle')
const touchStartX = ref(0)
const taskTabs = ref<HTMLElement | null>(null)
const editingTaskIds = ref<Set<string>>(new Set())
const galleryPhotos = ref<GalleryPhoto[]>([])
const galleryLoading = ref(false)
const galleryError = ref('')
const galleryProduct = ref('')
const galleryPart = ref('')
const galleryFrom = ref('')
const galleryTo = ref('')
const galleryScope = ref<'mine' | 'shared'>('mine')
const gallerySearch = ref('')
const gallerySort = ref<'asc' | 'desc'>('desc')
const galleryView = ref<'list' | 'grid'>('list')
const galleryFilterOpen = ref<'product' | 'part' | 'date' | null>(null)
const selectedGalleryPhoto = ref<GalleryPhoto | null>(null)
const fullPhotoLoaded = ref(false)
const photoScale = ref(1)
const photoOffsetX = ref(0)
const photoOffsetY = ref(0)
const photoDragging = ref(false)
const viewerImage = ref<HTMLImageElement | null>(null)
const activePhotoPointers = new Map<number, { x: number; y: number }>()
let panOrigin = { x: 0, y: 0, offsetX: 0, offsetY: 0 }
let pinchOrigin = { distance: 0, scale: 1, contentX: 0, contentY: 0 }
const calendarCursor = ref(new Date(new Date().getFullYear(), new Date().getMonth(), 1))
const productOptions = ['管件', '法兰', '管子', '焊管', '无缝管', '板材', '棒材', '盘管', '其它']
const partOptions = [
  { value: 'material', label: '材质光谱' }, { value: 'surface', label: '内外表面' },
  { value: 'dimension', label: '尺寸' }, { value: 'marking', label: '喷码' },
  { value: 'port', label: '端口坡口' }, { value: 'weld', label: '焊道' },
]
let gallerySearchTimer = 0
let jsapiReady: Promise<void> | null = null
const DEFAULT_REQUEST_TIMEOUT_MS = 20_000
const UPLOAD_REQUEST_TIMEOUT_MS = 180_000
const MAX_UPLOAD_DIMENSION = 1920

const surname = computed(() => dashboard.value?.user.name?.slice(0, 1) || '质')
const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 5) return `夜深了，${surname.value}工，注意休息`
  const time = hour < 12 ? '上午好' : hour < 18 ? '下午好' : '晚上好'
  return `${time}，${surname.value}工`
})
const todayText = computed(() => `今天有 ${dashboard.value?.pending_task_count || 0} 个拍照任务`)
const photoKey = (taskId: string, requirement: string) => `${taskId}:${requirement}`
const currentTask = computed(() => activeTask.value?.tasks[openSubtask.value] || null)
const isTaskComplete = computed(() => currentTask.value?.requirements.filter(item => item.mandatory).every(item => (photos.value[photoKey(currentTask.value!.feishu_record_id, item.name)] || []).length > 0) ?? false)
const completedTaskCount = computed(() => activeTask.value?.tasks.filter(task => uploadedTaskIds.value.has(task.feishu_record_id)).length || 0)
const captureProgress = computed(() => activeTask.value?.tasks.length ? completedTaskCount.value / activeTask.value.tasks.length * 100 : 0)
const galleryPartLabel = computed(() => partOptions.find(option => option.value === galleryPart.value)?.label || '全部部位')
const galleryDateLabel = computed(() => galleryFrom.value || galleryTo.value ? `${galleryFrom.value || '最早'} 至 ${galleryTo.value || '今天'}` : '全部时间')
const calendarTitle = computed(() => `${calendarCursor.value.getFullYear()} 年 ${calendarCursor.value.getMonth() + 1} 月`)
const calendarDays = computed<(Date | null)[]>(() => {
  const year = calendarCursor.value.getFullYear()
  const month = calendarCursor.value.getMonth()
  const leading = (new Date(year, month, 1).getDay() + 6) % 7
  const count = new Date(year, month + 1, 0).getDate()
  return [...Array<Date | null>(leading).fill(null), ...Array.from({ length: count }, (_, index) => new Date(year, month, index + 1))]
})
const photoTransform = computed(() => `translate(${photoOffsetX.value}px, ${photoOffsetY.value}px) scale(${photoScale.value})`)

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? '—' : `开始于${String(date.getMonth() + 1).padStart(2, '0')}月${String(date.getDate()).padStart(2, '0')}日`
}

async function request<T>(url: string): Promise<T> {
  const response = await fetchWithTimeout(url, { credentials: 'include' })
  if (response.status === 401) {
    window.location.replace('/api/v1/auth/feishu/login')
    throw new Error('登录已过期，正在跳转到飞书登录')
  }
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || '加载失败')
  return response.json()
}

async function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit = {}, timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(input, { ...init, signal: controller.signal })
  } catch (cause) {
    if (controller.signal.aborted) throw new Error('网络连接超时，请检查网络后重试')
    throw cause
  } finally {
    window.clearTimeout(timer)
  }
}

async function loadDashboard() {
  dashboard.value = await request<Dashboard>('/api/v1/dashboard')
}

function galleryDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? '未知时间' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

async function loadGallery() {
  galleryLoading.value = true
  galleryError.value = ''
  try {
    const query = new URLSearchParams({ sort: gallerySort.value, scope: galleryScope.value })
    if (galleryProduct.value) query.set('product_type', galleryProduct.value)
    if (galleryPart.value) query.set('inspection_category', galleryPart.value)
    if (galleryFrom.value) query.set('captured_from', galleryFrom.value)
    if (galleryTo.value) query.set('captured_to', galleryTo.value)
    if (gallerySearch.value.trim()) query.set('q', gallerySearch.value.trim())
    galleryPhotos.value = (await request<GalleryResponse>(`/api/v1/photos?${query}`)).photos
  } catch (cause) {
    galleryError.value = cause instanceof Error ? cause.message : '图片加载失败'
  } finally { galleryLoading.value = false }
}

function scheduleGallerySearch() {
  window.clearTimeout(gallerySearchTimer)
  gallerySearchTimer = window.setTimeout(loadGallery, 320)
}

function clearGallerySearch() {
  gallerySearch.value = ''
  window.clearTimeout(gallerySearchTimer)
  loadGallery()
}

function selectGalleryScope(scope: 'mine' | 'shared') {
  if (galleryScope.value === scope) return
  galleryScope.value = scope
  galleryFilterOpen.value = null
  loadGallery()
}

function toggleGalleryFilter(filter: 'product' | 'part' | 'date') {
  galleryFilterOpen.value = galleryFilterOpen.value === filter ? null : filter
}

function selectProduct(value: string) {
  galleryProduct.value = value
  galleryFilterOpen.value = null
  loadGallery()
}

function selectPart(value: string) {
  galleryPart.value = value
  galleryFilterOpen.value = null
  loadGallery()
}

function localDateValue(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function calendarDayClass(day: Date | null) {
  if (!day) return {}
  const value = localDateValue(day)
  return {
    selected: value === galleryFrom.value || value === galleryTo.value,
    ranged: Boolean(galleryFrom.value && galleryTo.value && value > galleryFrom.value && value < galleryTo.value),
    today: value === localDateValue(new Date()),
  }
}

function selectCalendarDay(day: Date | null) {
  if (!day) return
  const value = localDateValue(day)
  if (!galleryFrom.value || galleryTo.value || value < galleryFrom.value) {
    galleryFrom.value = value
    galleryTo.value = ''
  } else {
    galleryTo.value = value
  }
}

function moveCalendar(months: number) {
  calendarCursor.value = new Date(calendarCursor.value.getFullYear(), calendarCursor.value.getMonth() + months, 1)
}

function setDatePreset(kind: 'today' | 'week' | 'month') {
  const today = new Date()
  const from = new Date(today)
  if (kind === 'week') from.setDate(today.getDate() - 6)
  if (kind === 'month') from.setDate(1)
  galleryFrom.value = localDateValue(from)
  galleryTo.value = localDateValue(today)
  calendarCursor.value = new Date(today.getFullYear(), today.getMonth(), 1)
  galleryFilterOpen.value = null
  loadGallery()
}

function applyDateFilter() {
  galleryFilterOpen.value = null
  loadGallery()
}

function clearDateFilter() {
  galleryFrom.value = ''
  galleryTo.value = ''
  galleryFilterOpen.value = null
  loadGallery()
}

function galleryPhotoUrl(photo: GalleryPhoto, kind: 'preview' | 'full' | 'download') {
  return `/api/v1/feishu/photos/${photo.id}/${kind}?scope=${galleryScope.value}`
}

function openGalleryPhoto(photo: GalleryPhoto) {
  selectedGalleryPhoto.value = photo
  fullPhotoLoaded.value = false
  resetPhotoZoom()
}

function closeGalleryPhoto() {
  selectedGalleryPhoto.value = null
  resetPhotoZoom()
}

function resetPhotoZoom() {
  photoScale.value = 1
  photoOffsetX.value = 0
  photoOffsetY.value = 0
  photoDragging.value = false
  activePhotoPointers.clear()
}

function clampScale(value: number) {
  return Math.min(5, Math.max(1, value))
}

function pointerDistance(first: { x: number; y: number }, second: { x: number; y: number }) {
  return Math.hypot(second.x - first.x, second.y - first.y)
}

function pointerCenter(first: { x: number; y: number }, second: { x: number; y: number }) {
  return { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 }
}

function clampPhotoOffsets(stage: HTMLElement) {
  const image = viewerImage.value
  if (photoScale.value <= 1 || !image) {
    photoOffsetX.value = 0
    photoOffsetY.value = 0
    return
  }
  const maxX = Math.max(0, (image.clientWidth * photoScale.value - stage.clientWidth) / 2)
  const maxY = Math.max(0, (image.clientHeight * photoScale.value - stage.clientHeight) / 2)
  photoOffsetX.value = Math.min(maxX, Math.max(-maxX, photoOffsetX.value))
  photoOffsetY.value = Math.min(maxY, Math.max(-maxY, photoOffsetY.value))
}

function beginPinch(stage: HTMLElement) {
  const [first, second] = [...activePhotoPointers.values()]
  if (!first || !second) return
  const center = pointerCenter(first, second)
  const rect = stage.getBoundingClientRect()
  const focalX = center.x - (rect.left + rect.width / 2)
  const focalY = center.y - (rect.top + rect.height / 2)
  pinchOrigin = {
    distance: Math.max(1, pointerDistance(first, second)),
    scale: photoScale.value,
    contentX: (focalX - photoOffsetX.value) / photoScale.value,
    contentY: (focalY - photoOffsetY.value) / photoScale.value,
  }
}

function zoomAround(stage: HTMLElement, clientX: number, clientY: number, nextScale: number) {
  const rect = stage.getBoundingClientRect()
  const focalX = clientX - (rect.left + rect.width / 2)
  const focalY = clientY - (rect.top + rect.height / 2)
  const contentX = (focalX - photoOffsetX.value) / photoScale.value
  const contentY = (focalY - photoOffsetY.value) / photoScale.value
  photoScale.value = clampScale(nextScale)
  photoOffsetX.value = focalX - contentX * photoScale.value
  photoOffsetY.value = focalY - contentY * photoScale.value
  clampPhotoOffsets(stage)
}

function onPhotoWheel(event: WheelEvent) {
  const factor = event.deltaY < 0 ? 1.16 : 1 / 1.16
  zoomAround(event.currentTarget as HTMLElement, event.clientX, event.clientY, photoScale.value * factor)
}

function startPhotoGesture(event: PointerEvent) {
  if (activePhotoPointers.size >= 2) return
  const stage = event.currentTarget as HTMLElement
  stage.setPointerCapture(event.pointerId)
  activePhotoPointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  if (activePhotoPointers.size === 1) {
    panOrigin = { x: event.clientX, y: event.clientY, offsetX: photoOffsetX.value, offsetY: photoOffsetY.value }
  } else if (activePhotoPointers.size === 2) {
    photoDragging.value = true
    beginPinch(stage)
  }
}

function movePhotoGesture(event: PointerEvent) {
  if (!activePhotoPointers.has(event.pointerId)) return
  const stage = event.currentTarget as HTMLElement
  activePhotoPointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  if (activePhotoPointers.size >= 2) {
    const [first, second] = [...activePhotoPointers.values()]
    if (!first || !second) return
    const center = pointerCenter(first, second)
    const rect = stage.getBoundingClientRect()
    const focalX = center.x - (rect.left + rect.width / 2)
    const focalY = center.y - (rect.top + rect.height / 2)
    photoScale.value = clampScale(pinchOrigin.scale * pointerDistance(first, second) / pinchOrigin.distance)
    photoOffsetX.value = focalX - pinchOrigin.contentX * photoScale.value
    photoOffsetY.value = focalY - pinchOrigin.contentY * photoScale.value
    clampPhotoOffsets(stage)
  } else if (photoScale.value > 1) {
    photoDragging.value = true
    photoOffsetX.value = panOrigin.offsetX + event.clientX - panOrigin.x
    photoOffsetY.value = panOrigin.offsetY + event.clientY - panOrigin.y
    clampPhotoOffsets(stage)
  }
}

function stopPhotoGesture(event: PointerEvent) {
  activePhotoPointers.delete(event.pointerId)
  const remaining = [...activePhotoPointers.values()][0]
  if (remaining) {
    panOrigin = { x: remaining.x, y: remaining.y, offsetX: photoOffsetX.value, offsetY: photoOffsetY.value }
    photoDragging.value = photoScale.value > 1
  } else {
    photoDragging.value = false
  }
}

async function openGallery() {
  page.value = 'gallery'
  await loadGallery()
}

async function openTask(recordId: string) {
  activeTask.value = await request<CaptureTask>(`/api/v1/dashboard/tasks/${recordId}`)
  photos.value = {}
  uploadedTaskIds.value = new Set(activeTask.value.tasks.filter(task => task.uploaded).map(task => task.feishu_record_id))
  restoreSavedPhotos()
  openSubtask.value = 0
  await restoreDrafts()
  page.value = 'capture'
}

function openFirstTask() {
  const taskId = dashboard.value?.orders[0]?.task_ids[0]
  if (taskId) openTask(taskId)
}

async function configureFeishuJsapi() {
  if (jsapiReady) return jsapiReady
  if (!window.h5sdk || !window.tt) throw new Error('请在飞书手机客户端内打开后使用拍照功能')
  jsapiReady = (async () => {
    const url = window.location.href.split('#')[0]
    const response = await fetch(`/api/v1/feishu/jsapi-signature?url=${encodeURIComponent(url)}`, { credentials: 'include' })
    if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || '飞书拍照服务初始化失败')
    const signature = await response.json()
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(() => reject(new Error('飞书拍照服务初始化超时，请检查网络后重试')), 12_000)
      window.h5sdk!.config({ appId: signature.app_id, timestamp: signature.timestamp, nonceStr: signature.noncestr, signature: signature.signature, jsApiList: ['chooseImage'] })
      window.h5sdk!.ready(() => { window.clearTimeout(timer); resolve() })
      window.h5sdk!.error?.((cause) => { window.clearTimeout(timer); reject(cause) })
    })
  })()
  try { await jsapiReady } catch (error) { jsapiReady = null; throw error }
}

async function addPhoto(taskId: string, requirement: string) {
  cameraError.value = ''
  try {
    await configureFeishuJsapi()
    const result = await new Promise<FeishuChooseImageResult>((resolve, reject) => window.tt!.chooseImage({ count: 1, sourceType: ['camera'], sizeType: ['compressed'], success: resolve, fail: reject }))
    const localPath = result.tempFilePaths?.[0] || result.localIds?.[0]
    if (!localPath) return
    const task = activeTask.value?.tasks.find(item => item.feishu_record_id === taskId)
    if (!task || !activeTask.value) throw new Error('拍照任务已失效，请返回后重新进入')
    const image = await optimizePhotoForUpload(await readTemporaryPhoto(localPath))
    const capturedAt = new Date().toISOString()
    const draft: PhotoDraft = { id: crypto.randomUUID(), contractNo: activeTask.value.contract_no, taskId, inspectionItem: requirement, capturedAt, image, createdAt: Date.now() }
    await saveDraft(draft)
    const imageUrl = draftPreview(draft)
    const list = photos.value[photoKey(taskId, requirement)] ||= []
    list.push({ name: buildPhotoName(activeTask.value.contract_no, task.specification, task.product_type, requirement), tone: ['steel-a', 'steel-b', 'steel-c'][list.length % 3], url: imageUrl, draftId: draft.id })
  } catch (cause) {
    cameraError.value = cameraFailureMessage(cause)
  }
}

function cameraFailureMessage(cause: unknown) {
  let detail = ''
  if (cause instanceof Error) {
    detail = cause.message
  } else if (cause && typeof cause === 'object') {
    const value = cause as Record<string, unknown>
    detail = [value.errMsg, value.message, value.errorMessage].find(item => typeof item === 'string') as string || ''
  } else if (typeof cause === 'string') {
    detail = cause
  }
  if (!detail || /cancel|cancelled|canceled|abort|取消/i.test(detail)) return ''
  if (/请在飞书|升级飞书|相机权限/.test(detail)) return detail
  return '暂时无法使用相机，请检查飞书相机权限后重试'
}

function buildPhotoName(contractNo: string, specification: string, productType: string, requirement: string) {
  return [contractNo, specification || '未填写规格', productType || '未填写产品类型', requirement].join('_').replace(/[\\/:*?"<>|]/g, '-').replace(/\s+/g, ' ').trim() + '.jpg'
}

async function readTemporaryPhoto(filePath: string): Promise<Blob> {
  const manager = window.tt?.getFileSystemManager?.()
  if (!manager) throw new Error('当前飞书版本不支持读取临时照片，请升级飞书后重试')
  const base64 = await new Promise<string>((resolve, reject) => manager.readFile({ filePath, encoding: 'base64', success: ({ data }) => typeof data === 'string' ? resolve(data) : reject(new Error('临时照片格式不受支持')), fail: reject }))
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return new Blob([bytes], { type: 'image/jpeg' })
}

async function optimizePhotoForUpload(source: Blob): Promise<Blob> {
  const sourceUrl = URL.createObjectURL(source)
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const element = new Image()
      element.onload = () => resolve(element)
      element.onerror = () => reject(new Error('无法读取拍摄的图片'))
      element.src = sourceUrl
    })
    const longestSide = Math.max(image.naturalWidth, image.naturalHeight)
    if (longestSide <= MAX_UPLOAD_DIMENSION && source.size <= 3 * 1024 * 1024) return source
    const scale = Math.min(1, MAX_UPLOAD_DIMENSION / longestSide)
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
    const context = canvas.getContext('2d')
    if (!context) return source
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const compressed = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', .82))
    return compressed && compressed.size < source.size ? compressed : source
  } catch {
    // The server still validates and watermarks the original image. Do not
    // prevent an inspector from submitting if this client-only optimization fails.
    return source
  } finally {
    URL.revokeObjectURL(sourceUrl)
  }
}

async function removePhoto(taskId: string, requirement: string, index: number) {
  const removed = photos.value[photoKey(taskId, requirement)]?.splice(index, 1)[0]
  if (removed) {
    URL.revokeObjectURL(removed.url)
    try {
      if (removed.draftId) await removeDraft(removed.draftId)
      if (removed.recordId) {
        const response = await fetch(`/api/v1/photos/${removed.recordId}`, { method: 'DELETE', credentials: 'include' })
        if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || '删除已上传照片失败')
        editingTaskIds.value = new Set([...editingTaskIds.value, taskId])
        uploadedTaskIds.value = new Set([...uploadedTaskIds.value].filter(id => id !== taskId))
      }
    } catch (cause) {
      photos.value[photoKey(taskId, requirement)]?.splice(index, 0, removed)
      cameraError.value = cause instanceof Error ? cause.message : '删除照片失败'
    }
  }
}

function restoreSavedPhotos() {
  if (!activeTask.value) return
  for (const task of activeTask.value.tasks) {
    for (const saved of task.photos) {
      const list = photos.value[photoKey(task.feishu_record_id, saved.inspection_item)] ||= []
      list.push({ name: saved.name, tone: ['steel-a', 'steel-b', 'steel-c'][list.length % 3], url: `/api/v1/feishu/photos/${saved.id}/preview`, recordId: saved.id })
    }
  }
}

function editTask(taskId: string) { editingTaskIds.value = new Set([...editingTaskIds.value, taskId]) }

async function restoreDrafts() {
  if (!activeTask.value) return
  await cleanExpiredDrafts()
  const taskById = new Map(activeTask.value.tasks.map(task => [task.feishu_record_id, task]))
  for (const draft of await draftsForContract(activeTask.value.contract_no)) {
    const task = taskById.get(draft.taskId)
    if (!task) continue
    const list = photos.value[photoKey(draft.taskId, draft.inspectionItem)] ||= []
    list.push({ name: buildPhotoName(activeTask.value.contract_no, task.specification, task.product_type, draft.inspectionItem), tone: ['steel-a', 'steel-b', 'steel-c'][list.length % 3], url: draftPreview(draft), draftId: draft.id })
  }
}

function draftPreview(draft: PhotoDraft): string {
  return URL.createObjectURL(draft.image)
}

async function submitPhotos(taskId: string) {
  if (!activeTask.value || isSubmitting.value || uploadedTaskIds.value.has(taskId)) return
  submitError.value = ''
  submitStatus.value = 'uploading'
  isSubmitting.value = true
  try {
    const drafts = (await draftsForContract(activeTask.value.contract_no)).filter(draft => draft.taskId === taskId)
    if (!drafts.length) throw new Error('未找到待上传照片，请重新拍摄')
    const form = new FormData()
    form.append('manifest', JSON.stringify({ contract_no: activeTask.value.contract_no, photos: drafts.map((draft, index) => ({ file_index: index, task_feishu_record_id: draft.taskId, inspection_item: draft.inspectionItem, client_captured_at: draft.capturedAt })) }))
    drafts.forEach((draft, index) => form.append('files', draft.image, `capture-${index}.jpg`))
    const response = await fetchWithTimeout('/api/v1/photos/commit', { method: 'POST', credentials: 'include', body: form }, UPLOAD_REQUEST_TIMEOUT_MS)
    if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || '提交上传失败')
    await removeDrafts(drafts.map(draft => draft.id))
    Object.entries(photos.value).filter(([key]) => key.startsWith(`${taskId}:`)).forEach(([, list]) => list.forEach(photo => URL.revokeObjectURL(photo.url)))
    Object.keys(photos.value).filter(key => key.startsWith(`${taskId}:`)).forEach(key => delete photos.value[key])
    uploadedTaskIds.value = new Set([...uploadedTaskIds.value, taskId])
    editingTaskIds.value = new Set([...editingTaskIds.value].filter(id => id !== taskId))
    await loadDashboard()
    submitStatus.value = 'success'
    window.setTimeout(() => { if (submitStatus.value === 'success') submitStatus.value = 'idle' }, 1600)
  } catch (cause) {
    submitError.value = cause instanceof Error ? cause.message : '提交上传失败，请稍后重试'
    submitStatus.value = 'error'
  } finally { isSubmitting.value = false }
}

function selectTask(index: number) {
  if (activeTask.value && index >= 0 && index < activeTask.value.tasks.length) {
    openSubtask.value = index
    nextTick(() => taskTabs.value?.children[index]?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' }))
  }
}

function onSwipeStart(event: TouchEvent) { touchStartX.value = event.touches[0]?.clientX || 0 }
function onSwipeEnd(event: TouchEvent) {
  const delta = (event.changedTouches[0]?.clientX || 0) - touchStartX.value
  if (Math.abs(delta) > 48) selectTask(openSubtask.value + (delta < 0 ? 1 : -1))
}

onMounted(async () => {
  if (isDesktopGalleryRoute) return
  // Local draft cleanup must never delay login or the homepage, especially in
  // iOS WebViews where IndexedDB may be unavailable.
  void cleanExpiredDrafts()
  try { await loadDashboard() } catch (cause) { error.value = cause instanceof Error ? cause.message : '加载失败' } finally { isLoading.value = false }
})
</script>

<template>
  <DesktopGallery v-if="isDesktopGalleryRoute" />
  <main v-else class="stage">
    <div class="phone">
      <div v-if="isLoading" class="loading">正在加载任务…</div>
      <div v-else-if="error" class="loading">{{ error }}</div>
      <template v-else>
        <section v-if="page === 'home'" class="screen home-screen">
          <header class="topbar centered-title"><span class="brand-mark">QC</span><strong>质检拍照</strong><span class="header-space"/></header>
          <div class="greeting"><div class="avatar">{{ surname }}</div><div><p class="eyebrow">{{ greeting }}</p><h1>{{ todayText }}</h1><p class="muted">每一张照片，都让交付更有凭据。</p></div></div>
          <div class="todo-card" :class="{ interactive: dashboard?.orders.length }" role="button" :aria-disabled="!dashboard?.orders.length" :tabindex="dashboard?.orders.length ? 0 : -1" @click="openFirstTask" @keydown.enter="openFirstTask" @keydown.space.prevent="openFirstTask"><div class="card-heading"><span>我的待办</span></div><div class="todo-row"><div class="todo-icon">✓</div><div><b>{{ dashboard?.pending_task_count || 0 }}</b><small>待处理</small></div><div class="todo-sep"/><div><b>{{ dashboard?.orders.filter(order => order.status === 'completed').length || 0 }}</b><small>已完成订单</small></div><span class="go">›</span></div></div>
          <div class="list-title"><div><p class="eyebrow">合同任务</p><h2>待处理订单</h2></div></div>
          <p v-if="!dashboard?.orders.length" class="empty">暂无分配给你的待处理任务</p>
          <article v-for="order in dashboard?.orders" :key="order.contract_no" class="contract-card" :class="{ completed: order.status === 'completed' }" @click="openTask(order.task_ids[0])"><div class="contract-top"><span class="status" :class="{ done: order.status === 'completed' }">{{ order.status === 'completed' ? '已完成' : '待拍摄' }}</span><span class="due">{{ formatDate(order.started_at) }}</span></div><h3>{{ order.contract_no }}</h3><div class="tag-row"><span v-for="product in order.products" :key="product">{{ product }}</span></div><div class="progress"><i :style="{ width: `${order.task_count ? (order.task_count - order.pending_count) / order.task_count * 100 : 0}%` }"/></div><footer><span>{{ order.status === 'completed' ? `已完成 ${order.task_count} / ${order.task_count} 项任务` : `剩余 ${order.pending_count} / ${order.task_count} 项任务` }}</span><b>{{ order.status === 'completed' ? '查看详情 ›' : '进入拍摄 ›' }}</b></footer></article>
        </section>

        <section v-else-if="page === 'capture' && activeTask" class="screen capture-screen">
          <header class="topbar capture-topbar"><button class="back" @click="page = 'home'">‹</button><strong>拍照任务</strong><span/></header>
          <article class="order-card"><div><span class="eyebrow">合同编号</span><h2>{{ activeTask.contract_no }}</h2><p>共 {{ activeTask.tasks.length }} 个产品子任务</p></div><div class="order-badge"><b>{{ activeTask.tasks.length }}</b><small>产品子任务</small></div></article>
          <div class="capture-progress"><div><b>拍摄进度</b><span>{{ completedTaskCount }} / {{ activeTask.tasks.length }} 已提交</span></div><div class="progress"><i :style="{ width: `${captureProgress}%` }"/></div></div>
          <div ref="taskTabs" class="task-tabs"><button v-for="(task, index) in activeTask.tasks" :key="task.feishu_record_id" :class="{ active: index === openSubtask, done: uploadedTaskIds.has(task.feishu_record_id) }" @click="selectTask(index)"><i v-if="!uploadedTaskIds.has(task.feishu_record_id)"/><span>{{ task.sequence_no || `任务 ${index + 1}` }}</span></button></div>
          <p class="hint">带 <em>*</em> 的项目为必拍项；左右滑动可切换合同序号任务。</p>
          <p v-if="cameraError" class="camera-error">{{ cameraError }}</p>
          <p v-if="submitError" class="camera-error">{{ submitError }}</p>
          <div class="task-swipe" @touchstart.passive="onSwipeStart" @touchend.passive="onSwipeEnd">
            <div v-for="(task, taskIndex) in activeTask.tasks.slice(openSubtask, openSubtask + 1)" :key="task.feishu_record_id" class="capture-group open">
              <div class="group-head"><span class="component-icon">◈</span><b>{{ task.specification || '未填写规格' }} · {{ task.product_type }}</b><button v-if="uploadedTaskIds.has(task.feishu_record_id) && !editingTaskIds.has(task.feishu_record_id)" class="edit-task" @click="editTask(task.feishu_record_id)">编辑照片</button><small>{{ openSubtask + 1 }} / {{ activeTask.tasks.length }}</small></div>
              <div class="group-content">
                <div v-for="requirement in task.requirements" :key="requirement.name" class="shot-item">
                  <div class="shot-heading"><div class="check" :class="{ checked: (photos[photoKey(task.feishu_record_id, requirement.name)] || []).length }">{{ (photos[photoKey(task.feishu_record_id, requirement.name)] || []).length ? '✓' : '' }}</div><div><b>{{ requirement.name }} <em v-if="requirement.mandatory">*</em></b><p>请确保画面清晰、可识别，并覆盖对应质检需求。</p></div></div>
                  <div class="photo-row"><div v-for="(photo, photoIndex) in photos[photoKey(task.feishu_record_id, requirement.name)] || []" :key="photo.name + photoIndex" class="photo" :class="photo.tone"><img :src="photo.url" :alt="photo.name"><button v-if="!uploadedTaskIds.has(task.feishu_record_id) || editingTaskIds.has(task.feishu_record_id)" class="remove-photo" aria-label="删除照片" @click="removePhoto(task.feishu_record_id, requirement.name, photoIndex)">×</button><span>{{ photo.name }}</span></div><button v-if="!uploadedTaskIds.has(task.feishu_record_id) || editingTaskIds.has(task.feishu_record_id)" class="add-photo" @click="addPhoto(task.feishu_record_id, requirement.name)"><i>+</i><span>拍照</span></button></div>
                </div>
              </div>
            </div>
          </div>
          <div class="capture-spacer"/><div v-if="currentTask && (!uploadedTaskIds.has(currentTask.feishu_record_id) || editingTaskIds.has(currentTask.feishu_record_id))" class="bottom-action"><small v-if="isTaskComplete && !isSubmitting">草稿仅保存在本机，确认后才上传</small><button :disabled="!isTaskComplete || isSubmitting" @click="submitPhotos(currentTask.feishu_record_id)">{{ isSubmitting ? '正在上传…' : isTaskComplete ? (editingTaskIds.has(currentTask.feishu_record_id) ? '编辑并上传' : '完成并上传') : '请先完成必拍项' }}</button></div>
          <div v-if="submitStatus !== 'idle'" class="upload-overlay"><div class="upload-dialog"><div v-if="submitStatus === 'uploading'" class="spinner"/><b>{{ submitStatus === 'uploading' ? '正在上传图片…' : submitStatus === 'success' ? '上传成功' : '上传失败' }}</b><p>{{ submitStatus === 'uploading' ? '请勿关闭当前页面' : submitStatus === 'success' ? '当前规格任务已完成' : submitError }}</p><button v-if="submitStatus === 'error'" @click="submitStatus = 'idle'">知道了</button></div></div>
        </section>

        <section v-else class="screen gallery-screen">
          <header class="topbar centered-title"><span class="brand-mark">QC</span><strong>图片检索</strong><span class="header-space"/></header>
          <div class="tabs gallery-tabs"><button :class="{ active: galleryScope === 'mine' }" @click="selectGalleryScope('mine')">我拍摄的</button><button :class="{ active: galleryScope === 'shared' }" @click="selectGalleryScope('shared')">与我共享</button></div>
          <div class="gallery-search"><span aria-hidden="true">⌕</span><input v-model="gallerySearch" type="search" placeholder="搜索合同、产品、规格、部位…" maxlength="200" @input="scheduleGallerySearch" @keyup.enter="loadGallery"><button v-if="gallerySearch" aria-label="清除搜索" @click="clearGallerySearch">×</button></div>
          <div class="gallery-filter-shell">
            <div class="gallery-filters">
              <button class="filter-select" :class="{ selected: galleryProduct, open: galleryFilterOpen === 'product' }" @click="toggleGalleryFilter('product')"><span>产品</span>{{ galleryProduct || '全部产品' }} <i/></button>
              <button class="filter-select" :class="{ selected: galleryPart, open: galleryFilterOpen === 'part' }" @click="toggleGalleryFilter('part')"><span>部位</span>{{ galleryPartLabel }} <i/></button>
              <button class="filter-select date-chip" :class="{ selected: galleryFrom || galleryTo, open: galleryFilterOpen === 'date' }" @click="toggleGalleryFilter('date')"><span>时间</span>{{ galleryDateLabel }} <i/></button>
            </div>
            <div v-if="galleryFilterOpen === 'product'" class="filter-panel option-panel">
              <button :class="{ selected: !galleryProduct }" @click="selectProduct('')">全部产品</button><button v-for="product in productOptions" :key="product" :class="{ selected: galleryProduct === product }" @click="selectProduct(product)">{{ product }}</button>
            </div>
            <div v-if="galleryFilterOpen === 'part'" class="filter-panel option-panel">
              <button :class="{ selected: !galleryPart }" @click="selectPart('')">全部部位</button><button v-for="part in partOptions" :key="part.value" :class="{ selected: galleryPart === part.value }" @click="selectPart(part.value)">{{ part.label }}</button>
            </div>
            <div v-if="galleryFilterOpen === 'date'" class="filter-panel calendar-panel">
              <div class="date-presets"><button @click="setDatePreset('today')">今天</button><button @click="setDatePreset('week')">近 7 天</button><button @click="setDatePreset('month')">本月</button></div>
              <div class="calendar-head"><button aria-label="上个月" @click="moveCalendar(-1)">‹</button><b>{{ calendarTitle }}</b><button aria-label="下个月" @click="moveCalendar(1)">›</button></div>
              <div class="calendar-week"><span v-for="weekday in ['一','二','三','四','五','六','日']" :key="weekday">{{ weekday }}</span></div>
              <div class="calendar-grid"><button v-for="(day, index) in calendarDays" :key="day ? localDateValue(day) : `blank-${index}`" :disabled="!day" :class="calendarDayClass(day)" @click="selectCalendarDay(day)">{{ day?.getDate() }}</button></div>
              <p class="date-selection">{{ galleryFrom ? (galleryTo ? `${galleryFrom} 至 ${galleryTo}` : `${galleryFrom} 起，请选择结束日期`) : '请选择开始日期' }}</p>
              <div class="calendar-actions"><button @click="clearDateFilter">清除</button><button class="primary" :disabled="!galleryFrom" @click="applyDateFilter">确定</button></div>
            </div>
          </div>
          <div class="result-head"><b>{{ galleryPhotos.length }} 张照片</b><div class="gallery-actions"><button class="sort-button" :title="gallerySort === 'desc' ? '当前：最近拍摄在前' : '当前：最早拍摄在前'" @click="gallerySort = gallerySort === 'desc' ? 'asc' : 'desc'; loadGallery()">{{ gallerySort === 'desc' ? '↓' : '↑' }} 时间</button><button :class="{ active: galleryView === 'grid' }" title="卡片显示" @click="galleryView = 'grid'">▦</button><button :class="{ active: galleryView === 'list' }" title="记录显示" @click="galleryView = 'list'">☷</button></div></div>
          <p v-if="galleryError" class="camera-error">{{ galleryError }}</p><p v-else-if="galleryLoading" class="empty">正在加载图片…</p><p v-else-if="!galleryPhotos.length" class="empty">没有符合当前筛选条件的已上传图片</p>
          <div v-else class="gallery" :class="{ grid: galleryView === 'grid' }"><button v-for="photo in galleryPhotos" :key="photo.id" class="gallery-item" @click="openGalleryPhoto(photo)"><img class="thumb" :src="galleryPhotoUrl(photo, 'preview')" :alt="`${photo.contract_no} ${photo.inspection_item}`"><div class="file-info"><b>{{ photo.contract_no }}</b><span>{{ photo.product_type }}<template v-if="photo.specification"> · {{ photo.specification }}</template></span><small>{{ photo.inspection_item }} · {{ galleryDate(photo.captured_at) }}</small><small v-if="galleryScope === 'shared' && photo.photographer_name">拍摄人：{{ photo.photographer_name }}</small></div><i class="item-arrow">›</i></button></div>
        </section>
        <div v-if="selectedGalleryPhoto" class="photo-viewer" @click.self="closeGalleryPhoto">
          <header><button aria-label="关闭" @click="closeGalleryPhoto">‹</button><div><b>{{ selectedGalleryPhoto.contract_no }}</b><small>{{ selectedGalleryPhoto.product_type }} · {{ selectedGalleryPhoto.inspection_item }}</small></div><a :href="galleryPhotoUrl(selectedGalleryPhoto, 'download')" target="_blank" rel="noopener">下载</a></header>
          <div class="photo-stage" :class="{ dragging: photoDragging }" @contextmenu.prevent @wheel.prevent="onPhotoWheel" @pointerdown="startPhotoGesture" @pointermove="movePhotoGesture" @pointerup="stopPhotoGesture" @pointercancel="stopPhotoGesture">
            <img class="viewer-preview" :src="galleryPhotoUrl(selectedGalleryPhoto, 'preview')" alt="" :style="{ transform: photoTransform }"><img ref="viewerImage" class="viewer-full" :class="{ loaded: fullPhotoLoaded }" :src="galleryPhotoUrl(selectedGalleryPhoto, 'full')" :alt="`${selectedGalleryPhoto.contract_no} 高清照片`" :style="{ transform: photoTransform }" @load="fullPhotoLoaded = true">
            <span v-if="!fullPhotoLoaded" class="hd-loading">正在加载高清图…</span>
            <span v-else-if="photoScale === 1" class="gesture-hint">双指捏合缩放 · 放大后单指拖动</span>
            <span v-else class="zoom-level">{{ Math.round(photoScale * 100) }}%</span>
          </div>
        </div>
        <nav class="nav"><button :class="{ active: page === 'home' }" @click="page = 'home'"><i>⌂</i><span>首页</span></button><button :class="{ active: page === 'capture' }" @click="dashboard?.orders[0] && openTask(dashboard.orders[0].task_ids[0])"><i>◉</i><span>拍照任务</span></button><button :class="{ active: page === 'gallery' }" @click="openGallery"><i>▣</i><span>图片检索</span></button></nav>
      </template>
    </div>
  </main>
</template>

<style>
*{box-sizing:border-box}body{margin:0;background:#e9edf3;color:#1f2329;font-family:Inter,"PingFang SC","Microsoft YaHei",sans-serif}button{font:inherit;color:inherit;cursor:pointer;border:0;background:none}.stage{min-height:100vh;display:grid;place-items:center;padding:24px}.phone{width:min(100%,430px);height:min(880px,calc(100vh - 48px));position:relative;overflow:hidden;background:#f5f7fa;border:8px solid #1e252e;border-radius:34px;box-shadow:0 24px 70px #63708466}.screen{height:100%;overflow-y:auto;padding:18px 16px 90px}.capture-screen{padding-bottom:190px}.topbar{position:sticky;top:-18px;z-index:10;height:60px;padding:18px 0 0;display:flex;align-items:center;justify-content:space-between;background:#f5f7fa}.centered-title{display:grid;grid-template-columns:31px 1fr 31px}.topbar strong{font-size:18px}.centered-title strong{text-align:center}.brand-mark{width:31px;height:31px;display:grid;place-items:center;background:#3370ff;color:#fff;border-radius:9px;font-size:12px;font-weight:800}.greeting{display:flex;align-items:center;gap:11px;margin:21px 4px 25px}.avatar{width:43px;height:43px;border-radius:14px;color:#fff;font-weight:bold;display:grid;place-items:center;background:linear-gradient(135deg,#6c8b6b,#243a43)}h1,h2,h3,p{margin:0}h1{font-size:20px;margin:3px 0}h2{font-size:17px}h3{font-size:17px;margin:8px 0 5px}.eyebrow,.muted{color:#8a919f;font-size:12px}.todo-card,.contract-card,.order-card{background:#fff;border-radius:16px;box-shadow:0 5px 18px #17233c0b}.todo-card{padding:17px}.card-heading,.list-title,.contract-top,footer,.result-head{display:flex;align-items:center;justify-content:space-between}.card-heading{font-weight:700;font-size:17px}.card-heading button,footer b{color:#3370ff;font-size:12px}.todo-row{display:flex;align-items:center;gap:10px;padding-top:18px}.todo-icon{color:#2fa56b;background:#e6f7ef;font-weight:800;width:39px;height:39px;border-radius:12px;display:grid;place-items:center;font-size:20px}.todo-row b{font-size:18px;display:block}.todo-row small{color:#8a919f;font-size:11px}.todo-sep{height:30px;width:1px;background:#e6e8eb;margin:0 8px}.go{margin-left:auto;color:#a0a7b1;font-size:25px}.list-title{margin:26px 3px 12px}.contract-card{margin-bottom:13px;padding:15px 16px}.status{background:#fff3df;color:#c27600;padding:3px 7px;border-radius:5px;font-size:11px}.status.done{background:#e3f5ea;color:#168756}.due{color:#7e8793;font-size:12px}.tag-row,.filter-chips{display:flex;gap:6px;margin:12px 0;flex-wrap:wrap}.tag-row span,.filter-chips span{padding:4px 8px;border-radius:5px;background:#f0f4fa;color:#637084;font-size:11px}.progress{height:4px;background:#edf0f3;border-radius:4px;overflow:hidden}.progress i{display:block;height:100%;background:#3370ff}.contract-card footer{margin-top:11px;font-size:11px;color:#848d99}.back{font-size:36px;line-height:20px;color:#4a5564}.order-card{margin-top:18px;padding:16px;display:flex;justify-content:space-between;align-items:center;background:linear-gradient(125deg,#fff,#eef5ff);border:1px solid #e2ebfb}.order-card h2{margin:4px 0;font-size:19px}.order-card p{font-size:12px;color:#737c88}.order-badge{text-align:right;color:#3370ff}.order-badge b,.order-badge small{display:block}.order-badge b{font-size:12px}.order-badge small{font-size:11px;color:#7c8795;margin-top:3px}.hint{font-size:12px;color:#757f8c;margin:14px 4px}.hint em,.shot-item em{font-style:normal;color:#ef6457}.capture-group{background:#fff;border-radius:13px;margin:10px 0;overflow:hidden;border:1px solid #edf0f4}.group-head{width:100%;padding:14px;display:flex;align-items:center;text-align:left;gap:9px}.component-icon{color:#3370ff;background:#edf3ff;border-radius:6px;padding:3px 5px}.group-head small{color:#9299a4;margin-left:auto;font-size:11px}.chev{width:8px;height:8px;border-right:1.5px solid #7b8491;border-bottom:1.5px solid #7b8491;transform:rotate(45deg) translateY(-2px)}.group-content{padding:0 14px 14px;border-top:1px solid #f0f2f5}.shot-item{padding:13px 0;border-bottom:1px solid #f0f2f5}.shot-item:last-child{border:0}.shot-heading{display:flex;gap:9px}.check{width:17px;height:17px;border:1.5px solid #c6ccd6;border-radius:50%;font-size:11px;display:grid;place-items:center;color:#fff;flex:none;margin-top:2px}.check.checked{background:#3370ff;border-color:#3370ff}.shot-item b{font-size:13px}.shot-item p{font-size:11px;color:#8b94a1;margin-top:4px}.photo-row{display:flex;flex-wrap:wrap;gap:8px;margin:9px 0 0 26px}.photo,.add-photo{width:74px;height:74px;border-radius:8px;overflow:hidden}.photo{position:relative;background:#73828d}.photo span{position:absolute;bottom:4px;left:4px;right:4px;color:#fff;font-size:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.remove-photo{position:absolute;right:3px;top:3px;z-index:1;width:19px;height:19px;border-radius:50%;background:#202b36cc;color:#fff;font-size:17px;line-height:17px}.add-photo{border:1px dashed #94b6fb;background:#f6f9ff;color:#3370ff;display:flex;flex-direction:column;align-items:center;justify-content:center}.add-photo i{font-size:25px;font-style:normal;line-height:22px}.add-photo span{font-size:10px;margin-top:3px}.steel-a{background:linear-gradient(135deg,#aab7bc,#3d4d55 42%,#bbc6c9 44%,#526770)}.steel-b{background:linear-gradient(35deg,#304852,#b08f6c 48%,#253941 52%)}.steel-c{background:linear-gradient(135deg,#554c47,#bda883 45%,#293f48 46%)}.capture-spacer{display:none}.bottom-action{position:absolute;bottom:68px;left:0;right:0;padding:10px 16px;background:linear-gradient(transparent,#f5f7fa 30%)}.bottom-action button{width:100%;background:#3370ff;color:#fff;font-weight:600;padding:13px;border-radius:10px;box-shadow:0 5px 11px #3370ff44}.bottom-action button:disabled{background:#aab7cf;box-shadow:none}.tabs{display:flex;gap:23px;border-bottom:1px solid #e6e9ee;margin-top:13px}.tabs button{padding:10px 4px;color:#737d89}.tabs .active{color:#3370ff;border-bottom:2px solid #3370ff;font-weight:600}.search-box{height:39px;background:#fff;border:1px solid #e6eaf0;border-radius:9px;margin:15px 0 9px;display:flex;align-items:center;padding:0 11px;gap:8px;color:#8d96a2}.placeholder{font-size:12px;flex:1}.search-box button{font-size:12px;color:#3370ff;border-left:1px solid #e8ebef;padding-left:9px}.result-head{margin:19px 0 10px}.result-head b{font-size:14px}.result-head small{font-size:11px;color:#969eaa}.gallery{display:flex;flex-direction:column;gap:8px}.gallery-item{display:flex;align-items:center;gap:10px;background:#fff;border-radius:10px;padding:8px;box-shadow:0 2px 8px #17233c08}.thumb{width:62px;height:52px;border-radius:6px;position:relative;overflow:hidden}.thumb span{position:absolute;left:5px;top:4px;color:#fff;font-weight:bold;font-size:9px}.file-info{display:flex;flex-direction:column;gap:5px}.file-info b{font-size:13px}.file-info small{font-size:11px;color:#8a939f}.more{margin-left:auto;color:#9aa2ad;font-weight:bold}.nav{height:68px;position:absolute;bottom:0;left:0;right:0;background:#fff;border-top:1px solid #e5e8ec;display:flex;justify-content:space-around;padding-top:8px}.nav button{color:#89929e;display:flex;flex-direction:column;align-items:center;gap:3px;font-size:11px;min-width:80px}.nav i{font-style:normal;font-size:22px;line-height:24px}.nav .active{color:#3370ff;font-weight:600}.empty,.loading{color:#8a919f;text-align:center;padding:40px 16px}.loading{display:grid;place-items:center;height:100%}@media(max-width:600px){.stage{padding:0}.phone{width:100%;height:100dvh;border:0;border-radius:0;box-shadow:none}.capture-screen{padding-bottom:calc(190px + env(safe-area-inset-bottom))}.nav{height:calc(68px + env(safe-area-inset-bottom));padding-bottom:env(safe-area-inset-bottom)}.bottom-action{bottom:calc(68px + env(safe-area-inset-bottom))}}
.photo,.add-photo{width:92px;height:92px;border-radius:10px}.photo{box-shadow:0 2px 7px #1e293b22}.photo::after{content:"";position:absolute;inset:48% 0 0;background:linear-gradient(transparent,#111b)}.photo img{width:100%;height:100%;display:block;object-fit:cover}.photo span{z-index:1;bottom:7px;left:7px;right:7px;font-size:10px;line-height:14px;text-shadow:0 1px 2px #000}.remove-photo{z-index:2;right:6px;top:6px;width:26px;height:26px;padding:0;border-radius:50%;background:#17212be6;border:1px solid #ffffff80;color:#fff;font-size:22px;line-height:22px;font-weight:300;display:grid;place-items:center;box-shadow:0 2px 5px #0004}.remove-photo:active{transform:scale(.9);background:#d84b45}.add-photo{border-width:1.5px}.add-photo i{font-size:28px}.add-photo span{font-size:11px;margin-top:7px}.camera-error{margin:0 4px 10px;padding:9px 11px;border-radius:8px;background:#fff1f0;color:#c53a32;font-size:12px}
.capture-progress{margin:14px 3px 8px}.capture-progress>div:first-child{display:flex;justify-content:space-between;margin-bottom:7px;font-size:12px}.capture-progress span{color:#7d8794}.task-tabs{display:flex;overflow-x:auto;gap:22px;border-bottom:1px solid #e6e9ee;white-space:nowrap;scroll-snap-type:x mandatory}.task-tabs button{position:relative;flex:none;padding:10px 2px;color:#737d89;font-size:13px;scroll-snap-align:center}.task-tabs button.active{color:#3370ff;border-bottom:2px solid #3370ff;font-weight:600}.task-tabs button.done{color:#1d9b64}.task-tabs button i{position:absolute;width:6px;height:6px;border-radius:50%;background:#ef6457;top:7px;right:-8px}.task-swipe{touch-action:pan-y}.bottom-action small{display:block;text-align:center;color:#7f8995;font-size:11px;padding:2px 0 7px}.upload-overlay{position:absolute;z-index:30;inset:0;display:grid;place-items:center;background:#17233c66;backdrop-filter:blur(2px)}.upload-dialog{width:230px;padding:25px 20px;border-radius:16px;text-align:center;background:#fff;box-shadow:0 15px 36px #17233c44}.upload-dialog b{display:block;font-size:17px}.upload-dialog p{margin-top:9px;color:#747e8a;font-size:12px;line-height:18px}.upload-dialog button{margin-top:14px;padding:8px 26px;border-radius:8px;background:#3370ff;color:#fff}.spinner{width:30px;height:30px;margin:0 auto 15px;border:3px solid #dce7ff;border-top-color:#3370ff;border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.contract-card.completed{background:#f0f2f4;box-shadow:none;color:#747c86}.contract-card.completed .tag-row span{background:#e2e5e8;color:#7e8690}.contract-card.completed .progress{background:#d8dde2}.contract-card.completed .progress i{background:#98a1ab}.contract-card.completed footer b{color:#68717b}.status.done{background:#e1e4e7;color:#68717b}.edit-task{margin-left:auto;color:#3370ff;font-size:12px;padding:5px 8px;background:#edf3ff;border-radius:6px}.group-head .edit-task+small{margin-left:0}
.bottom-action{z-index:20}.nav{z-index:21}.photo,.remove-photo,.photo span{z-index:1}.photo span{z-index:2}.remove-photo{z-index:3}
.gallery-filters{display:flex;gap:7px;margin:15px 0 10px;overflow-x:auto;padding-bottom:2px}.filter-select{flex:none;display:flex;align-items:center;gap:4px;padding:0 8px;height:32px;border:1px solid #dfe5ec;border-radius:8px;background:#fff;color:#596573;font-size:11px}.filter-select span{color:#8a94a1}.filter-select select{max-width:92px;border:0;background:transparent;color:#334155;font:inherit;outline:0}.date-chip.selected{border-color:#8eb1ff;color:#2863db}.date-filter{display:flex;align-items:end;gap:8px;padding:10px;margin-bottom:9px;border-radius:9px;background:#fff;border:1px solid #e5eaf0}.date-filter label{display:flex;flex-direction:column;gap:4px;font-size:10px;color:#7d8794}.date-filter input{width:118px;border:1px solid #dfe5ec;border-radius:5px;padding:4px;font:inherit;font-size:11px}.date-filter button{font-size:11px;color:#3370ff;padding:5px}.gallery-actions{display:flex;align-items:center;gap:5px}.gallery-actions button{height:25px;min-width:25px;border:1px solid #e0e5eb;border-radius:5px;color:#7b8592;font-size:13px}.gallery-actions .sort-button{padding:0 7px;font-size:11px}.gallery-actions button.active{background:#edf3ff;border-color:#9bbcfb;color:#3370ff}.gallery.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.gallery.grid .gallery-item{display:block;padding:6px}.gallery.grid .thumb{width:100%;height:120px;display:block}.gallery.grid .file-info{padding:7px 2px 2px}.gallery.grid .file-info b{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.thumb{object-fit:cover;background:#dde4e9}.gallery-item .thumb{flex:none}
.gallery-screen{overflow-x:hidden}.gallery-tabs{margin-top:8px}.gallery-tabs button{font-size:14px}.gallery-search{height:42px;margin:14px 0 10px;display:flex;align-items:center;gap:8px;padding:0 12px;border:1px solid #e1e6ed;border-radius:10px;background:#fff;box-shadow:0 2px 8px #17233c08;color:#87909c}.gallery-search:focus-within{border-color:#8fb2ff;box-shadow:0 0 0 3px #3370ff14}.gallery-search>span{font-size:22px;line-height:1;transform:rotate(-20deg)}.gallery-search input{min-width:0;flex:1;border:0;outline:0;background:transparent;color:#1f2329;font:inherit;font-size:13px}.gallery-search input::placeholder{color:#a3aab4}.gallery-search button{width:24px;height:24px;border-radius:50%;background:#eef1f5;color:#76808d;font-size:18px;line-height:20px}.gallery-filter-shell{position:relative}.gallery-filters{margin:0 0 10px;padding:0 0 2px;overflow-x:auto}.filter-select{height:34px;padding:0 10px;gap:5px;font-size:12px;transition:.15s}.filter-select>span{color:#8a94a1}.filter-select>i{width:6px;height:6px;margin:-3px 1px 0 2px;border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:rotate(45deg);transition:.15s}.filter-select.open>i{margin-top:3px;transform:rotate(225deg)}.filter-select.selected,.filter-select.open{border-color:#8eb1ff;background:#f4f7ff;color:#2863db}.filter-panel{position:relative;z-index:9;margin:-3px 0 11px;padding:10px;border:1px solid #e2e7ee;border-radius:11px;background:#fff;box-shadow:0 10px 28px #17233c1a;animation:filter-in .14s ease-out}@keyframes filter-in{from{opacity:0;transform:translateY(-5px)}to{opacity:1;transform:none}}.option-panel{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.option-panel button{min-height:34px;padding:6px;border-radius:7px;background:#f6f7f9;color:#4c5663;font-size:12px}.option-panel button.selected{background:#eaf1ff;color:#2863db;font-weight:600}.calendar-panel{padding:12px}.date-presets{display:flex;gap:7px;margin-bottom:10px}.date-presets button{padding:6px 11px;border-radius:7px;background:#f2f5f9;color:#53606e;font-size:12px}.calendar-head{display:grid;grid-template-columns:34px 1fr 34px;align-items:center;margin-bottom:7px}.calendar-head b{text-align:center;font-size:14px}.calendar-head button{height:30px;border-radius:7px;color:#596574;font-size:24px}.calendar-head button:active{background:#eef3fc}.calendar-week,.calendar-grid{display:grid;grid-template-columns:repeat(7,1fr);text-align:center}.calendar-week{margin-bottom:3px;color:#9aa2ad;font-size:10px}.calendar-grid{row-gap:3px}.calendar-grid button{position:relative;height:34px;border-radius:8px;font-size:12px;z-index:1}.calendar-grid button.ranged{border-radius:0;background:#edf3ff;color:#2863db}.calendar-grid button.selected{background:#3370ff;color:#fff;font-weight:600}.calendar-grid button.today:not(.selected)::after{content:"";position:absolute;bottom:3px;left:50%;width:3px;height:3px;border-radius:50%;background:#3370ff;transform:translateX(-50%)}.date-selection{min-height:18px;margin:7px 2px;color:#77818e;font-size:11px;text-align:center}.calendar-actions{display:flex;justify-content:flex-end;gap:8px;padding-top:9px;border-top:1px solid #edf0f3}.calendar-actions button{min-width:58px;padding:7px 12px;border-radius:7px;color:#687382;font-size:12px}.calendar-actions .primary{background:#3370ff;color:#fff}.calendar-actions .primary:disabled{background:#b7c7e6}.result-head{margin-top:15px}.gallery-item{width:100%;text-align:left}.gallery-item:active{transform:scale(.99);background:#f9fbff}.gallery-item .thumb{width:78px;height:66px}.file-info{min-width:0;flex:1;gap:4px}.file-info b{font-size:15px;line-height:19px;color:#262b33;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.file-info span{font-size:13px;line-height:17px;color:#505b68;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.file-info small{font-size:12px;line-height:16px;color:#7d8794;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.item-arrow{flex:none;color:#a0a8b2;font-size:22px;font-style:normal}.gallery.grid .gallery-item{position:relative}.gallery.grid .thumb{height:126px}.gallery.grid .file-info{gap:5px}.gallery.grid .file-info b{font-size:14px}.gallery.grid .file-info span{font-size:12px}.gallery.grid .file-info small{font-size:11px}.gallery.grid .item-arrow{display:none}.photo-viewer{position:absolute;z-index:50;inset:0;display:flex;flex-direction:column;background:#111820;color:#fff}.photo-viewer header{height:66px;display:grid;grid-template-columns:44px 1fr 54px;align-items:center;gap:5px;padding:8px 10px;background:#17212b}.photo-viewer header button{color:#fff;font-size:34px;line-height:1}.photo-viewer header div{min-width:0;display:flex;flex-direction:column;gap:2px;text-align:center}.photo-viewer header b{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.photo-viewer header small{color:#b9c1ca;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.photo-viewer header a{padding:7px 9px;border-radius:7px;background:#3370ff;color:#fff;text-align:center;text-decoration:none;font-size:12px}.photo-stage{position:relative;min-height:0;flex:1;overflow:hidden;display:grid;place-items:center;touch-action:none;cursor:grab;background:#0d1319}.photo-stage.dragging{cursor:grabbing}.photo-stage img{position:absolute;max-width:100%;max-height:100%;user-select:none;-webkit-user-drag:none}.viewer-preview{opacity:.66;filter:blur(1px)}.viewer-full{opacity:0;transform-origin:center;transition:opacity .18s ease,transform .12s ease-out}.viewer-full.loaded{opacity:1}.photo-stage.dragging .viewer-full{transition:opacity .18s ease}.hd-loading{position:absolute;bottom:18px;padding:6px 10px;border-radius:14px;background:#101820b8;color:#d7dce2;font-size:11px}.zoom-controls{height:64px;display:flex;align-items:center;justify-content:center;gap:9px;background:#17212b}.zoom-controls button{min-width:44px;height:36px;padding:0 10px;border-radius:9px;background:#283542;color:#fff;font-size:18px}.zoom-controls button:nth-child(2){min-width:66px;font-size:12px}.zoom-controls button:disabled{opacity:.35}
.photo-stage img{transform-origin:center;will-change:transform}.viewer-preview{transition:transform .12s ease-out}.photo-stage.dragging img{transition:none}.gesture-hint{position:absolute;bottom:18px;padding:7px 11px;border-radius:16px;background:#101820b8;color:#e1e5ea;font-size:11px;pointer-events:none}.zoom-level{position:absolute;right:12px;top:12px;min-width:48px;padding:5px 8px;border-radius:14px;background:#101820b8;color:#fff;text-align:center;font-size:11px;pointer-events:none}.zoom-controls{display:none}
.todo-card.interactive{cursor:pointer;transition:transform .12s ease,box-shadow .12s ease}.todo-card.interactive:active{transform:scale(.99);box-shadow:0 2px 8px #17233c12}.todo-card:focus{outline:none}.todo-card:focus-visible{box-shadow:0 0 0 3px #3370ff26,0 5px 18px #17233c0b}.capture-topbar{display:grid;grid-template-columns:40px 1fr 40px}.capture-topbar strong{text-align:center}.capture-topbar .back{justify-self:start}.screen{padding-bottom:76px}.capture-screen{padding-bottom:190px}.bottom-action{bottom:56px}.nav{height:56px;padding-top:5px}.nav button{min-width:68px;gap:1px;font-size:10px;outline:none;border-radius:8px}.nav button:focus{outline:none}.nav button:focus-visible{background:#edf3ff;box-shadow:inset 0 0 0 2px #dce8ff}.nav i{font-size:18px;line-height:20px}@media(max-width:600px){.capture-screen{padding-bottom:calc(190px + env(safe-area-inset-bottom))}.nav{height:calc(56px + env(safe-area-inset-bottom));padding-bottom:env(safe-area-inset-bottom)}.bottom-action{bottom:calc(56px + env(safe-area-inset-bottom))}}
.nav,.nav button{-webkit-tap-highlight-color:transparent}.nav button:active,.nav button:focus,.nav button:focus-visible{outline:none!important;background:transparent!important;box-shadow:none!important}
</style>
