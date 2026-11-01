<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import DownloadOptionsDialog from './DownloadOptionsDialog.vue'
import { rangeIdsInclusive } from './selection'

type GalleryPhoto = { id: string; contract_no: string; product_type: string; specification: string; inspection_item: string; inspection_note: string; captured_at: string; photographer_name: string; has_unwatermarked: boolean }
type GalleryResponse = { photos: GalleryPhoto[]; count: number; page: number; page_size: number; total_pages: number }
type CurrentUser = { id: string; name: string; avatar_url: string | null }
type Scope = 'mine' | 'shared'

const productOptions = ['管件', '法兰', '管子', '焊管', '无缝管', '板材', '棒材', '盘管', '其它']
const partOptions = [
  { value: 'material', label: '材质光谱' }, { value: 'surface', label: '内外表面' },
  { value: 'dimension', label: '尺寸' }, { value: 'marking', label: '喷码' },
  { value: 'port', label: '端口坡口' }, { value: 'weld', label: '焊道' },
]
const scope = ref<Scope>('mine')
const keyword = ref('')
const product = ref('')
const part = ref('')
const from = ref('')
const to = ref('')
const sort = ref<'asc' | 'desc'>('desc')
const view = ref<'grid' | 'list'>('grid')
const photos = ref<GalleryPhoto[]>([])
const totalPhotos = ref(0)
const currentPage = ref(1)
const totalPages = ref(0)
const pageSize = 50
const loading = ref(true)
const error = ref('')
const downloadBusy = ref(false)
const downloadError = ref('')
const selected = ref<GalleryPhoto | null>(null)
const fullLoaded = ref(false)
const rotation = ref(0)
const selectedPhotoIds = ref<Set<string>>(new Set())
const downloadDialogOpen = ref(false)
const downloadWithWatermark = ref(true)
const pendingDownloadIds = ref<string[]>([])
const currentUser = ref<CurrentUser | null>(null)
let searchTimer = 0
let swipeStart: { x: number; y: number } | null = null
let selectionAnchorId: string | null = null
const DOWNLOAD_TIMEOUT_MS = 300_000

const partLabel = computed(() => partOptions.find(item => item.value === part.value)?.label || '全部部位')
const activeFilterCount = computed(() => Number(Boolean(product.value)) + Number(Boolean(part.value)) + Number(Boolean(from.value || to.value)))
const dateSummary = computed(() => from.value || to.value ? `${from.value || '最早'} 至 ${to.value || '今天'}` : '全部时间')
const profileInitial = computed(() => currentUser.value?.name?.trim().slice(0, 1) || '用')
const selectedIndex = computed(() => selected.value ? photos.value.findIndex(photo => photo.id === selected.value?.id) : -1)
const hasPrevious = computed(() => selectedIndex.value > 0)
const hasNext = computed(() => selectedIndex.value >= 0 && selectedIndex.value < photos.value.length - 1)
const selectedPhotos = computed(() => photos.value.filter(photo => selectedPhotoIds.value.has(photo.id)))
const unavailableOriginalCount = computed(() => selectedPhotos.value.filter(photo => !photo.has_unwatermarked).length)
const allSelected = computed(() => photos.value.length > 0 && selectedPhotos.value.length === photos.value.length)
const pageNumbers = computed(() => {
  const count = Math.min(5, totalPages.value)
  const start = Math.max(1, Math.min(currentPage.value - 2, totalPages.value - count + 1))
  return Array.from({ length: count }, (_, index) => start + index)
})
const rotationTransform = computed(() => `rotate(${rotation.value}deg)`)

