/**
 * 错误汇总：左侧按日期归档列表，右侧摘要 + 控制台风格日志，可点开截图预览（复制 / 前往标注 / 关闭）。
 */
const ErrorArchivesPanel = {
  name: 'ErrorArchivesPanel',
  emits: ['go-to-editor-with-image'],
  data() {
    return {
      loading: false,
      items: [],
      groups: {},
      activeFolder: '',
      detail: null,
      detailLoading: false,
      checked: {},
      lastCheckedFolder: '',
      previewVisible: false,
      previewPath: '',
      previewTitle: '',
      importLoading: false,
      fileInputKey: 0,
      videoCollapsed: false,
    };
  },
  computed: {
    dateKeys() {
      const k = Object.keys(this.groups || {});
      return k.sort((a, b) => {
        if (a === '未知日期') return 1;
        if (b === '未知日期') return -1;
        return b.localeCompare(a);
      });
    },
    previewUrl() {
      if (!this.activeFolder || !this.previewPath) return '';
      const q = new URLSearchParams({
        folder: this.activeFolder,
        path: this.previewPath,
      });
      return `/api/error-archives/file?${q.toString()}`;
    },
    hasSelection() {
      return Object.keys(this.checked).some((k) => this.checked[k]);
    },
    flatArchiveFolders() {
      const folders = [];
      for (const dk of this.dateKeys) {
        for (const it of this.groups[dk] || []) {
          folders.push(it.folder);
        }
      }
      return folders;
    },
  },
  mounted() {
    this.refreshList();
  },
  methods: {
    async refreshList() {
      this.loading = true;
      try {
        const r = await fetch('/api/error-archives');
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || '加载失败');
        this.items = d.items || [];
        this.groups = d.groups || {};
        const validFolders = new Set(this.items.map((x) => x.folder));
        this.checked = Object.fromEntries(
          Object.entries(this.checked).filter(([folder, on]) => on && validFolders.has(folder)),
        );
        if (this.lastCheckedFolder && !validFolders.has(this.lastCheckedFolder)) {
          this.lastCheckedFolder = '';
        }
        if (this.activeFolder && !this.items.some((x) => x.folder === this.activeFolder)) {
          this.activeFolder = '';
          this.detail = null;
        }
        if (!this.activeFolder && this.items.length) {
          this.selectArchive(this.items[0].folder);
        }
      } catch (e) {
        ElementPlus.ElMessage.error(String(e.message || e));
      } finally {
        this.loading = false;
      }
    },
    async selectArchive(folder) {
      this.activeFolder = folder;
      this.detail = null;
      this.videoCollapsed = false;
      if (!folder) return;
      this.detailLoading = true;
      try {
        const q = new URLSearchParams({ folder });
        const r = await fetch(`/api/error-archives/detail?${q}`);
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || '读取失败');
        this.detail = d;
      } catch (e) {
        ElementPlus.ElMessage.error(String(e.message || e));
      } finally {
        this.detailLoading = false;
      }
    },
    setChecked(folder, ev) {
      const on = !!ev.target.checked;
      const next = { ...this.checked, [folder]: on };
      if (ev.shiftKey && this.lastCheckedFolder && this.lastCheckedFolder !== folder) {
        const folders = this.flatArchiveFolders;
        const start = folders.indexOf(this.lastCheckedFolder);
        const end = folders.indexOf(folder);
        if (start >= 0 && end >= 0) {
          const [lo, hi] = start < end ? [start, end] : [end, start];
          for (const f of folders.slice(lo, hi + 1)) {
            next[f] = on;
          }
        }
      }
      this.checked = next;
      this.lastCheckedFolder = folder;
    },
    async deleteSelected() {
      const folders = Object.keys(this.checked).filter((k) => this.checked[k]);
      if (!folders.length) return;
      try {
        await ElementPlus.ElMessageBox.confirm(
          `确定删除 ${folders.length} 条归档？此操作不可恢复。`,
          '删除确认',
          { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
        );
      } catch (_) {
        return;
      }
      try {
        const r = await fetch('/api/error-archives', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ folders }),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || '删除失败');
        if (d.errors && d.errors.length) {
          ElementPlus.ElMessage.warning(`部分未删除: ${d.errors.join(', ')}`);
        } else {
          ElementPlus.ElMessage.success(`已删除 ${d.removed || 0} 条`);
        }
        this.checked = {};
        if (folders.includes(this.activeFolder)) {
          this.activeFolder = '';
          this.detail = null;
        }
        await this.refreshList();
      } catch (e) {
        ElementPlus.ElMessage.error(String(e.message || e));
      }
    },
    triggerImport() {
      this.$refs.zipInput && this.$refs.zipInput.click();
    },
    async onImportZip(ev) {
      const file = ev.target.files && ev.target.files[0];
      this.fileInputKey += 1;
      if (!file) return;
      if (!file.name.toLowerCase().endsWith('.zip')) {
        ElementPlus.ElMessage.warning('请选择 .zip 文件');
        return;
      }
      this.importLoading = true;
      try {
        const fd = new FormData();
        fd.append('file', file);
        const r = await fetch('/api/error-archives/import', { method: 'POST', body: fd });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || '导入失败');
        ElementPlus.ElMessage.success('导入成功');
        await this.refreshList();
        if (d.folder) this.selectArchive(d.folder);
      } catch (e) {
        ElementPlus.ElMessage.error(String(e.message || e));
      } finally {
        this.importLoading = false;
      }
    },
    shortName(path) {
      const p = path.split('/').pop() || path;
      return p.length > 28 ? p.slice(0, 14) + '…' + p.slice(-10) : p;
    },
    openPreview(relPath) {
      this.previewPath = relPath;
      this.previewTitle = relPath.split('/').pop() || relPath;
      this.previewVisible = true;
    },
    closePreview() {
      this.previewVisible = false;
      this.previewPath = '';
    },
    async copyPreview() {
      if (!this.previewUrl) return;
      try {
        const r = await fetch(this.previewUrl);
        const blob = await r.blob();
        if (navigator.clipboard && window.ClipboardItem) {
          await navigator.clipboard.write([
            new ClipboardItem({ [blob.type || 'image/png']: blob }),
          ]);
          ElementPlus.ElMessage.success('图片已复制到剪贴板');
        } else {
          throw new Error('浏览器不支持图片剪贴板');
        }
      } catch (e) {
        ElementPlus.ElMessage.error(String(e.message || e));
      }
    },
    goToAnnotate() {
      if (!this.previewUrl) return;
      this.$emit('go-to-editor-with-image', this.previewUrl);
      this.closePreview();
    },
    imgSrc(relPath) {
      if (!this.activeFolder || !relPath) return '';
      const q = new URLSearchParams({ folder: this.activeFolder, path: relPath });
      return `/api/error-archives/file?${q.toString()}`;
    },
    videoSrc(relPath) {
      return this.imgSrc(relPath);
    },
    hasSegments(detail) {
      return detail && Array.isArray(detail.segments) && detail.segments.length > 0;
    },
  },
  template: `
<div class="flex flex-col lg:flex-row gap-4 h-full min-h-0 error-archives-root">
  <!-- 左侧 1/3 -->
  <div class="lg:w-1/3 flex flex-col min-h-0 rounded-2xl shadow-lg overflow-hidden border border-slate-200/80 bg-gradient-to-b from-slate-50 to-white">
    <div class="px-4 py-3 border-b border-slate-200/90 bg-white/90 backdrop-blur flex flex-wrap items-center gap-2 shrink-0">
      <h2 class="text-base font-semibold text-slate-800 tracking-tight mr-auto">
        <i class="fa fa-archive text-amber-500 mr-1.5"></i>错误归档
      </h2>
      <el-button size="small" :loading="loading" @click="refreshList">
        <i class="fa fa-refresh mr-1"></i>刷新
      </el-button>
      <el-button size="small" type="primary" plain :loading="importLoading" @click="triggerImport">
        <i class="fa fa-file-archive-o mr-1"></i>导入 zip
      </el-button>
      <input :key="fileInputKey" ref="zipInput" type="file" accept=".zip" class="hidden" @change="onImportZip" />
      <el-button size="small" type="danger" plain :disabled="!hasSelection" @click="deleteSelected">
        <i class="fa fa-trash-o mr-1"></i>删除
      </el-button>
    </div>
    <div class="flex-1 overflow-y-auto min-h-0 p-3 space-y-4">
      <template v-if="!items.length && !loading">
        <div class="text-center text-slate-400 text-sm py-16">
          <i class="fa fa-inbox text-4xl mb-3 opacity-40"></i>
          <p>暂无归档。任务失败时会自动写入 <code class="text-xs bg-slate-100 px-1 rounded">logs/errors</code></p>
          <p class="mt-2 text-xs">也可导入他人导出的 zip 预览</p>
        </div>
      </template>
      <template v-else>
        <section v-for="dk in dateKeys" :key="dk" class="error-archives-date-block">
          <div class="sticky top-0 z-10 flex items-center gap-2 mb-2 px-1">
            <span class="text-xs font-bold uppercase tracking-wider text-slate-500">{{ dk }}</span>
            <span class="h-px flex-1 bg-slate-200"></span>
          </div>
          <ul class="space-y-1.5">
            <li v-for="it in groups[dk]" :key="it.folder"
                class="group rounded-xl border transition-all cursor-pointer px-3 py-2.5 flex items-start gap-2"
                :class="activeFolder === it.folder
                  ? 'border-primary/50 bg-primary/5 shadow-sm'
                  : 'border-transparent bg-white/60 hover:border-slate-200 hover:bg-white' "
                @click="selectArchive(it.folder)">
              <input type="checkbox"
                class="mt-1.5 h-4 w-4 shrink-0 rounded border-slate-300 text-primary focus:ring-primary"
                :checked="!!checked[it.folder]"
                @click.stop="setChecked(it.folder, $event)" />
              <div class="min-w-0 flex-1">
                <div class="flex items-baseline justify-between gap-2">
                  <span class="text-sm font-medium text-slate-800 truncate" :title="it.taskName">{{ it.taskName }}</span>
                  <span class="text-xs text-slate-400 tabular-nums shrink-0">{{ it.timeLabel }}</span>
                </div>
                <div class="text-[11px] text-slate-400 font-mono truncate mt-0.5" :title="it.folder">{{ it.folder }}</div>
              </div>
            </li>
          </ul>
        </section>
      </template>
    </div>
  </div>

  <!-- 右侧 2/3 -->
  <div class="lg:w-2/3 flex flex-col min-h-0 rounded-2xl shadow-lg overflow-hidden border border-emerald-100/90 bg-white ring-1 ring-emerald-50/80">
    <template v-if="!activeFolder">
      <div class="flex-1 flex items-center justify-center text-slate-400 text-sm">请选择左侧归档</div>
    </template>
    <template v-else>
      <div class="shrink-0 px-5 py-4 border-b border-emerald-200/50 bg-[#f1faf5]">
        <div class="text-xs text-slate-900 mb-1 font-medium tracking-wide">核心原因（摘要）</div>
        <div v-if="detailLoading" class="h-6 w-2/3 bg-emerald-200/35 rounded-md animate-pulse"></div>
        <p v-else class="text-base leading-relaxed font-medium tracking-wide text-slate-900">{{ (detail && detail.summary) || '—' }}</p>
      </div>
      <div class="flex-1 flex flex-col min-h-0 p-4">
        <div v-if="detail && detail.videos && detail.videos.length" class="mb-3 rounded-xl border border-emerald-200/60 bg-[#f1faf5] p-3 shrink-0">
          <div class="flex items-center justify-between gap-2 mb-2">
            <div class="text-sm font-semibold text-slate-900">
              <i class="fa fa-video-camera mr-1.5 text-primary"></i>任务录屏
              <span class="ml-1 text-xs font-normal text-slate-500">{{ detail.videos.length }} 个</span>
            </div>
            <button type="button" class="text-xs text-primary hover:text-primary/80" :aria-expanded="String(!videoCollapsed)" @click="videoCollapsed = !videoCollapsed">
              <i class="fa mr-1" :class="videoCollapsed ? 'fa-chevron-down' : 'fa-chevron-up'"></i>{{ videoCollapsed ? '展开' : '折叠' }}
            </button>
          </div>
          <transition name="expand">
            <div v-if="!videoCollapsed" class="space-y-2">
              <div v-for="video in detail.videos" :key="video" class="space-y-1">
                <div class="text-xs text-slate-500 font-mono">{{ video }}</div>
                <video :src="videoSrc(video)" class="w-full max-h-[360px] rounded bg-black" controls preload="metadata"></video>
              </div>
            </div>
          </transition>
        </div>
        <div class="flex items-center justify-between mb-2 shrink-0">
          <h3 class="text-sm font-semibold text-slate-900">
            <i class="fa fa-file-text-o mr-1.5 text-primary"></i>日志与截图（富文本）
          </h3>
          <span class="text-xs text-slate-500">按日志时间戳与截图文件名时间对齐；点击图片放大</span>
        </div>
        <div v-if="detailLoading" class="flex-1 rounded-xl bg-[#f1faf5] flex items-center justify-center text-slate-500 text-sm border border-emerald-200/40">加载中…</div>
        <div v-else class="flex-1 flex flex-col min-h-0 rounded-xl border border-emerald-200/60 bg-[#f1faf5] text-slate-900 overflow-hidden shadow-sm">
          <div class="shrink-0 flex items-center gap-2 px-3 py-2 border-b border-emerald-200/50 bg-[#e8f5ef] text-xs text-slate-900">
            <i class="fa fa-columns text-primary/80"></i>
            <span>只读富文本区，可选中复制；截图由后端按时间戳插入在对应日志行后</span>
          </div>
          <div
            class="error-archives-rich-body flex-1 min-h-0 overflow-auto px-4 py-3 font-mono text-[13px] leading-relaxed selection:bg-primary/20 select-text outline-none bg-[#f1faf5]"
            contenteditable="false"
            spellcheck="false"
            tabindex="0"
            role="textbox"
            aria-label="错误日志与内联截图"
          >
            <template v-if="hasSegments(detail)">
              <template v-for="(seg, sidx) in detail.segments" :key="'s'+sidx">
                <span v-if="seg.type==='text'" class="whitespace-pre-wrap text-slate-900 block">{{ seg.text }}</span>
                <figure v-else-if="seg.type==='image'"
                  class="my-3 mx-0 rounded-lg border border-emerald-200/80 bg-white overflow-hidden max-w-full block shadow-sm"
                  :class="seg.unmatched ? 'ring-1 ring-amber-300/80' : ''">
                  <div class="flex items-center justify-between gap-2 px-2.5 py-1.5 bg-[#e8f5ef] text-[11px] text-slate-900 border-b border-emerald-200/50">
                    <span class="truncate font-mono">{{ shortName(seg.path) }}</span>
                    <span v-if="seg.unmatched" class="text-amber-700 shrink-0">未匹配时间</span>
                  </div>
                  <button type="button" class="block w-full p-1 bg-white focus:outline-none focus:ring-2 focus:ring-primary/35" @click="openPreview(seg.path)">
                    <img :src="imgSrc(seg.path)" :alt="seg.path" class="max-w-full max-h-[min(52vh,480px)] w-auto h-auto object-contain mx-auto cursor-zoom-in" loading="lazy" />
                  </button>
                </figure>
              </template>
            </template>
            <pre v-else-if="detail && detail.logText" class="whitespace-pre-wrap m-0 text-slate-900">{{ detail.logText }}</pre>
            <div v-else class="text-slate-500">（无 error.log）</div>
          </div>
        </div>
      </div>
    </template>
  </div>

  <el-dialog v-model="previewVisible" width="min(96vw, 1100px)" top="4vh"
    class="error-archives-preview-dialog"
    destroy-on-close @closed="closePreview">
    <template #header>
      <div class="flex items-center gap-3 w-full pr-2">
        <span class="text-sm font-medium text-slate-700 truncate flex-1">{{ previewTitle }}</span>
        <el-button size="small" type="primary" @click="copyPreview">
          <i class="fa fa-clipboard mr-1"></i>复制图片
        </el-button>
        <el-button size="small" type="success" plain @click="goToAnnotate">
          <i class="fa fa-pencil-square-o mr-1"></i>前往标注
        </el-button>
        <el-button size="small" @click="closePreview">
          <i class="fa fa-times mr-1"></i>关闭
        </el-button>
      </div>
    </template>
    <div class="flex justify-center bg-[#f1faf5] rounded-lg p-2 max-h-[78vh] overflow-auto border border-emerald-200/50">
      <img v-if="previewUrl" :src="previewUrl" alt="preview" class="max-w-full h-auto rounded shadow-2xl" />
    </div>
  </el-dialog>
</div>`,
};
