/**
 * EditorCanvas – 截图显示 + 左键框选 + 绿色 locate 框
 *
 * 左键拖拽：框选，触发 selection-change
 * 右键单击：canvas-remote-click { x, y }
 * 右键拖拽：canvas-remote-swipe { x1, y1, x2, y2 }
 *
 * Emits:
 *   selection-change({left, top, right, bottom})
 *   canvas-remote-click({ x, y })
 *   canvas-remote-swipe({ x1, y1, x2, y2 })
 */
const EditorCanvas = {
  name: 'EditorCanvas',
  props: {
    imageSrc: { type: String, default: '' },
    selection: { type: Object, default: null },
    locateBoxes: { type: Array, default: () => [] },
    imgWidth: { type: Number, default: 1280 },
    imgHeight: { type: Number, default: 720 },
  },
  emits: ['selection-change', 'canvas-remote-click', 'canvas-remote-swipe'],
  template: `
<div ref="wrapper" class="editor-canvas-wrapper w-full h-full" @contextmenu.prevent>
  <canvas ref="canvas"
    @mousedown="onMouseDown" @mousemove="onMouseMove" @mouseup="onMouseUp"
    @mouseleave="onMouseLeave"
    :style="{ cursor: 'crosshair', display: 'block', width: canvasStyleW + 'px', height: canvasStyleH + 'px', margin: '0 auto' }">
  </canvas>
</div>`,
  setup(props, { emit }) {
    const { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } = Vue;

    const wrapper = ref(null);
    const canvas = ref(null);
    const containerW = ref(1280);
    const containerH = ref(600);

    const scale = computed(() => {
      const fitW = containerW.value / props.imgWidth;
      const fitH = containerH.value / props.imgHeight;
      return Math.min(fitW, fitH);
    });
    const canvasStyleW = computed(() => Math.floor(props.imgWidth * scale.value));
    const canvasStyleH = computed(() => Math.floor(props.imgHeight * scale.value));

    let imgEl = null;
    let drawing = false;
    let startX = 0, startY = 0;
    let curX = 0, curY = 0;

    const rmbDrawing = ref(false);
    let rStartX = 0, rStartY = 0, rCurX = 0, rCurY = 0;
    let ro = null;

    function toReal(px, py) {
      const rect = canvas.value.getBoundingClientRect();
      const s = 1 / scale.value;
      return [Math.round((px - rect.left) * s), Math.round((py - rect.top) * s)];
    }

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    function redraw() {
      const c = canvas.value;
      if (!c) return;
      const ctx = c.getContext('2d');
      const dpr = window.devicePixelRatio || 1;
      const sw = canvasStyleW.value;
      const sh = canvasStyleH.value;
      c.width = sw * dpr;
      c.height = sh * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      if (imgEl && imgEl.complete && imgEl.naturalWidth) {
        ctx.drawImage(imgEl, 0, 0, sw, sh);
      } else {
        ctx.fillStyle = '#1e293b';
        ctx.fillRect(0, 0, sw, sh);
        ctx.fillStyle = '#94a3b8';
        ctx.font = '16px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('点击「刷新截图」获取画面', sw / 2, sh / 2);
      }

      const s = scale.value;

      if (props.locateBoxes.length) {
        ctx.strokeStyle = '#00cc00';
        ctx.lineWidth = 2;
        for (const b of props.locateBoxes) {
          ctx.strokeRect(b.left * s, b.top * s, b.width * s, b.height * s);
        }
      }

      const sel = drawing
        ? { left: Math.min(startX, curX), top: Math.min(startY, curY),
            right: Math.max(startX, curX), bottom: Math.max(startY, curY) }
        : props.selection;
      if (sel && sel.right > sel.left && sel.bottom > sel.top) {
        ctx.strokeStyle = '#ff3333';
        ctx.lineWidth = 2;
        ctx.strokeRect(sel.left * s, sel.top * s, (sel.right - sel.left) * s, (sel.bottom - sel.top) * s);
      }

      if (rmbDrawing.value) {
        ctx.strokeStyle = '#3b82f6';
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        ctx.moveTo(rStartX * s, rStartY * s);
        ctx.lineTo(rCurX * s, rCurY * s);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    function onMouseDown(e) {
      if (e.button === 2) {
        e.preventDefault();
        rmbDrawing.value = true;
        [rStartX, rStartY] = toReal(e.clientX, e.clientY);
        rStartX = clamp(rStartX, 0, props.imgWidth);
        rStartY = clamp(rStartY, 0, props.imgHeight);
        rCurX = rStartX;
        rCurY = rStartY;
        redraw();
        return;
      }
      if (e.button !== 0) return;
      drawing = true;
      [startX, startY] = toReal(e.clientX, e.clientY);
      startX = clamp(startX, 0, props.imgWidth);
      startY = clamp(startY, 0, props.imgHeight);
      curX = startX; curY = startY;
    }

    function onMouseMove(e) {
      if (rmbDrawing.value) {
        [rCurX, rCurY] = toReal(e.clientX, e.clientY);
        rCurX = clamp(rCurX, 0, props.imgWidth);
        rCurY = clamp(rCurY, 0, props.imgHeight);
        redraw();
        return;
      }
      if (!drawing) return;
      [curX, curY] = toReal(e.clientX, e.clientY);
      curX = clamp(curX, 0, props.imgWidth);
      curY = clamp(curY, 0, props.imgHeight);
      redraw();
    }

    function onMouseUp(e) {
      if (e.button === 2) {
        if (!rmbDrawing.value) return;
        rmbDrawing.value = false;
        let [ex, ey] = toReal(e.clientX, e.clientY);
        ex = clamp(ex, 0, props.imgWidth);
        ey = clamp(ey, 0, props.imgHeight);
        const dist = Math.hypot(ex - rStartX, ey - rStartY);
        if (dist < 6) {
          emit('canvas-remote-click', { x: rStartX, y: rStartY });
        } else {
          emit('canvas-remote-swipe', { x1: rStartX, y1: rStartY, x2: ex, y2: ey });
        }
        redraw();
        return;
      }
      if (e.button !== 0) return;
      if (!drawing) return;
      drawing = false;
      [curX, curY] = toReal(e.clientX, e.clientY);
      curX = clamp(curX, 0, props.imgWidth);
      curY = clamp(curY, 0, props.imgHeight);
      const left = Math.min(startX, curX), top = Math.min(startY, curY);
      const right = Math.max(startX, curX), bottom = Math.max(startY, curY);
      if (right - left > 2 && bottom - top > 2) {
        emit('selection-change', { left, top, right, bottom });
      }
      redraw();
    }

    function onMouseLeave(e) {
      if (rmbDrawing.value) {
        rmbDrawing.value = false;
        redraw();
      }
      if (!drawing) return;
      drawing = false;
      [curX, curY] = toReal(e.clientX, e.clientY);
      curX = clamp(curX, 0, props.imgWidth);
      curY = clamp(curY, 0, props.imgHeight);
      const left = Math.min(startX, curX), top = Math.min(startY, curY);
      const right = Math.max(startX, curX), bottom = Math.max(startY, curY);
      if (right - left > 2 && bottom - top > 2) {
        emit('selection-change', { left, top, right, bottom });
      }
      redraw();
    }

    function loadImage(src) {
      if (!src) { imgEl = null; redraw(); return; }
      const img = new Image();
      img.onload = () => { imgEl = img; redraw(); };
      img.src = src;
    }

    watch(() => props.imageSrc, (v) => loadImage(v));
    watch(() => props.selection, () => { if (!drawing) redraw(); }, { deep: true });
    watch(() => props.locateBoxes, () => redraw(), { deep: true });
    watch(canvasStyleW, () => nextTick(redraw));
    watch(canvasStyleH, () => nextTick(redraw));

    onMounted(() => {
      ro = new ResizeObserver(entries => {
        for (const e of entries) {
          containerW.value = e.contentRect.width || 1280;
          containerH.value = e.contentRect.height || 600;
        }
      });
      ro.observe(wrapper.value);
      if (props.imageSrc) loadImage(props.imageSrc);
      else redraw();
    });

    onBeforeUnmount(() => { if (ro) ro.disconnect(); });

    return {
      wrapper, canvas, canvasStyleW, canvasStyleH,
      onMouseDown, onMouseMove, onMouseUp, onMouseLeave,
    };
  },
};
