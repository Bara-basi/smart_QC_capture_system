<script setup lang="ts">
import { onMounted, ref } from 'vue'
const emit = defineEmits<{ resolve: [allowed: boolean] }>()
const dialog = ref<HTMLDialogElement | null>(null)
onMounted(() => dialog.value?.showModal())
</script>

<template>
  <dialog ref="dialog" class="exit-dialog" aria-labelledby="exit-title" aria-describedby="exit-description" @cancel.prevent="emit('resolve', false)">
    <div class="exit-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M10 5H5v14h5m4-12 5 5-5 5m-5-5h10" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    <h2 id="exit-title">退出质检拍照？</h2>
    <p id="exit-description">即将离开当前系统，返回飞书。退出前请确认需要上传的照片已提交。</p>
    <div class="exit-actions"><button autofocus class="stay" @click="emit('resolve', false)">继续使用</button><button class="leave" @click="emit('resolve', true)">确认退出</button></div>
  </dialog>
</template>

<style scoped>
.exit-dialog{width:min(340px,calc(100% - 40px));padding:24px;border:0;border-radius:18px;background:#fff;color:#202630;box-shadow:0 24px 70px #10172240;animation:dialog-in .2s ease-out}
.exit-dialog::backdrop{background:#10172299;backdrop-filter:blur(3px)}
.exit-mark{display:grid;place-items:center;width:42px;height:42px;margin-bottom:16px;border-radius:12px;background:#eaf1ff;color:#3370ff}
.exit-mark svg{width:24px;height:24px}
h2{margin:0;font-size:18px}p{margin:10px 0 24px;color:#7b8490;font-size:13px;line-height:1.7}
.exit-actions{display:flex;gap:10px}.exit-actions button{flex:1;height:40px;border:0;border-radius:9px;font:inherit;font-size:13px;font-weight:600;cursor:pointer}
.stay{background:#eef2f7;color:#596575}.leave{background:#3370ff;color:#fff}
button:focus-visible{outline:2px solid #3370ff;outline-offset:3px}
@keyframes dialog-in{from{opacity:0;transform:translateY(10px) scale(.98)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){.exit-dialog{animation:none}}
</style>
