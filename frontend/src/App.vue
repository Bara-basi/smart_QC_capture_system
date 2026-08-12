<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

type Photo = { name: string; tone: string }

const page = ref<'home' | 'capture' | 'gallery'>('home')
const selectedSection = ref(0)
const isGrid = ref(false)
const toast = ref('')
const done = ref(false)
const isAuthenticating = ref(true)
const photos = ref<Record<string, Photo[]>>({ '法兰-产品整体与包装状态': [{ name: '产品整体.jpg', tone: 'steel-a' }] })

const sections = [
  { title: '法兰', count: '3 项待拍', key: '外观与标识', items: ['产品整体与包装状态', '法兰正面 / 密封面', '规格标识与炉批号'] },
  { title: '无缝管', count: '2 项待拍', key: '尺寸与细节', items: ['管材全貌与端口', '壁厚及长度测量'] },
  { title: '质保资料', count: '1 项待拍', key: '资料', items: ['材质证明书与检验报告'] },
]
const taskStatus = computed(() => done.value ? '已完成 · 可编辑' : '待拍摄')

function addPhoto(key: string) {
  const list = photos.value[key] ||= []
  list.push({ name: `现场照片_${String(list.length + 1).padStart(2, '0')}.jpg`, tone: list.length % 2 ? 'steel-b' : 'steel-c' })
}
function upload() {
  done.value = true
  toast.value = '上传成功'
  setTimeout(() => { toast.value = ''; page.value = 'home' }, 1200)
}

onMounted(async () => {
  try {
    const response = await fetch('/api/v1/auth/me', { credentials: 'include' })
    if (!response.ok) window.location.replace('/api/v1/auth/feishu/login')
  } catch {
    window.location.replace('/api/v1/auth/feishu/login')
  } finally {
    isAuthenticating.value = false
  }
})
</script>

