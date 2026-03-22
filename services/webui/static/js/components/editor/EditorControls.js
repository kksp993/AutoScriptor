/**
 * EditorControls – 选项开关、阈值滑块、坐标/代码信息面板
 *
 * Props: name, freezeName, freeX, freeY, onlyOcr, lockColor, threshold,
 *        centerText, boxText, tCode, iCode, colorText, nameOk
 * Emits: update:* for each prop, copy(field)
 */
const EditorControls = {
  name: 'EditorControls',
  props: {
    name: { type: String, default: '' },
    freezeName: { type: Boolean, default: false },
    freeX: { type: Boolean, default: false },
    freeY: { type: Boolean, default: false },
    onlyOcr: { type: Boolean, default: false },
    lockColor: { type: Boolean, default: false },
    threshold: { type: Number, default: 100 },
    centerText: { type: String, default: '' },
    boxText: { type: String, default: '' },
    tCode: { type: String, default: '' },
    iCode: { type: String, default: '' },
    colorText: { type: String, default: '' },
    nameOk: { type: Object, default: () => ({}) },
  },
  emits: [
    'update:name', 'update:freezeName', 'update:freeX', 'update:freeY',
    'update:onlyOcr', 'update:lockColor', 'update:threshold',
    'copy', 'threshold-release',
  ],
  template: `
<el-form label-width="122px" label-position="left" class="editor-controls">
  <!-- 名称 -->
  <el-form-item class="editor-controls-name-item mb-6">
    <template #label>
      <span class="text-lg font-medium text-gray-700">名称</span>
    </template>
    <div class="flex items-center gap-3 w-full min-w-0">
      <div class="flex items-center gap-1 shrink-0">
        <span v-for="s in ['0.5', '0.75', '1.0']" :key="s"
              class="inline-flex items-center text-xs font-mono rounded px-1 py-0.5 leading-tight"
              :class="{
                'bg-green-50': nameOk[s] === '√',
                'bg-red-50': nameOk[s] === 'X',
                'bg-gray-100': !nameOk[s] || nameOk[s] === '-'
              }"
              :style="{ color: nameOk[s] === '√' ? '#00aa00' : nameOk[s] === 'X' ? '#e53e3e' : '#a0aec0' }">
          {{ s }}<span class="font-bold ml-0.5">{{ nameOk[s] || '-' }}</span>
        </span>
      </div>
      <el-input class="flex-1 min-w-0" size="large" :model-value="name" @update:model-value="$emit('update:name', $event)"
                placeholder="OCR 识别名" clearable />
    </div>
  </el-form-item>

  <!-- 选项开关 -->
  <div class="flex flex-wrap gap-x-8 gap-y-4 mb-7 pl-0">
    <el-checkbox :model-value="freezeName" @update:model-value="$emit('update:freezeName', $event)">固定名称</el-checkbox>
    <el-checkbox :model-value="freeX" @update:model-value="$emit('update:freeX', $event)">x轴自由</el-checkbox>
    <el-checkbox :model-value="lockColor" @update:model-value="$emit('update:lockColor', $event)">锁定颜色</el-checkbox>
    <el-checkbox :model-value="freeY" @update:model-value="$emit('update:freeY', $event)">y轴自由</el-checkbox>
    <el-checkbox :model-value="onlyOcr" @update:model-value="$emit('update:onlyOcr', $event)">仅OCR</el-checkbox>
  </div>

  <!-- 阈值 -->
  <el-form-item class="mb-7">
    <template #label>
      <span class="text-lg text-gray-700">阈值</span>
    </template>
    <div class="flex items-center gap-3 w-full min-w-0 pt-1">
      <span class="text-base font-medium text-gray-700 tabular-nums w-10 shrink-0 text-right leading-none">{{ threshold }}</span>
      <el-slider class="flex-1 min-w-0" :model-value="threshold" @update:model-value="$emit('update:threshold', $event)"
                 @change="$emit('threshold-release')"
                 :min="0" :max="255" :step="1" />
    </div>
  </el-form-item>

  <!-- 坐标信息 -->
  <div class="space-y-5 mb-2">
    <el-form-item label="中心点" class="mb-0">
      <div class="flex items-center gap-3 w-full min-w-0">
        <el-input class="flex-1 min-w-0" size="large" :model-value="centerText" readonly />
        <el-button size="large" @click="$emit('copy','center')" circle><i class="fa fa-copy"></i></el-button>
      </div>
    </el-form-item>
    <el-form-item label="Box" class="mb-0">
      <div class="flex items-center gap-3 w-full min-w-0">
        <el-input class="flex-1 min-w-0" size="large" :model-value="boxText" readonly />
        <el-button size="large" @click="$emit('copy','box')" circle><i class="fa fa-copy"></i></el-button>
      </div>
    </el-form-item>
    <el-form-item label="颜色" class="mb-0">
      <div class="flex items-center gap-3 w-full min-w-0">
        <el-input class="flex-1 min-w-0" size="large" :model-value="colorText" readonly />
        <el-button size="large" @click="$emit('copy','color')" circle><i class="fa fa-copy"></i></el-button>
      </div>
    </el-form-item>
  </div>

  <!-- 代码输出 -->
  <div class="space-y-5">
    <el-form-item label="T代码" class="mb-0">
      <div class="flex items-center gap-3 w-full min-w-0">
        <el-input class="flex-1 min-w-0" size="large" :model-value="tCode" readonly />
        <el-button size="large" @click="$emit('copy','t')" circle><i class="fa fa-copy"></i></el-button>
      </div>
    </el-form-item>
    <el-form-item label="I代码" class="mb-0">
      <div class="flex items-center gap-3 w-full min-w-0">
        <el-input class="flex-1 min-w-0" size="large" :model-value="iCode" readonly />
        <el-button size="large" @click="$emit('copy','i')" circle><i class="fa fa-copy"></i></el-button>
      </div>
    </el-form-item>
  </div>
</el-form>`,
  setup() {
    return {};
  },
};
