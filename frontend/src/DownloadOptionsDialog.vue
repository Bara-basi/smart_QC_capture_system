<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  count: number
  unavailableCount?: number
}>()

const withWatermark = defineModel<boolean>('withWatermark', { required: true })
const emit = defineEmits<{
  cancel: []
  confirm: []
}>()

const hasUnavailableOriginals = computed(() => !withWatermark.value && (props.unavailableCount || 0) > 0)
</script>

<template>
  <div class="download-dialog-backdrop" role="presentation" @click.self="emit('cancel')">
    <section class="download-options" role="dialog" aria-modal="true" aria-labelledby="download-options-title">
      <div class="dialog-mark" aria-hidden="true">⇩</div>
      <h2 id="download-options-title">{{ count > 1 ? `下载所选 ${count} 张照片` : '下载照片' }}</h2>
      <p>下载前请选择图片是否携带质检水印。</p>

      <label class="watermark-choice">
        <input v-model="withWatermark" type="checkbox">
        <span class="check-box" aria-hidden="true">✓</span>
        <span>
          <b>下载图片携带水印</b>
          <small>勾选后下载带合同号、规格和拍摄时间的质检水印图片</small>
        </span>
      </label>

      <p v-if="hasUnavailableOriginals" class="choice-warning">
        所选内容中有 {{ unavailableCount }} 张历史照片没有无水印原图，请勾选携带水印后继续。
      </p>
      <p v-else-if="!withWatermark" class="choice-note">将下载原始清晰图片，不包含质检水印。</p>

      <div class="dialog-actions">
        <button type="button" class="secondary" @click="emit('cancel')">取消</button>
        <button type="button" class="primary" :disabled="hasUnavailableOriginals" @click="emit('confirm')">
          {{ count > 1 ? '开始批量下载' : '开始下载' }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.download-dialog-backdrop {
  position: fixed;
  z-index: 120;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: #101722b8;
  backdrop-filter: blur(3px);
}
.download-options {
  width: min(100%, 430px);
  padding: 25px;
  border-radius: 16px;
  background: #fff;
  color: #202630;
  box-shadow: 0 24px 70px #00000040;
}
.dialog-mark {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  margin-bottom: 14px;
  border-radius: 12px;
  background: #eaf1ff;
  color: #2863db;
  font-size: 24px;
  font-weight: 700;
}
h2 {
  margin: 0;
  font-size: 19px;
}
h2 + p {
  margin: 7px 0 18px;
  color: #7b8490;
  font-size: 12px;
  line-height: 19px;
}
.watermark-choice {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 14px;
  border: 1px solid #dce4f2;
  border-radius: 10px;
  background: #f8faff;
  cursor: pointer;
}
.watermark-choice input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  opacity: 0;
}
.check-box {
  width: 21px;
  height: 21px;
  flex: none;
  display: grid;
  place-items: center;
  margin-top: 1px;
  border: 1.5px solid #aab6c8;
  border-radius: 4px;
  background: #fff;
  color: transparent;
  font-size: 15px;
  font-weight: 800;
}
.watermark-choice input:checked + .check-box {
  border-color: #3370ff;
  background: #3370ff;
  color: #fff;
}
.watermark-choice input:focus-visible + .check-box {
  outline: 3px solid #3370ff33;
  outline-offset: 2px;
}
.watermark-choice b,
.watermark-choice small {
  display: block;
}
.watermark-choice b {
  font-size: 14px;
}
.watermark-choice small {
  margin-top: 4px;
  color: #7d8794;
  font-size: 11px;
  line-height: 17px;
}
.choice-warning,
.choice-note {
  margin: 11px 1px 0;
  padding: 9px 10px;
  border-radius: 7px;
  font-size: 11px;
  line-height: 17px;
}
.choice-warning {
  background: #fff3e8;
  color: #a55712;
}
.choice-note {
  background: #eef7f1;
  color: #24794a;
}
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 9px;
  margin-top: 20px;
}
.dialog-actions button {
  min-width: 78px;
  padding: 10px 16px;
  border: 0;
  border-radius: 8px;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.dialog-actions .secondary {
  background: #eef1f5;
  color: #56606d;
}
.dialog-actions .primary {
  background: #3370ff;
  color: #fff;
  font-weight: 600;
}
.dialog-actions .primary:disabled {
  background: #b9c8e5;
  cursor: not-allowed;
}
</style>