<template>
  <main v-if="!isAuthenticating" class="stage">
    <div class="phone">
      <section v-if="page === 'home'" class="screen home-screen">
        <header class="topbar"><span class="brand-mark">QC</span><strong>质检拍照</strong><button class="round-btn">•••</button></header>
        <div class="greeting"><div class="avatar">林</div><div><p class="eyebrow">上午好，林工</p><h1>今天有 1 个拍照任务</h1><p class="muted">每一张照片，都让交付更有凭据。</p></div><span class="search">⌕</span></div>
        <div class="todo-card"><div class="card-heading"><span>我的待办</span><button @click="page = 'capture'">查看全部 ›</button></div><div class="todo-row"><div class="todo-icon">✓</div><div><b>{{ done ? '1 / 1' : '0 / 1' }}</b><small>我负责</small></div><div class="todo-sep"></div><div><b>0</b><small>今日已完成</small></div><span class="go">›</span></div></div>
        <div class="list-title"><div><p class="eyebrow">合同任务</p><h2>待处理订单</h2></div><button class="filter">筛选<span class="inline-chev" aria-hidden="true"></span></button></div>
        <article class="contract-card" @click="page = 'capture'"><div class="contract-top"><span class="status" :class="{ done }">{{ taskStatus }}</span><span class="due">截止 08 月 14 日</span></div><h3>HT-2026-0810-047</h3><p>中东海工项目 · PO-MLD-3288</p><div class="tag-row"><span>法兰</span><span>无缝管</span><span>6 个拍摄项</span></div><div class="progress"><i :style="{ width: done ? '100%' : '17%' }"></i></div><footer><span>{{ done ? '资料已提交，可继续补充照片' : '已完成 1 / 6 项' }}</span><b>进入拍摄 ›</b></footer></article>
        <article class="contract-card soft"><div class="contract-top"><span class="status gray">待开始</span><span class="due">截止 08 月 18 日</span></div><h3>HT-2026-0810-052</h3><p>东南亚管件订单 · PO-TR-7251</p><div class="tag-row"><span>弯头</span><span>三通</span></div></article>
      </section>

      <section v-else-if="page === 'capture'" class="screen capture-screen">
        <header class="topbar"><button class="back" @click="page = 'home'">‹</button><strong>拍照任务</strong><button class="round-btn">•••</button></header>
        <article class="order-card"><div><span class="eyebrow">合同编号</span><h2>HT-2026-0810-047</h2><p>中东海工项目 · 截止 08 月 14 日</p></div><div class="order-badge"><b>1/6</b><small>已完成</small></div></article>
        <p class="hint">请按清单拍摄。带 <em>*</em> 项为交付必需照片。</p>
        <div v-for="(section, index) in sections" :key="section.title" class="capture-group" :class="{ open: selectedSection === index }"><button class="group-head" @click="selectedSection = selectedSection === index ? -1 : index"><span class="component-icon">⌘</span><b>{{ section.title }}</b><small>{{ section.count }}</small><span class="chev">⌄</span></button><div v-if="selectedSection === index" class="group-content"><div v-for="(item, itemIndex) in section.items" :key="item" class="shot-item"><div class="shot-heading"><div class="check" :class="{ checked: index === 0 && itemIndex === 0 }">{{ index === 0 && itemIndex === 0 ? '✓' : '' }}</div><div><b>{{ item }} <em>*</em></b><p>{{ itemIndex === 0 ? '建议横向拍摄，画面包含整体状态' : '请确保文字、刻印清晰可识别' }}</p></div></div><div class="photo-row"><div v-for="photo in photos[`${section.title}-${item}`] || []" :key="photo.name" class="photo" :class="photo.tone"><span>{{ photo.name }}</span></div><button class="add-photo" @click="addPhoto(`${section.title}-${item}`)"><i>+</i><span>拍照</span></button></div></div></div></div>
        <div class="bottom-action"><button @click="upload">完成并上传</button></div>
      </section>

      <section v-else class="screen gallery-screen">
        <header class="topbar"><span class="brand-mark">QC</span><strong>图片检索</strong><button class="round-btn">⌕</button></header>
        <div class="tabs"><button class="active">我拍摄的</button><button>与我共享</button><button class="view-toggle" @click="isGrid = !isGrid">{{ isGrid ? '▤' : '⊞' }}</button></div>
        <div class="search-box"><span>⌕</span><span class="placeholder">合同号、产品类型、部位</span><button>筛选</button></div>
        <div class="filter-chips"><span>HT-2026-0810-047<i class="inline-chev" aria-hidden="true"></i></span><span>全部产品<i class="inline-chev" aria-hidden="true"></i></span><span>全部部位<i class="inline-chev" aria-hidden="true"></i></span></div>
        <div class="result-head"><b>18 张照片</b><small>按最近拍摄排序</small></div>
        <div class="gallery" :class="{ grid: isGrid }"><article v-for="(photo, i) in [{name:'法兰正面.jpg', tone:'steel-a', info:'法兰 · 密封面 · 今天 10:22'}, {name:'无缝管端口.jpg', tone:'steel-b', info:'无缝管 · 管端 · 昨天 16:08'}, {name:'炉批号特写.jpg', tone:'steel-c', info:'法兰 · 标识 · 昨天 15:46'}, {name:'包装全貌.jpg', tone:'steel-d', info:'外包装 · 全貌 · 08/08'}]" :key="photo.name" class="gallery-item"><div class="thumb" :class="photo.tone"><span class="img-label">QC</span></div><div class="file-info"><b>{{ photo.name }}</b><small>{{ photo.info }}</small></div><button v-if="!isGrid" class="more">•••</button></article></div>
      </section>
      <nav class="nav"><button :class="{ active: page === 'home' }" @click="page = 'home'"><i>⌂</i><span>首页</span></button><button :class="{ active: page === 'capture' }" @click="page = 'capture'"><i>▣</i><span>拍照任务</span></button><button :class="{ active: page === 'gallery' }" @click="page = 'gallery'"><i>▦</i><span>图片检索</span></button></nav>
      <transition name="toast"><div v-if="toast" class="toast">✓&nbsp; {{ toast }}</div></transition>
    </div>
  </main>