async function loadPhotos(resetPage = true) {
  loading.value = true
  error.value = ''
  downloadError.value = ''
  try {
    if (resetPage) currentPage.value = 1
    const query = new URLSearchParams({
      scope: scope.value,
      sort: sort.value,
      page: String(currentPage.value),
      page_size: String(pageSize),
    })
    if (keyword.value.trim()) query.set('q', keyword.value.trim())
    if (product.value) query.set('product_type', product.value)
    if (part.value) query.set('inspection_category', part.value)
    if (from.value) query.set('captured_from', from.value)
    if (to.value) query.set('captured_to', to.value)
    const response = await fetch(`/api/v1/photos?${query}`, { credentials: 'include' })
    if (response.status === 401) {
      const returnPath = `${window.location.pathname}${window.location.search}${window.location.hash}`
      window.location.replace(`/api/v1/auth/feishu/login?next=${encodeURIComponent(returnPath)}`)
      return
    }
    if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || '图片加载失败')
    const data = await response.json() as GalleryResponse
    photos.value = data.photos
    totalPhotos.value = data.count
    totalPages.value = data.total_pages
    if (resetPage) selectedPhotoIds.value = new Set()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '图片加载失败'
  } finally { loading.value = false }
}

async function loadCurrentUser() {
  try {
    const response = await fetch('/api/v1/auth/me', { credentials: 'include' })
    if (response.ok) {
      const user = await response.json() as Partial<CurrentUser>
      if (user.name) { currentUser.value = { id: user.id || '', name: user.name, avatar_url: user.avatar_url || null }; return }
    }
    // Compatibility fallback for deployments that have not yet updated /auth/me.
    const dashboardResponse = await fetch('/api/v1/dashboard', { credentials: 'include' })
    if (dashboardResponse.ok) {
      const dashboard = await dashboardResponse.json() as { user?: { name?: string } }
      if (dashboard.user?.name) currentUser.value = { id: '', name: dashboard.user.name, avatar_url: null }
    }
  } catch {
    // The gallery remains usable when a non-essential profile request fails.
  }
}

