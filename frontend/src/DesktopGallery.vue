<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

type GalleryPhoto = { id: string; contract_no: string; product_type: string; specification: string; inspection_item: string; captured_at: string; photographer_name: string }
type GalleryResponse = { photos: GalleryPhoto[]; count: number }
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
const loading = ref(true)
const error = ref('')
const selected = ref<GalleryPhoto | null>(null)
const fullLoaded = ref(false)
let searchTimer = 0

const partLabel = computed(() => partOptions.find(item => item.value === part.value)?.label || '全部部位')
const activeFilterCount = computed(() => Number(Boolean(product.value)) + Number(Boolean(part.value)) + Number(Boolean(from.value || to.value)))
const dateSummary = computed(() => from.value || to.value ? `${from.value || '最早'} 至 ${to.value || '今天'}` : '全部时间')

async function loadPhotos() {
  loading.value = true
  error.value = ''
  try {
    const query = new URLSearchParams({ scope: scope.value, sort: sort.value })
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
    photos.value = (await response.json() as GalleryResponse).photos
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '图片加载失败'
  } finally { loading.value = false }
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
function openPhoto(photo: GalleryPhoto) { selected.value = photo; fullLoaded.value = false }
function onKeydown(event: KeyboardEvent) { if (event.key === 'Escape') selected.value = null }
onMounted(() => { window.addEventListener('keydown', onKeydown); loadPhotos() })
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
        <div class="account"><span>质</span><b>照片查看</b></div>
      </header>

      <div class="content">
        <section class="query-card" aria-label="图片筛选">
          <div class="search-row">
            <label class="search"><span>⌕</span><input v-model="keyword" type="search" maxlength="200" placeholder="搜索合同编号、产品、规格或拍摄部位" @input="scheduleSearch" @keyup.enter="loadPhotos"><button v-if="keyword" aria-label="清空搜索" @click="keyword = ''; loadPhotos()">×</button></label>
            <button class="search-submit" @click="loadPhotos">搜索</button>
          </div>
          <div class="filters">
            <label>产品<select v-model="product" @change="loadPhotos"><option value="">全部产品</option><option v-for="item in productOptions" :key="item" :value="item">{{ item }}</option></select></label>
            <label>拍摄部位<select v-model="part" @change="loadPhotos"><option value="">全部部位</option><option v-for="item in partOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
            <label>开始日期<input v-model="from" type="date" :max="to || undefined" @change="loadPhotos"></label>
            <label>结束日期<input v-model="to" type="date" :min="from || undefined" @change="loadPhotos"></label>
            <button v-if="activeFilterCount" class="clear-filters" @click="resetFilters">清除筛选（{{ activeFilterCount }}）</button>
          </div>
          <div class="quick-dates"><span>快捷时间：</span><button @click="datePreset(0)">今天</button><button @click="datePreset(6)">近 7 天</button><button @click="datePreset('month')">本月</button><em v-if="from || to">{{ dateSummary }}</em></div>
        </section>

        <section class="results" aria-live="polite">
          <header class="results-head"><div><b>{{ loading ? '正在加载…' : `${photos.length} 张照片` }}</b><span v-if="!loading">{{ scope === 'mine' ? '您拍摄并上传的照片' : '他人共享给您的照片' }}</span></div><div class="result-tools"><button :title="sort === 'desc' ? '当前按最新拍摄时间排序' : '当前按最早拍摄时间排序'" @click="sort = sort === 'desc' ? 'asc' : 'desc'; loadPhotos()">{{ sort === 'desc' ? '↓ 最新优先' : '↑ 最早优先' }}</button><span class="divider"/><button :class="{ selected: view === 'grid' }" title="宫格视图" @click="view = 'grid'">▦</button><button :class="{ selected: view === 'list' }" title="列表视图" @click="view = 'list'">☷</button></div></header>
          <p v-if="error" class="state error">{{ error }}</p>
          <p v-else-if="loading" class="state">正在载入照片…</p>
          <div v-else-if="photos.length" class="photo-grid" :class="view">
            <button v-for="photo in photos" :key="photo.id" class="photo-card" @click="openPhoto(photo)">
              <img :src="photoUrl(photo, 'preview')" :alt="`${photo.contract_no} ${photo.inspection_item}`">
              <div class="photo-meta"><b>{{ photo.contract_no }}</b><span>{{ photo.product_type }}<template v-if="photo.specification"> · {{ photo.specification }}</template></span><small>{{ photo.inspection_item }} · {{ formatDate(photo.captured_at) }}</small><small v-if="scope === 'shared' && photo.photographer_name">拍摄人：{{ photo.photographer_name }}</small></div>
            </button>
          </div>
          <div v-else class="state empty"><strong>未找到符合条件的照片</strong><span>请调整搜索内容或筛选条件后重试</span><button v-if="keyword || activeFilterCount" @click="keyword = ''; resetFilters()">清空搜索与筛选</button></div>
        </section>
      </div>
    </section>

    <div v-if="selected" class="viewer" role="dialog" aria-modal="true" :aria-label="`${selected.contract_no} 照片预览`" @click.self="selected = null">
      <header><div><p>{{ selected.contract_no }}</p><b>{{ selected.product_type }}<template v-if="selected.specification"> · {{ selected.specification }}</template> · {{ selected.inspection_item }}</b></div><div><a :href="photoUrl(selected, 'download')" target="_blank" rel="noopener">⇩ 下载原图</a><button aria-label="关闭预览" @click="selected = null">×</button></div></header>
      <div class="viewer-stage"><img class="preview" :src="photoUrl(selected, 'preview')" alt=""><img class="full" :class="{ ready: fullLoaded }" :src="photoUrl(selected, 'full')" :alt="`${selected.contract_no} 高清照片`" @load="fullLoaded = true"><span v-if="!fullLoaded">正在加载高清图…</span></div>
      <footer><span>{{ formatDate(selected.captured_at) }}<template v-if="scope === 'shared' && selected.photographer_name"> · 拍摄人：{{ selected.photographer_name }}</template></span><span>按 Esc 关闭</span></footer>
    </div>
  </main>
</template>

<style>
:global(*){box-sizing:border-box}:global(body){margin:0;background:#f5f6f7;color:#1f2329;font-family:Inter,"PingFang SC","Microsoft YaHei",sans-serif}.desktop-gallery{min-height:100vh;display:flex;background:#f5f6f7}.sidebar{width:232px;flex:none;padding:22px 12px;border-right:1px solid #e7e9ed;background:#fff}.brand{height:40px;display:flex;align-items:center;gap:10px;padding:0 10px;color:#1f2329;text-decoration:none}.brand span{display:grid;place-items:center;width:30px;height:30px;border-radius:8px;background:#3370ff;color:#fff;font-size:11px;font-weight:800}.brand b{font-size:16px}.sidebar nav{margin-top:30px;display:grid;gap:4px}.sidebar nav button{height:42px;display:flex;align-items:center;gap:11px;padding:0 12px;border:0;border-radius:7px;background:transparent;color:#4e5969;font:inherit;font-size:14px;text-align:left;cursor:pointer}.sidebar nav i{font-style:normal;font-size:18px;color:#8d96a3}.sidebar nav button.active{background:#eaf1ff;color:#1456d9;font-weight:600}.sidebar nav button.active i{color:#3370ff}.side-hint{position:fixed;bottom:22px;width:190px;margin:0 10px;color:#8f959f;font-size:12px;line-height:18px}.workspace{min-width:0;flex:1}.workspace-header{height:72px;display:flex;align-items:center;justify-content:space-between;padding:0 32px;border-bottom:1px solid #e7e9ed;background:#fff}.crumb{margin:0 0 4px;color:#8b929e;font-size:12px}.workspace-header h1{margin:0;font-size:18px;line-height:24px}.account{display:flex;align-items:center;gap:8px;color:#596273;font-size:13px}.account span{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#dbeaff;color:#2766dc;font-weight:700}.content{max-width:1540px;margin:0 auto;padding:28px 32px 48px}.query-card{padding:20px 22px;border:1px solid #e7e9ed;border-radius:10px;background:#fff;box-shadow:0 1px 2px #1f232908}.search-row{display:flex;gap:10px}.search{height:40px;display:flex;align-items:center;flex:1;gap:9px;padding:0 11px;border:1px solid #d8dce3;border-radius:7px;color:#8c949e}.search:focus-within{border-color:#3370ff;box-shadow:0 0 0 3px #3370ff16}.search>span{font-size:22px;line-height:1;transform:rotate(-20deg)}.search input{min-width:0;flex:1;border:0;outline:0;font:inherit;font-size:14px}.search button{width:22px;height:22px;border:0;border-radius:50%;background:#f0f1f3;color:#687180;font-size:17px;line-height:18px;cursor:pointer}.search-submit{width:72px;border:0;border-radius:7px;background:#3370ff;color:#fff;font:inherit;font-size:14px;font-weight:600;cursor:pointer}.filters{display:flex;align-items:end;gap:12px;flex-wrap:wrap;margin-top:16px}.filters label{display:flex;flex-direction:column;gap:6px;color:#646e7c;font-size:12px}.filters select,.filters input{height:34px;min-width:158px;padding:0 9px;border:1px solid #dfe2e7;border-radius:6px;background:#fff;color:#303846;font:inherit;font-size:13px;outline:none}.filters input{min-width:144px}.filters select:focus,.filters input:focus{border-color:#3370ff}.clear-filters,.quick-dates button{border:0;background:transparent;color:#3370ff;font:inherit;font-size:12px;cursor:pointer}.clear-filters{height:34px;padding:0 6px}.quick-dates{display:flex;align-items:center;gap:12px;margin-top:15px;color:#8b929e;font-size:12px}.quick-dates button{padding:0}.quick-dates em{padding-left:3px;border-left:1px solid #e6e8ec;color:#737d8b;font-style:normal}.results{margin-top:22px}.results-head{display:flex;align-items:center;justify-content:space-between;min-height:38px}.results-head>div:first-child{display:flex;align-items:baseline;gap:10px}.results-head b{font-size:16px}.results-head span{color:#8a929e;font-size:12px}.result-tools{display:flex;align-items:center;gap:5px}.result-tools button{height:30px;min-width:30px;padding:0 9px;border:1px solid #dfe3e8;border-radius:6px;background:#fff;color:#5e6875;font:inherit;font-size:12px;cursor:pointer}.result-tools button.selected{border-color:#9bbcfb;background:#edf3ff;color:#2766dc}.result-tools .divider{width:1px;height:18px;margin:0 3px;background:#e0e3e8}.photo-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(198px,1fr));gap:16px;margin-top:14px}.photo-card{overflow:hidden;padding:0;border:1px solid #e3e6ea;border-radius:9px;background:#fff;color:inherit;text-align:left;cursor:pointer;transition:box-shadow .16s,transform .16s}.photo-card:hover{box-shadow:0 8px 20px #1f23291a;transform:translateY(-2px)}.photo-card img{display:block;width:100%;aspect-ratio:4 / 3;object-fit:cover;background:#edf0f2}.photo-meta{display:flex;flex-direction:column;gap:5px;padding:11px 12px 12px}.photo-meta b{overflow:hidden;font-size:14px;line-height:18px;text-overflow:ellipsis;white-space:nowrap}.photo-meta span{overflow:hidden;color:#4d5968;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.photo-meta small{overflow:hidden;color:#89919c;font-size:11px;line-height:15px;text-overflow:ellipsis;white-space:nowrap}.photo-grid.list{display:flex;flex-direction:column;gap:8px}.photo-grid.list .photo-card{display:flex;align-items:center}.photo-grid.list .photo-card img{width:132px;aspect-ratio:4 / 3;flex:none}.photo-grid.list .photo-meta{min-width:0;gap:6px}.state{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:250px;gap:10px;color:#88919c;font-size:14px}.state.error{color:#c53a32}.state.empty strong{color:#535d6b;font-size:15px}.state.empty button{margin-top:5px;padding:7px 12px;border:0;border-radius:6px;background:#edf3ff;color:#2863db;font:inherit;font-size:12px;cursor:pointer}.viewer{position:fixed;z-index:30;inset:0;display:flex;flex-direction:column;background:#12161dcc;color:#fff;backdrop-filter:blur(3px)}.viewer header{height:68px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;background:#171c25}.viewer header p,.viewer header b{margin:0;display:block}.viewer header p{margin-bottom:3px;font-size:14px}.viewer header b{max-width:60vw;overflow:hidden;color:#bac1cb;font-size:12px;font-weight:400;text-overflow:ellipsis;white-space:nowrap}.viewer header>div:last-child{display:flex;align-items:center;gap:18px}.viewer header a{padding:8px 11px;border-radius:6px;background:#3370ff;color:#fff;font-size:13px;text-decoration:none}.viewer header button{padding:0;border:0;background:transparent;color:#fff;font-size:29px;font-weight:200;cursor:pointer}.viewer-stage{position:relative;min-height:0;flex:1;display:grid;place-items:center;overflow:hidden;background:#0d1117}.viewer-stage img{position:absolute;max-width:94%;max-height:92%;object-fit:contain}.viewer-stage .preview{filter:blur(1px);opacity:.5}.viewer-stage .full{opacity:0;transition:opacity .2s}.viewer-stage .full.ready{opacity:1}.viewer-stage span{position:relative;padding:7px 11px;border-radius:16px;background:#202734cc;color:#dfe4eb;font-size:12px}.viewer footer{height:40px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;background:#171c25;color:#aeb6c1;font-size:12px}@media(max-width:780px){.sidebar{width:62px;padding:15px 8px}.brand{justify-content:center;padding:0}.brand b,.sidebar nav button:not(.active)::after,.side-hint{display:none}.sidebar nav button{justify-content:center;padding:0}.sidebar nav button{font-size:0}.workspace-header{padding:0 18px}.content{padding:20px 18px}.filters label{flex:1}.filters select,.filters input{width:100%;min-width:0}.photo-grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}}@media(max-width:560px){.desktop-gallery{min-width:520px}.content{padding:16px}.workspace-header{height:64px}.query-card{padding:15px}.photo-grid{grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}}
</style>
