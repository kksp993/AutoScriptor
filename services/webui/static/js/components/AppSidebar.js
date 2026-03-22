const APP_MENU = [
  {
    group: 'CONTROL',
    items: [
      { id: 'overview',  label: '总览',   icon: 'fa-dashboard' },
      { id: 'scheduler', label: '调度',   icon: 'fa-clock-o' },
    ],
  },
  {
    group: 'TASKS',
    items: [
      { id: 'daily',   label: '每日任务', icon: 'fa-sun-o' },
      { id: 'weekly',  label: '每周任务', icon: 'fa-calendar' },
      { id: 'general', label: '一般任务', icon: 'fa-tasks' },
      { id: 'event',   label: '活动任务', icon: 'fa-star' },
    ],
  },
  {
    group: 'TOOLS',
    items: [
      { id: 'editor',   label: '编辑器', icon: 'fa-pencil-square-o' },
      { id: 'settings', label: '设置',   icon: 'fa-cog' },
    ],
  },
];

const SIDEBAR_PARTICLE_COUNT = 48;
const SIDEBAR_CONNECT_DIST = 88;

const AppSidebar = {
  name: 'AppSidebar',
  props: {
    activeTab:       { type: String,  required: true },
    theme:           { type: String,  default: 'light' },
    schedulerStatus: { type: Object,  required: true },
    characterName:   { type: String,  default: '' },
  },
  emits: ['navigate'],
  data() {
    return {
      menu: APP_MENU,
      _particleRaf: null,
      particles: [],
    };
  },
  computed: {
    schedDot() {
      return {
        green:  '#22c55e',
        orange: '#f59e0b',
        red:    '#ef4444',
      }[this.schedulerStatus.color] || '#94a3b8';
    },
    isLight() {
      return this.theme === 'light';
    },
  },
  watch: {
    theme() {
      this.$nextTick(() => this.syncParticles());
    },
  },
  mounted() {
    this.syncParticles();
    window.addEventListener('resize', this.onResize);
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.onResize);
    this.stopParticles();
  },
  methods: {
    onResize() {
      if (this.theme !== 'light') return;
      this.resizeParticleCanvas();
      this.initParticles();
    },
    getParticleCanvas() {
      return this.$refs.particleCanvas;
    },
    resizeParticleCanvas() {
      const cvs = this.getParticleCanvas();
      if (!cvs) return null;
      const panel = cvs.parentElement;
      if (!panel) return null;
      const w = panel.offsetWidth;
      const h = panel.offsetHeight;
      const dpr = window.devicePixelRatio || 1;
      cvs.width = w * dpr;
      cvs.height = h * dpr;
      cvs.style.width = w + 'px';
      cvs.style.height = h + 'px';
      const ctx = cvs.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { ctx, w, h };
    },
    createParticle(w, h) {
      return {
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.35,
        vy: (Math.random() - 0.5) * 0.35,
        r: Math.random() * 2 + 0.45,
        a: Math.random() * 0.32 + 0.1,
      };
    },
    initParticles() {
      const cvs = this.getParticleCanvas();
      if (!cvs) return;
      const w = cvs.width / (window.devicePixelRatio || 1);
      const h = cvs.height / (window.devicePixelRatio || 1);
      this.particles = [];
      for (let i = 0; i < SIDEBAR_PARTICLE_COUNT; i++) {
        this.particles.push(this.createParticle(w, h));
      }
    },
    stopParticles() {
      if (this._particleRaf != null) {
        cancelAnimationFrame(this._particleRaf);
        this._particleRaf = null;
      }
      const cvs = this.getParticleCanvas();
      if (cvs) {
        const ctx = cvs.getContext('2d');
        const w = cvs.width / (window.devicePixelRatio || 1);
        const h = cvs.height / (window.devicePixelRatio || 1);
        ctx.clearRect(0, 0, w, h);
      }
    },
    animateParticles() {
      if (this.theme !== 'light') return;
      const cvs = this.getParticleCanvas();
      if (!cvs) return;
      const dpr = window.devicePixelRatio || 1;
      const w = cvs.width / dpr;
      const h = cvs.height / dpr;
      const ctx = cvs.getContext('2d');
      if (!ctx || w < 8 || h < 8) return;
      if (!this.particles.length) this.initParticles();

      ctx.clearRect(0, 0, w, h);

      const pts = this.particles;
      for (let i = 0; i < pts.length; i++) {
        const a = pts[i];
        for (let j = i + 1; j < pts.length; j++) {
          const b = pts[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d = Math.sqrt(dx * dx + dy * dy);
          if (d < SIDEBAR_CONNECT_DIST) {
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.strokeStyle = 'rgba(22,163,74,' + (0.11 * (1 - d / SIDEBAR_CONNECT_DIST)) + ')';
            ctx.lineWidth = 0.55;
            ctx.stroke();
          }
        }
      }

      for (const p of pts) {
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0 || p.x > w) p.vx *= -1;
        if (p.y < 0 || p.y > h) p.vy *= -1;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(22,163,74,' + p.a + ')';
        ctx.fill();
      }

      this._particleRaf = requestAnimationFrame(() => this.animateParticles());
    },
    syncParticles() {
      this.stopParticles();
      if (this.theme !== 'light') return;
      this.$nextTick(() => {
        this.resizeParticleCanvas();
        this.initParticles();
        this.animateParticles();
      });
    },
  },
  template: `
<aside class="sidebar flex flex-col">
  <canvas
    v-show="isLight"
    ref="particleCanvas"
    class="sidebar-particle-canvas"
    aria-hidden="true"
  ></canvas>
  <div v-show="isLight" class="sidebar-light-overlay" aria-hidden="true"></div>

  <div class="sidebar-inner flex flex-col flex-1 min-h-0">
    <div class="sidebar-logo">
      <i class="fa fa-bolt text-primary text-2xl sidebar-logo-icon"></i>
      <span class="sidebar-brand-text font-bold text-xl tracking-wide ml-2">AutoScriptor</span>
    </div>

    <nav class="flex-1 overflow-y-auto py-2">
      <template v-for="group in menu" :key="group.group">
        <div class="sidebar-group-label">{{ group.group }}</div>
        <a v-for="item in group.items" :key="item.id"
           :class="['sidebar-item', activeTab === item.id ? 'sidebar-item-active' : '']"
           @click="$emit('navigate', item.id)">
          <i :class="['fa', item.icon, 'sidebar-icon']"></i>
          <span>{{ item.label }}</span>
        </a>
      </template>
    </nav>

    <div class="sidebar-footer">
      <div class="flex items-center gap-2 mb-2">
        <span class="sidebar-dot" :style="{ backgroundColor: schedDot }"></span>
        <span class="sidebar-footer-text truncate">{{ schedulerStatus.label || '未知' }}</span>
      </div>
      <div v-if="characterName" class="flex items-center gap-2">
        <i class="fa fa-user sidebar-footer-muted w-4 text-center"></i>
        <span class="sidebar-footer-muted truncate">{{ characterName }}</span>
      </div>
      <div v-else class="flex items-center gap-2">
        <i class="fa fa-lock sidebar-footer-dim w-4 text-center"></i>
        <span class="sidebar-footer-dim">未验证</span>
      </div>
    </div>
  </div>
</aside>`,
};