function scheduleSearch() { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(loadPhotos, 320) }
function setScope(next: Scope) { if (scope.value !== next) { scope.value = next; selected.value = null; loadPhotos() } }
function resetFilters() { product.value = ''; part.value = ''; from.value = ''; to.value = ''; loadPhotos() }
function datePreset(days: number | 'month') {
  const now = new Date()
  const start = new Date(now)
  if (days === 'month') start.setDate(1); else start.setDate(now.getDate() - days)
  const local = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
  from.value = local(start); to.value = local(now); loadPhotos()
}
function photoUrl(photo: GalleryPhoto, kind: 'preview' | 'full' | 'download') { return `/api/v1/feishu/photos/${photo.id}/${kind}?scope=${scope.value}` }
function formatDate(value: string) { const date = new Date(value); return Number.isNaN(date.valueOf()) ? '未知时间' : date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) }
function openPhoto(photo: GalleryPhoto) { selected.value = photo; fullLoaded.value = false; rotation.value = 0; downloadError.value = '' }
function rotatePhoto() { rotation.value = (rotation.value + 90) % 360 }
function togglePhoto(photoId: string, extendRange = false) {
  const next = new Set(selectedPhotoIds.value)
  if (extendRange && selectionAnchorId) {
    rangeIdsInclusive(photos.value.map(photo => photo.id), selectionAnchorId, photoId).forEach(id => next.add(id))
  } else if (next.has(photoId)) next.delete(photoId)
  else next.add(photoId)
  selectedPhotoIds.value = next
  selectionAnchorId = photoId
}
function toggleCurrentPage() {
  const next = new Set(selectedPhotoIds.value)
  const allSelected = photos.value.every(photo => next.has(photo.id))
  for (const photo of photos.value) {
    if (allSelected) next.delete(photo.id)
    else next.add(photo.id)
  }
  selectedPhotoIds.value = next
  selectionAnchorId = allSelected ? null : photos.value[0]?.id || null
}
function goToPage(page: number) {
  if (page < 1 || page > totalPages.value || page === currentPage.value) return
  currentPage.value = page
  selectedPhotoIds.value = new Set()
  loadPhotos(false)
  document.querySelector('.results')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function navigatePhoto(offset: number) {
  const target = photos.value[selectedIndex.value + offset]
  if (!target) return
  selected.value = target
  fullLoaded.value = false
  rotation.value = 0
  downloadError.value = ''
}
function startSwipe(event: PointerEvent) { swipeStart = { x: event.clientX, y: event.clientY } }
function cancelSwipe() { swipeStart = null }
function endSwipe(event: PointerEvent) {
  if (!swipeStart) return
  const dx = event.clientX - swipeStart.x
  const dy = event.clientY - swipeStart.y
  swipeStart = null
  if (Math.abs(dx) >= 60 && Math.abs(dx) > Math.abs(dy) * 1.25) navigatePhoto(dx < 0 ? 1 : -1)
}
function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000)
}
function responseFilename(response: Response, fallback: string) {
  const match = (response.headers.get('content-disposition') || '').match(/filename="([^"]+)"/i)
  return match?.[1] || fallback
}
async function fetchDownload(input: RequestInfo | URL, init: RequestInit = {}) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), DOWNLOAD_TIMEOUT_MS)
  try {
    return await fetch(input, { ...init, signal: controller.signal })
  } catch (cause) {
    if (controller.signal.aborted) throw new Error('下载超时，请缩小范围后重试')
    throw cause
  } finally {
    window.clearTimeout(timer)
  }
}
function openDownload(ids: string[]) {
  if (!ids.length) return
  pendingDownloadIds.value = ids
  downloadWithWatermark.value = true
  downloadDialogOpen.value = true
}
async function confirmDownload() {
  const ids = pendingDownloadIds.value
  if (!ids.length) return
  downloadDialogOpen.value = false
  downloadBusy.value = true
  downloadError.value = ''
  try {
    let response: Response
    let fallbackName: string
    if (ids.length === 1) {
      const query = new URLSearchParams({ scope: scope.value, watermarked: String(downloadWithWatermark.value) })
      response = await fetchDownload(`/api/v1/feishu/photos/${ids[0]}/download?${query}`, { credentials: 'include' })
      fallbackName = `qc-photo-${ids[0]}.jpg`
    } else {
      response = await fetchDownload('/api/v1/feishu/photos/download-batch', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope: scope.value, photo_ids: ids, watermarked: downloadWithWatermark.value }),
      })
      const timestamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, '')
      fallbackName = `qc-photos-${timestamp}.zip`
    }
    if (response.status === 401) throw new Error('登录已过期，请刷新页面重新登录后再下载')
    if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || '图片下载失败')
    saveBlob(await response.blob(), responseFilename(response, fallbackName))
    selectedPhotoIds.value = new Set()
  } catch (cause) {
    downloadError.value = cause instanceof Error ? cause.message : '图片下载失败，请稍后重试'
  } finally {
    downloadBusy.value = false
  }
}
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    if (downloadDialogOpen.value) downloadDialogOpen.value = false
    else selected.value = null
    return
  }
  if (!selected.value) return
  if (event.key === 'ArrowLeft') { event.preventDefault(); navigatePhoto(-1) }
  else if (event.key === 'ArrowRight') { event.preventDefault(); navigatePhoto(1) }
}
onMounted(() => { window.addEventListener('keydown', onKeydown); loadCurrentUser(); loadPhotos() })
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <main class="desktop-gallery">
    <aside class="sidebar">
      <a class="brand" href="/gallery" aria-label="质检照片库首页"><span>QC</span><b>质检照片库</b></a>
      <nav aria-label="照片范围">
        <button :class="{ active: scope === 'mine' }" @click="setScope('mine')"><i>▣</i>我拍摄的</button>
        <button :class="{ active: scope === 'shared' }" @click="setScope('shared')"><i>◫</i>与我共享</button>
      </nav>
      <p class="side-hint">仅展示您有权限查看的质检照片</p>
    </aside>

    <section class="workspace">
      <header class="workspace-header">
        <div><p class="crumb">质检管理 / 图片检索</p><h1>{{ scope === 'mine' ? '我拍摄的照片' : '与我共享的照片' }}</h1></div>
        <div class="account"><img v-if="currentUser?.avatar_url" :src="currentUser.avatar_url" :alt="`${currentUser.name}的头像`"><span v-else>{{ profileInitial }}</span><b>{{ currentUser?.name || '照片查看' }}</b></div>
      </header>

      <div class="content">
        <section class="query-card" aria-label="图片筛选">
          <div class="search-row">
            <label class="search"><span>⌕</span><input v-model="keyword" type="search" maxlength="200" placeholder="搜索合同编号、产品、规格或拍摄部位" @input="scheduleSearch" @keyup.enter="loadPhotos()"><button v-if="keyword" aria-label="清空搜索" @click="keyword = ''; loadPhotos()">×</button></label>
            <button class="search-submit" @click="loadPhotos()">搜索</button>
          </div>
          <div class="filters">
            <label>产品<select v-model="product" @change="loadPhotos()"><option value="">全部产品</option><option v-for="item in productOptions" :key="item" :value="item">{{ item }}</option></select></label>
            <label>拍摄部位<select v-model="part" @change="loadPhotos()"><option value="">全部部位</option><option v-for="item in partOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
            <label>开始日期<input v-model="from" type="date" :max="to || undefined" @change="loadPhotos()"></label>
            <label>结束日期<input v-model="to" type="date" :min="from || undefined" @change="loadPhotos()"></label>
            <button v-if="activeFilterCount" class="clear-filters" @click="resetFilters">清除筛选（{{ activeFilterCount }}）</button>
          </div>
          <div class="quick-dates"><span>快捷时间：</span><button @click="datePreset(0)">今天</button><button @click="datePreset(6)">近 7 天</button><button @click="datePreset('month')">本月</button><em v-if="from || to">{{ dateSummary }}</em></div>
        </section>

        <section class="results" aria-live="polite">
          <header class="results-head">
            <div><b>{{ loading ? '正在加载…' : `共 ${totalPhotos} 张照片` }}</b><span v-if="!loading">第 {{ currentPage }} / {{ Math.max(totalPages, 1) }} 页 · 每页 {{ pageSize }} 张</span></div>
            <div class="result-tools">
              <button class="selection-button" :disabled="!photos.length" @click="toggleCurrentPage">{{ photos.length && photos.every(photo => selectedPhotoIds.has(photo.id)) ? '取消全选' : '全选本页' }}</button>
              <button class="download-selected" :disabled="!selectedPhotoIds.size" @click="openDownload([...selectedPhotoIds])">下载所选（{{ selectedPhotoIds.size }}）</button>
              <span class="divider"/>
              <button :title="sort === 'desc' ? '当前按最新拍摄时间排序' : '当前按最早拍摄时间排序'" @click="sort = sort === 'desc' ? 'asc' : 'desc'; loadPhotos()">{{ sort === 'desc' ? '↓ 最新优先' : '↑ 最早优先' }}</button><span class="divider"/><button :class="{ selected: view === 'grid' }" title="宫格视图" @click="view = 'grid'">▦</button><button :class="{ selected: view === 'list' }" title="列表视图" @click="view = 'list'">☷</button>
            </div>
          </header>
          <p v-if="downloadError" class="state error">{{ downloadError }}</p>
          <p v-if="error" class="state error">{{ error }}</p>
          <p v-else-if="loading" class="state">正在载入照片…</p>
          <div v-else-if="photos.length" class="photo-grid" :class="view">
            <div v-for="photo in photos" :key="photo.id" class="photo-card" :class="{ 'is-selected': selectedPhotoIds.has(photo.id) }">
              <label class="photo-select" :class="{ checked: selectedPhotoIds.has(photo.id) }" @click.stop>
                <input type="checkbox" :checked="selectedPhotoIds.has(photo.id)" :aria-label="`选择 ${photo.contract_no} 的照片`" @change="togglePhoto(photo.id)">
                <span aria-hidden="true">✓</span>
              </label>
              <button class="photo-open" @click="openPhoto(photo)">
                <img :src="photoUrl(photo, 'preview')" :alt="`${photo.contract_no} ${photo.inspection_item}`">
                <div class="photo-meta"><b>{{ photo.contract_no }}</b><span>{{ photo.product_type }}<template v-if="photo.specification"> · {{ photo.specification }}</template></span><small>{{ photo.inspection_item }} · {{ formatDate(photo.captured_at) }}</small><small v-if="photo.inspection_note">备注：{{ photo.inspection_note }}</small><small v-if="scope === 'shared' && photo.photographer_name">拍摄人：{{ photo.photographer_name }}</small></div>
              </button>
            </div>
          </div>
          <div v-else class="state empty"><strong>未找到符合条件的照片</strong><span>请调整搜索内容或筛选条件后重试</span><button v-if="keyword || activeFilterCount" @click="keyword = ''; resetFilters()">清空搜索与筛选</button></div>
          <nav v-if="totalPages > 1 && !loading" class="pagination" aria-label="照片分页">
            <button :disabled="currentPage === 1" @click="goToPage(currentPage - 1)">‹ 上一页</button>
            <button v-for="page in pageNumbers" :key="page" :class="{ active: page === currentPage }" :aria-current="page === currentPage ? 'page' : undefined" @click="goToPage(page)">{{ page }}</button>
            <button :disabled="currentPage === totalPages" @click="goToPage(currentPage + 1)">下一页 ›</button>
          </nav>
        </section>
      </div>
    </section>

    <div v-if="selected" class="viewer" role="dialog" aria-modal="true" :aria-label="`${selected.contract_no} 照片预览`" @click.self="selected = null">
      <header><div><p>{{ selected.contract_no }} <template v-if="selectedIndex >= 0">· {{ selectedIndex + 1 }} / {{ photos.length }}</template></p><b>{{ selected.product_type }}<template v-if="selected.specification"> · {{ selected.specification }}</template> · {{ selected.inspection_item }}</b></div><div class="viewer-actions"><button class="rotate-button" aria-label="将照片顺时针旋转90度" @click="rotatePhoto"><span aria-hidden="true">↻</span> 旋转 90°</button><button class="download-button" @click="openDownload([selected.id])">⇩ 下载</button><button class="close-button" aria-label="关闭预览" @click="selected = null">×</button></div></header>
      <p v-if="downloadError" class="viewer-error">{{ downloadError }}</p>
      <div class="viewer-stage" @pointerdown="startSwipe" @pointerup="endSwipe" @pointercancel="cancelSwipe"><img class="preview" :class="{ 'quarter-turn': rotation % 180 !== 0 }" :src="photoUrl(selected, 'preview')" alt="" :style="{ transform: rotationTransform }"><img class="full" :class="{ ready: fullLoaded, 'quarter-turn': rotation % 180 !== 0 }" :src="photoUrl(selected, 'full')" :alt="`${selected.contract_no} 高清照片`" :style="{ transform: rotationTransform }" @load="fullLoaded = true"><span v-if="!fullLoaded">正在加载高清图…</span><button class="viewer-nav previous" :disabled="!hasPrevious" aria-label="上一张照片" @pointerdown.stop @click="navigatePhoto(-1)">‹</button><button class="viewer-nav next" :disabled="!hasNext" aria-label="下一张照片" @pointerdown.stop @click="navigatePhoto(1)">›</button></div>
      <footer><span>{{ formatDate(selected.captured_at) }}<template v-if="selected.inspection_note"> · 备注：{{ selected.inspection_note }}</template><template v-if="scope === 'shared' && selected.photographer_name"> · 拍摄人：{{ selected.photographer_name }}</template></span><span>← → 切换图片 · Esc 关闭</span></footer>
    </div>
    <DownloadOptionsDialog
      v-if="downloadDialogOpen"
      v-model:with-watermark="downloadWithWatermark"
      :count="pendingDownloadIds.length"
      :unavailable-count="unavailableOriginalCount"
      @cancel="downloadDialogOpen = false"
      @confirm="confirmDownload"
    />
  </main>