</template>

<style>
* { box-sizing: border-box; } body { margin: 0; background: #e9edf3; color: #1f2329; font-family: Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif; } button { font: inherit; color: inherit; cursor: pointer; border: 0; background: none; } .stage { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: radial-gradient(circle at 12% 20%, #f9fbff 0 8%, transparent 25%), #e9edf3; } .phone { width: min(100%, 430px); height: min(880px, calc(100vh - 48px)); overflow: hidden; position: relative; background: #f5f7fa; border: 8px solid #1e252e; border-radius: 34px; box-shadow: 0 24px 70px #63708466; } .screen { overflow-y: auto; height: 100%; padding: 18px 16px 92px; scrollbar-width: none; } .topbar { height: 42px; display: flex; align-items: center; justify-content: space-between; } .topbar strong { font-size: 18px; letter-spacing: .2px; } .brand-mark { width: 31px; height: 31px; display: grid; place-items: center; background: #3370ff; color: white; border-radius: 9px; font-size: 12px; font-weight: 800; letter-spacing: -1px; } .round-btn { color: #67707c; font-weight: 800; letter-spacing: 1px; font-size: 16px; } .greeting { display: flex; align-items: center; gap: 11px; margin: 21px 4px 25px; } .avatar { width: 43px; height: 43px; border-radius: 14px; color: #fff; font-weight: bold; display: grid; place-items: center; background: linear-gradient(135deg, #6c8b6b, #243a43); } h1,h2,h3,p { margin: 0; } h1 { font-size: 20px; margin: 3px 0; } h2 { font-size: 17px; } h3 { font-size: 17px; margin: 8px 0 5px; } .eyebrow,.muted { color: #8a919f; font-size: 12px; } .search { color: #7a8494; margin-left: auto; font-size: 31px; transform: rotate(-20deg); } .todo-card,.contract-card,.order-card { background:#fff; border-radius: 16px; box-shadow: 0 5px 18px #17233c0b; } .todo-card { padding: 17px; } .card-heading,.list-title,.contract-top,footer,.result-head { display: flex; align-items: center; justify-content: space-between; } .card-heading { font-weight: 700; font-size: 17px; } .card-heading button { color: #3370ff; font-size: 12px; } .todo-row { display:flex; align-items:center; gap:10px; padding-top: 18px; } .todo-icon { color:#2fa56b; background:#e6f7ef; font-weight: 800; width:39px;height:39px;border-radius:12px;display:grid;place-items:center;font-size:20px }.todo-row b { font-size:18px; display:block; }.todo-row small { color:#8a919f; font-size:11px; }.todo-sep { height:30px; width:1px; background:#e6e8eb; margin: 0 8px; }.go { margin-left:auto;color:#a0a7b1;font-size:25px; }.list-title { margin: 26px 3px 12px; }.list-title h2 { margin-top:3px; }.filter { color:#6b7480;font-size:13px; }.contract-card { margin-bottom: 13px; padding: 15px 16px; }.contract-card.soft { opacity:.72; }.status { background:#fff3df;color:#c27600;padding:3px 7px;border-radius:5px;font-size:11px; }.status.done { background:#e3f5ea;color:#168756; }.status.gray {background:#f0f1f3;color:#6f7783}.due { color:#7e8793;font-size:12px; }.contract-card p { color:#737c88;font-size:13px; }.tag-row { display:flex;gap:6px;margin:12px 0;flex-wrap:wrap; }.tag-row span,.filter-chips span { padding:4px 8px;border-radius:5px;background:#f0f4fa;color:#637084;font-size:11px; }.progress { height:4px;background:#edf0f3;border-radius:4px;overflow:hidden; }.progress i { display:block;height:100%;background:#3370ff;border-radius:4px; }.contract-card footer { margin-top:11px;font-size:11px;color:#848d99; }.contract-card footer b { color:#3370ff;font-weight:600; }.back {font-size:36px;line-height:20px;color:#4a5564}.order-card { margin-top:18px;padding:16px;display:flex;justify-content:space-between;align-items:center;background: linear-gradient(125deg,#ffffff,#eef5ff);border:1px solid #e2ebfb; }.order-card h2 { margin:4px 0;font-size:19px;}.order-card p {font-size:12px;color:#737c88}.order-badge { text-align:right;color:#3370ff}.order-badge b,.order-badge small{display:block}.order-badge small{font-size:11px;color:#7c8795;margin-top:3px}.hint {font-size:12px;color:#757f8c;margin:14px 4px}.hint em,.shot-item em {font-style:normal;color:#ef6457}.capture-group { background:#fff;border-radius:13px;margin:10px 0;overflow:hidden;border:1px solid #edf0f4}.group-head {width:100%;padding:14px;display:flex;align-items:center;text-align:left;gap:9px}.component-icon {color:#3370ff;background:#edf3ff;border-radius:6px;padding:3px 5px}.group-head small{color:#9299a4;margin-left:auto;font-size:11px}.chev{color:#84909d;font-size:17px}.group-content{padding:0 14px 14px;border-top:1px solid #f0f2f5}.shot-item{display:flex;gap:9px;padding:13px 0 8px}.check{width:17px;height:17px;border:1.5px solid #c6ccd6;border-radius:50%;font-size:11px;display:grid;place-items:center;color:white;flex:none;margin-top:2px}.check.checked{background:#3370ff;border-color:#3370ff}.shot-item b{font-size:13px}.shot-item p{font-size:11px;color:#8b94a1;margin-top:4px}.photo-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}.photo,.add-photo{width:74px;height:74px;border-radius:8px;overflow:hidden}.photo{position:relative;background:#73828d}.photo::after,.thumb::after{content:"";position:absolute;inset:0;background:linear-gradient(125deg,transparent 38%,#ffffff19 38% 42%,transparent 42%),linear-gradient(30deg,#24333b55,transparent 55%)}.photo span{position:absolute;bottom:4px;left:4px;right:4px;color:white;font-size:8px;z-index:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.add-photo{border:1px dashed #94b6fb;background:#f6f9ff;color:#3370ff;display:flex;flex-direction:column;align-items:center;justify-content:center}.add-photo i{font-size:25px;font-style:normal;line-height:22px}.add-photo span{font-size:10px;margin-top:3px}.steel-a{background:linear-gradient(135deg,#aab7bc,#3d4d55 42%,#bbc6c9 44%,#526770)}.steel-b{background:linear-gradient(35deg,#304852,#b08f6c 48%,#253941 52%)}.steel-c{background:linear-gradient(135deg,#554c47,#bda883 45%,#293f48 46%)}.steel-d{background:linear-gradient(135deg,#c4ad8d,#657781 43%,#334853 44%)}.bottom-action{position:absolute;bottom:67px;left:0;right:0;padding:9px 16px 0;background:linear-gradient(transparent,#f5f7fa 25%)}.bottom-action button{width:100%;background:#3370ff;color:white;font-weight:600;padding:13px;border-radius:10px;box-shadow:0 5px 11px #3370ff44}.tabs{display:flex;align-items:center;border-bottom:1px solid #e6e9ee;margin-top:13px}.tabs button{padding:10px 4px;margin-right:23px;font-size:14px;color:#737d89}.tabs .active{color:#3370ff;border-bottom:2px solid #3370ff;font-weight:600}.tabs .view-toggle{margin-left:auto;margin-right:0;font-size:23px;padding:4px;color:#4b5563}.search-box{height:39px;background:#fff;border:1px solid #e6eaf0;border-radius:9px;margin:15px 0 9px;display:flex;align-items:center;padding:0 11px;gap:8px;color:#8d96a2}.placeholder{font-size:12px;flex:1}.search-box button{font-size:12px;color:#3370ff;border-left:1px solid #e8ebef;padding-left:9px}.filter-chips{display:flex;gap:6px;overflow:hidden;white-space:nowrap}.result-head{margin:19px 0 10px}.result-head b{font-size:14px}.result-head small{font-size:11px;color:#969eaa}.gallery{display:flex;flex-direction:column;gap:8px}.gallery-item{display:flex;align-items:center;gap:10px;background:#fff;border-radius:10px;padding:8px;box-shadow:0 2px 8px #17233c08}.thumb{width:62px;height:52px;border-radius:6px;position:relative;overflow:hidden}.img-label{position:absolute;left:5px;top:4px;color:#fff;font-weight:bold;font-size:9px;z-index:2}.file-info{display:flex;flex-direction:column;gap:5px;min-width:0}.file-info b{font-size:13px}.file-info small{font-size:11px;color:#8a939f}.more{margin-left:auto;color:#9aa2ad;font-weight:bold}.gallery.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.gallery.grid .gallery-item{display:block;padding:7px}.gallery.grid .thumb{width:100%;height:111px}.gallery.grid .file-info{padding:7px 2px 2px}.gallery.grid .file-info small{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.nav{height:68px;position:absolute;z-index:3;bottom:0;left:0;right:0;background:#fff;border-top:1px solid #e5e8ec;display:flex;justify-content:space-around;padding-top:8px}.nav button{color:#89929e;display:flex;flex-direction:column;align-items:center;gap:3px;font-size:11px;min-width:80px}.nav i{font-style:normal;font-size:22px;line-height:24px}.nav .active{color:#3370ff;font-weight:600}.toast{position:absolute;z-index:9;left:50%;top:45%;transform:translate(-50%,-50%);padding:14px 22px;border-radius:9px;background:#343a43eF;color:#fff;font-size:14px;box-shadow:0 8px 22px #1e252e66}.toast-enter-active,.toast-leave-active{transition:.2s}.toast-enter-from,.toast-leave-to{opacity:0;transform:translate(-50%,-42%)}@media(max-width:600px){.stage{padding:0;background:#f5f7fa}.phone{width:100%;height:100vh;border:0;border-radius:0;box-shadow:none}}
.shot-item { display:grid !important; grid-template-columns:minmax(0, 1fr); grid-template-rows:auto auto; padding:13px 0 12px; border-bottom:1px solid #f0f2f5; }
.shot-item:last-child { border-bottom:0; }
.shot-heading { display:flex; gap:9px; }
.shot-item .photo-row { grid-column:1; grid-row:2; width:calc(100% - 26px); margin:9px 0 0 26px; }

/* Mobile browsers use a dynamic visual viewport while their address bars are visible. */
@media (max-width:600px) {
  .stage { height:100dvh; min-height:100dvh; }
  .phone, .screen { height:100dvh; }
  .screen { padding-bottom:calc(84px + env(safe-area-inset-bottom)); }
  .nav {
    position:fixed;
    z-index:30;
    height:calc(68px + env(safe-area-inset-bottom));
    padding-bottom:env(safe-area-inset-bottom);
  }
  .bottom-action {
    position:fixed;
    z-index:20;
    bottom:calc(80px + env(safe-area-inset-bottom));
  }
}

/* Replace the text glyph with a compact, Feishu-like line chevron. */
.group-head .chev {
  width:18px;
  height:18px;
  display:flex;
  align-items:center;
  justify-content:center;
  margin-left:2px;
  color:#7b8491;
  font-size:0;
  line-height:1;
  flex:none;
}
.group-head .chev::before {
  content:"";
  width:7px;
  height:7px;
  border-right:1.5px solid currentColor;
  border-bottom:1.5px solid currentColor;
  transform:translateY(-2px) rotate(45deg);
}
.filter,
.filter-chips span {
  display:inline-flex;
  align-items:center;
  gap:5px;
}
.inline-chev {
  display:inline-block;
  width:6px;
  height:6px;
  margin-top:-3px;
  border-right:1.25px solid currentColor;
  border-bottom:1.25px solid currentColor;
  transform:rotate(45deg);
  flex:none;
}
</style>
