<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ChevronDownIcon } from 'tdesign-icons-vue-next'

type Option = { value: string; label: string; disabled?: boolean }

const props = withDefaults(defineProps<{
  modelValue: string
  options: Option[]
  placeholder?: string
  disabled?: boolean
  ariaLabel?: string
}>(), { placeholder: '请选择', disabled: false, ariaLabel: '' })

const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

const selected = computed(() => props.options.find((item) => item.value === props.modelValue))
const displayLabel = computed(() => selected.value?.label ?? props.placeholder)

const toggle = () => { if (!props.disabled) open.value = !open.value }
const close = () => { open.value = false }
const choose = (option: Option) => {
  if (option.disabled) return
  emit('update:modelValue', option.value)
  close()
}

const onDocClick = (event: MouseEvent) => {
  if (root.value && !root.value.contains(event.target as Node)) close()
}
onMounted(() => document.addEventListener('mousedown', onDocClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocClick))
</script>

<template>
  <div ref="root" class="ps-select" :class="{ 'ps-select--open': open, 'ps-select--disabled': disabled }">
    <button
      type="button" class="ps-trigger" :disabled="disabled"
      :aria-label="ariaLabel || placeholder" aria-haspopup="listbox" :aria-expanded="open"
      @click="toggle"
    >
      <span class="ps-value" :class="{ 'ps-placeholder': !selected }">{{ displayLabel }}</span>
      <ChevronDownIcon class="ps-caret" />
    </button>
    <ul v-if="open" class="ps-panel" role="listbox">
      <li
        v-for="option in options" :key="option.value" role="option"
        class="ps-option"
        :class="{ 'ps-option--active': option.value === modelValue, 'ps-option--disabled': option.disabled }"
        :aria-selected="option.value === modelValue"
        @click="choose(option)"
      >{{ option.label }}</li>
      <li v-if="!options.length" class="ps-empty">暂无可选项</li>
    </ul>
  </div>
</template>

<style scoped>
.ps-select { position: relative; width: 100%; min-width: 0; }
.ps-trigger {
  width: 100%; min-height: var(--control-height, 38px); display: flex; align-items: center; gap: 8px;
  padding: 0 10px; border: 1px solid #d6e3df; border-radius: var(--radius-control, 6px);
  background: #fff; color: #24433d; font: inherit; font-size: 12px; cursor: pointer; text-align: left;
}
.ps-trigger:hover { border-color: #91bcb3; }
.ps-select--open .ps-trigger { outline: 2px solid rgba(20, 125, 114, .18); border-color: #147d72; }
.ps-select--disabled .ps-trigger { background: #f2f5f4; color: #8a9995; cursor: not-allowed; }
.ps-value { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ps-placeholder { color: #a0ada9; }
.ps-caret { flex: 0 0 auto; width: 15px; color: #8ca19a; transition: transform .18s ease; }
.ps-select--open .ps-caret { transform: rotate(180deg); }
.ps-panel {
  position: absolute; z-index: 60; top: calc(100% + 4px); left: 0; right: 0; margin: 0; padding: 4px;
  list-style: none; max-height: 240px; overflow: auto; background: #fff; border: 1px solid #d6e3df;
  border-radius: var(--radius-control, 6px); box-shadow: 0 10px 30px rgba(24, 50, 44, .14);
}
.ps-option {
  padding: 8px 9px; border-radius: 4px; color: #34524b; font-size: 12px; cursor: pointer;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ps-option:hover { background: #f1f7f4; }
.ps-option--active { background: #e8f5ef; color: #1f6f60; font-weight: 650; }
.ps-option--disabled { color: #b8c2bf; cursor: not-allowed; }
.ps-option--disabled:hover { background: transparent; }
.ps-empty { padding: 8px 9px; color: #97a39f; font-size: 11px; }
</style>