</template>

<style>
:global(*){box-sizing:border-box}:global(body){margin:0;background:#f5f6f7;color:#1f2329;font-family:Inter,"PingFang SC","Microsoft YaHei",sans-serif}.desktop-gallery{min-height:100vh;display:flex;background:#f5f6f7}.sidebar{width:232px;flex:none;padding:22px 12px;border-right:1px solid #e7e9ed;background:#fff}.brand{height:40px;display:flex;align-items:center;gap:10px;padding:0 10px;color:#1f2329;text-decoration:none}.brand span{display:grid;place-items:center;width:30px;height:30px;border-radius:8px;background:#3370ff;color:#fff;font-size:11px;font-weight:800}.brand b{font-size:16px}.sidebar nav{margin-top:30px;display:grid;gap:4px}.sidebar nav button{height:42px;display:flex;align-items:center;gap:11px;padding:0 12px;border:0;border-radius:7px;background:transparent;color:#4e5969;font:inherit;font-size:14px;text-align:left;cursor:pointer}.sidebar nav i{font-style:normal;font-size:18px;color:#8d96a3}.sidebar nav button.active{background:#eaf1ff;color:#1456d9;font-weight:600}.sidebar nav button.active i{color:#3370ff}.side-hint{position:fixed;bottom:22px;width:190px;margin:0 10px;color:#8f959f;font-size:12px;line-height:18px}.workspace{min-width:0;flex:1}.workspace-header{height:72px;display:flex;align-items:center;justify-content:space-between;padding:0 32px;border-bottom:1px solid #e7e9ed;background:#fff}.crumb{margin:0 0 4px;color:#8b929e;font-size:12px}.workspace-header h1{margin:0;font-size:18px;line-height:24px}.account{display:flex;align-items:center;gap:8px;color:#596273;font-size:13px}.account span{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#dbeaff;color:#2766dc;font-weight:700}.content{max-width:1540px;margin:0 auto;padding:28px 32px 48px}.query-card{padding:20px 22px;border:1px solid #e7e9ed;border-radius:10px;background:#fff;box-shadow:0 1px 2px #1f232908}.search-row{display:flex;gap:10px}.search{height:40px;display:flex;align-items:center;flex:1;gap:9px;padding:0 11px;border:1px solid #d8dce3;border-radius:7px;color:#8c949e}.search:focus-within{border-color:#3370ff;box-shadow:0 0 0 3px #3370ff16}.search>span{font-size:22px;line-height:1;transform:rotate(-20deg)}.search input{min-width:0;flex:1;border:0;outline:0;font:inherit;font-size:14px}.search button{width:22px;height:22px;border:0;border-radius:50%;background:#f0f1f3;color:#687180;font-size:17px;line-height:18px;cursor:pointer}.search-submit{width:72px;border:0;border-radius:7px;background:#3370ff;color:#fff;font:inherit;font-size:14px;font-weight:600;cursor:pointer}.filters{display:flex;align-items:end;gap:12px;flex-wrap:wrap;margin-top:16px}.filters label{display:flex;flex-direction:column;gap:6px;color:#646e7c;font-size:12px}.filters select,.filters input{height:34px;min-width:158px;padding:0 9px;border:1px solid #dfe2e7;border-radius:6px;background:#fff;color:#303846;font:inherit;font-size:13px;outline:none}.filters input{min-width:144px}.filters select:focus,.filters input:focus{border-color:#3370ff}.clear-filters,.quick-dates button{border:0;background:transparent;color:#3370ff;font:inherit;font-size:12px;cursor:pointer}.clear-filters{height:34px;padding:0 6px}.quick-dates{display:flex;align-items:center;gap:12px;margin-top:15px;color:#8b929e;font-size:12px}.quick-dates button{padding:0}.quick-dates em{padding-left:3px;border-left:1px solid #e6e8ec;color:#737d8b;font-style:normal}.results{margin-top:22px}.results-head{display:flex;align-items:center;justify-content:space-between;min-height:38px}.results-head>div:first-child{display:flex;align-items:baseline;gap:10px}.results-head b{font-size:16px}.results-head span{color:#8a929e;font-size:12px}.result-tools{display:flex;align-items:center;gap:5px}.result-tools button{height:30px;min-width:30px;padding:0 9px;border:1px solid #dfe3e8;border-radius:6px;background:#fff;color:#5e6875;font:inherit;font-size:12px;cursor:pointer}.result-tools button.selected{border-color:#9bbcfb;background:#edf3ff;color:#2766dc}.result-tools .divider{width:1px;height:18px;margin:0 3px;background:#e0e3e8}.photo-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(198px,1fr));gap:16px;margin-top:14px}.photo-card{overflow:hidden;padding:0;border:1px solid #e3e6ea;border-radius:9px;background:#fff;color:inherit;text-align:left;cursor:pointer;transition:box-shadow .16s,transform .16s}.photo-card:hover{box-shadow:0 8px 20px #1f23291a;transform:translateY(-2px)}.photo-card img{display:block;width:100%;aspect-ratio:4 / 3;object-fit:cover;background:#edf0f2}.photo-meta{display:flex;flex-direction:column;gap:5px;padding:11px 12px 12px}.photo-meta b{overflow:hidden;font-size:14px;line-height:18px;text-overflow:ellipsis;white-space:nowrap}.photo-meta span{overflow:hidden;color:#4d5968;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.photo-meta small{overflow:hidden;color:#89919c;font-size:11px;line-height:15px;text-overflow:ellipsis;white-space:nowrap}.photo-grid.list{display:flex;flex-direction:column;gap:8px}.photo-grid.list .photo-card{display:flex;align-items:center}.photo-grid.list .photo-card img{width:132px;aspect-ratio:4 / 3;flex:none}.photo-grid.list .photo-meta{min-width:0;gap:6px}.state{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:250px;gap:10px;color:#88919c;font-size:14px}.state.error{color:#c53a32}.state.empty strong{color:#535d6b;font-size:15px}.state.empty button{margin-top:5px;padding:7px 12px;border:0;border-radius:6px;background:#edf3ff;color:#2863db;font:inherit;font-size:12px;cursor:pointer}.viewer{position:fixed;z-index:30;inset:0;display:flex;flex-direction:column;background:#12161dcc;color:#fff;backdrop-filter:blur(3px)}.viewer header{height:68px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;background:#171c25}.viewer header p,.viewer header b{margin:0;display:block}.viewer header p{margin-bottom:3px;font-size:14px}.viewer header b{max-width:60vw;overflow:hidden;color:#bac1cb;font-size:12px;font-weight:400;text-overflow:ellipsis;white-space:nowrap}.viewer header>div:last-child{display:flex;align-items:center;gap:18px}.viewer header a{padding:8px 11px;border-radius:6px;background:#3370ff;color:#fff;font-size:13px;text-decoration:none}.viewer header button{padding:0;border:0;background:transparent;color:#fff;font-size:29px;font-weight:200;cursor:pointer}.viewer-stage{position:relative;min-height:0;flex:1;display:grid;place-items:center;overflow:hidden;background:#0d1117}.viewer-stage img{position:absolute;max-width:94%;max-height:92%;object-fit:contain}.viewer-stage .preview{filter:blur(1px);opacity:.5}.viewer-stage .full{opacity:0;transition:opacity .2s}.viewer-stage .full.ready{opacity:1}.viewer-stage span{position:relative;padding:7px 11px;border-radius:16px;background:#202734cc;color:#dfe4eb;font-size:12px}.viewer footer{height:40px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;background:#171c25;color:#aeb6c1;font-size:12px}@media(max-width:780px){.sidebar{width:62px;padding:15px 8px}.brand{justify-content:center;padding:0}.brand b,.sidebar nav button:not(.active)::after,.side-hint{display:none}.sidebar nav button{justify-content:center;padding:0}.sidebar nav button{font-size:0}.workspace-header{padding:0 18px}.content{padding:20px 18px}.filters label{flex:1}.filters select,.filters input{width:100%;min-width:0}.photo-grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}}@media(max-width:560px){.desktop-gallery{min-width:520px}.content{padding:16px}.workspace-header{height:64px}.query-card{padding:15px}.photo-grid{grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}
.account img{width:30px;height:30px;border-radius:50%;object-fit:cover}
.results-head{gap:16px;flex-wrap:wrap}
.result-tools{flex-wrap:wrap}
.result-tools .selection-button,
.result-tools .download-selected{height:32px;padding:0 11px}
.result-tools .download-selected:not(:disabled){border-color:#3370ff;background:#3370ff;color:#fff;font-weight:600}
.result-tools button:disabled{color:#a5adb8;background:#f4f5f7;cursor:not-allowed}
.photo-card{position:relative}
.photo-open{display:block;width:100%;padding:0;border:0;background:transparent;color:inherit;text-align:left;cursor:pointer}
.photo-card.is-selected{border-color:#3370ff;box-shadow:0 0 0 2px #3370ff24}
.photo-select{position:absolute;z-index:3;top:9px;left:9px;width:23px;height:23px;display:grid;place-items:center;border:1.5px solid #d5dbe3;border-radius:5px;background:#fff;color:transparent;box-shadow:0 2px 7px #1f232929;cursor:pointer}
.photo-select input{position:absolute;width:1px;height:1px;opacity:0}
.photo-select span{font-size:15px;font-weight:800;line-height:1}
.photo-select.checked{border-color:#3370ff;background:#3370ff;color:#fff}
.photo-select:focus-within{outline:3px solid #3370ff2b;outline-offset:2px}
.photo-grid.list .photo-card{display:flex;align-items:center}
.photo-grid.list .photo-open{display:flex;align-items:center;min-width:0}
.photo-grid.list .photo-select{left:10px;top:50%;transform:translateY(-50%)}
.photo-grid.list .photo-card img{margin-left:24px}
.pagination{display:flex;align-items:center;justify-content:center;gap:7px;margin-top:24px}
.pagination button{min-width:34px;height:34px;padding:0 11px;border:1px solid #dfe3e8;border-radius:7px;background:#fff;color:#596473;font:inherit;font-size:12px;cursor:pointer}
.pagination button.active{border-color:#3370ff;background:#3370ff;color:#fff;font-weight:700}
.pagination button:disabled{border-color:#eceef1;background:#f6f7f8;color:#abb2bb;cursor:not-allowed}
.viewer-actions{gap:10px!important}
.viewer header .viewer-actions button{width:auto;height:34px;padding:0 12px;border:1px solid #ffffff2b;border-radius:7px;background:#2a3441;color:#fff;font-size:13px;font-weight:500;line-height:32px}
.viewer header .viewer-actions .rotate-button{border-color:#70a0ff;background:#2459bd}
.viewer header .viewer-actions .rotate-button span{display:inline-block;margin-right:4px;font-size:18px;vertical-align:-1px}
.viewer header .viewer-actions .download-button{background:#3370ff}
.viewer header .viewer-actions .close-button{width:34px;padding:0;border:0;background:transparent;font-size:29px;font-weight:200;line-height:30px}
.viewer header .viewer-actions button:focus-visible{outline:2px solid #fff;outline-offset:2px}
.viewer-stage img{transition:opacity .2s ease,transform .2s ease;transform-origin:center}
.viewer-stage img.quarter-turn{width:min(92vh,94vw);height:min(92vh,94vw);max-width:none;max-height:none;object-fit:contain}
.viewer .viewer-error{margin:0;padding:8px 28px;background:#9b2b2b;color:#fff;font-size:12px}
.viewer-stage .viewer-nav{position:absolute;z-index:4;top:50%;width:44px;height:68px;padding:0;transform:translateY(-50%);border-radius:10px;background:#141b24cc;color:#fff;font-size:42px;line-height:1;display:grid;place-items:center;backdrop-filter:blur(4px)}
.viewer-stage .viewer-nav.previous{left:18px}
.viewer-stage .viewer-nav.next{right:18px}
.viewer-stage .viewer-nav:disabled{opacity:.2;pointer-events:none}
@media(max-width:780px){.result-tools .selection-button,.result-tools .download-selected{padding:0 8px}.viewer header{padding:0 13px}.viewer header .viewer-actions{gap:5px!important}.viewer header .viewer-actions button{padding:0 8px}.viewer header b{max-width:40vw}}
</style>
