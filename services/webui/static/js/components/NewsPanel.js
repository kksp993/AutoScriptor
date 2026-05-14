const NewsPanel = {
  name: 'NewsPanel',
  data() {
    return {
      posts: [],
      /** 服务端是否可用「安全解锁 + 游戏账密」走通行证代拉论坛（见 GET /api/news/posts → bbs_session_eligible） */
      bbsSessionEligible: false,
      loading: true,
      error: '',
      dialogVisible: false,
      dialogTitle: '',
      iframeSrc: '',
      /** 当前弹窗对应的帖子（用于展示与列表一致的简介正文） */
      dialogPost: null,
      giftDialogVisible: false,
      giftLoading: false,
      giftRows: [],
      giftUpdatedAt: '',
      giftFetchError: '',
    };
  },
  computed: {
    featuredPost() {
      return this.posts.find(p => p.thumbnail) || this.posts[0] || null;
    },
    listPosts() {
      const feat = this.featuredPost;
      const others = feat
        ? this.posts.filter(p => p.post_id !== feat.post_id)
        : this.posts;
      return others.slice(0, 5);
    },
  },
  mounted() {
    // 打开 WebUI / 模拟器时强制拉取最新资讯（绕过服务端缓存）
    this.fetchPosts(true);
  },
  methods: {
    async fetchPosts(force = false) {
      this.loading = true;
      this.error = '';
      try {
        const qs = force ? '?force=1' : '';
        const res = await fetch('/api/news/posts' + qs, { credentials: 'same-origin' });
        const data = await res.json();
        this.bbsSessionEligible = !!data.bbs_session_eligible;
        if (data.error) {
          this.error = data.error;
          this.posts = data.posts || [];
        } else {
          this.posts = data.posts || [];
        }
      } catch (e) {
        this.error = '加载失败: ' + e.message;
      } finally {
        this.loading = false;
      }
    },
    openPost(post) {
      this.dialogPost = post;
      this.dialogTitle = post.title;
      this.iframeSrc = '/api/news/proxy?url=' + encodeURIComponent(post.url);
      this.dialogVisible = true;
    },
    onNewsDialogClosed() {
      this.dialogPost = null;
      this.iframeSrc = '';
    },
    openForum() {
      window.open('https://bbs.4399.cn/forums-kind-id-1493-order-dl', '_blank');
    },
    formatDate(dateStr) {
      if (!dateStr) return '';
      const parts = dateStr.split('-');
      if (parts.length === 3) {
        return parseInt(parts[1]) + '月' + parseInt(parts[2]) + '日';
      }
      return dateStr;
    },
    openGiftCodes() {
      this.giftDialogVisible = true;
      this.fetchGiftCodes();
    },
    async fetchGiftCodes() {
      this.giftLoading = true;
      this.giftFetchError = '';
      try {
        const res = await fetch('/api/news/gift_codes?refresh=1', { credentials: 'same-origin' });
        const data = await res.json();
        this.giftUpdatedAt = data.generated_at || '';
        this.giftRows = data.rows || [];
      } catch (e) {
        this.giftFetchError = '同步失败，请稍后点击重试或检查网络。' + e.message;
        this.giftRows = [];
        this.giftUpdatedAt = '';
      } finally {
        this.giftLoading = false;
      }
    },
    onGiftDialogClosed() {
      this.giftRows = [];
      this.giftUpdatedAt = '';
      this.giftFetchError = '';
    },
    async copyGiftCode(code) {
      if (!code) return;
      try {
        await navigator.clipboard.writeText(code);
        ElementPlus.ElMessage.success('已复制');
      } catch (e) {
        ElementPlus.ElMessage.error('复制失败');
      }
    },
  },
  template: `
<div class="news-panel h-full flex flex-col overflow-hidden">

  <!-- 造笔大字介绍（置顶） -->
  <section class="news-intro flex-shrink-0" aria-label="造笔介绍">
    <div class="news-intro-inner">
      <div class="news-intro-brand">
        <span class="news-intro-cn">造笔</span>
        <span class="news-intro-en">AutoScriptor</span>
      </div>
      <p class="news-intro-lead">
        面向《造梦西游 OL》等游戏的自动化脚本与调度工具，集成任务编排、模拟器控制与 Web 控制台，让日常与周常更省心。
      </p>
      <p class="news-intro-hint">
        <i class="fa fa-info-circle"></i> 下方同步 4399 官方公告区最近两周内容，点击条目可在窗口内阅读原文。
      </p>
    </div>
  </section>

  <!-- 游戏资讯区（在介绍下方） -->
  <div class="news-panel-body flex flex-col flex-1 min-h-0 overflow-hidden">

  <!-- 头部 -->
  <div class="flex items-center justify-between mb-3 flex-shrink-0">
    <div class="flex items-center gap-2">
      <h2 class="text-lg font-semibold text-gray-800">
        <i class="fa fa-newspaper-o text-primary mr-1"></i>游戏资讯
      </h2>
      <span class="text-xs text-gray-400">造梦西游OL · 官方公告</span>
      <span v-if="bbsSessionEligible" class="text-xs text-emerald-600" title="已验证安全密码且配置中有游戏账密时，内嵌原文将尝试经通行证登录后拉取">
        <i class="fa fa-unlock-alt"></i> 通行证代拉已就绪
      </span>
    </div>
    <div class="flex items-center gap-2">
      <el-button size="small" type="success" plain @click="openGiftCodes">
        <i class="fa fa-gift mr-1"></i>兑换码
      </el-button>
      <el-button size="small" :icon="''" :loading="loading" @click="fetchPosts(true)">
        <i class="fa fa-refresh" v-if="!loading"></i>
        刷新资讯
      </el-button>
      <el-button size="small" type="primary" @click="openForum">
        更多 <i class="fa fa-external-link ml-1"></i>
      </el-button>
    </div>
  </div>

  <!-- 加载状态 -->
  <div v-if="loading && !posts.length" class="flex-1 flex items-center justify-center">
    <div class="text-center text-gray-400">
      <i class="fa fa-spinner fa-spin text-2xl mb-2"></i>
      <p>正在加载资讯...</p>
    </div>
  </div>

  <!-- 错误状态 -->
  <div v-else-if="error && !posts.length" class="flex-1 flex items-center justify-center">
    <div class="text-center">
      <i class="fa fa-exclamation-circle text-2xl text-amber-400 mb-2"></i>
      <p class="text-gray-500 mb-3">{{ error }}</p>
      <el-button size="small" @click="fetchPosts(true)">重试</el-button>
    </div>
  </div>

  <!-- 空状态 -->
  <div v-else-if="!posts.length" class="flex-1 flex items-center justify-center">
    <div class="text-center text-gray-400">
      <i class="fa fa-inbox text-3xl mb-2"></i>
      <p>暂无最近两周的资讯</p>
      <el-button size="small" class="mt-3" @click="openForum">前往论坛查看</el-button>
    </div>
  </div>

  <!-- 内容区：等高两列，无内部滚动条 -->
  <div v-else class="news-layout-outer flex-1 flex flex-col min-h-0 overflow-hidden">
    <div class="news-layout">

      <!-- 左侧：精选配图 -->
      <div class="news-featured" v-if="featuredPost" @click="openPost(featuredPost)">
        <div class="news-featured-img">
          <img v-if="featuredPost.thumbnail"
               :src="featuredPost.thumbnail"
               :alt="featuredPost.title"
               @error="$event.target.style.display='none'" />
          <div v-else class="news-featured-placeholder">
            <i class="fa fa-image text-4xl text-gray-300"></i>
          </div>
          <div class="news-featured-overlay">
            <span class="news-featured-tag">
              <i class="fa fa-bullhorn"></i> 最新
            </span>
          </div>
        </div>
        <div class="news-featured-info">
          <h3 class="news-featured-title">{{ featuredPost.title }}</h3>
          <p class="news-featured-summary">{{ featuredPost.summary }}</p>
          <div class="news-featured-meta">
            <span><i class="fa fa-user-o"></i> {{ featuredPost.author }}</span>
            <span><i class="fa fa-calendar-o"></i> {{ formatDate(featuredPost.date) }}</span>
          </div>
        </div>
      </div>

      <!-- 右侧：帖子列表 -->
      <div class="news-list">
        <div v-for="(post, idx) in listPosts" :key="post.post_id"
             class="news-list-item" @click="openPost(post)">
          <div class="news-list-idx">{{ idx + 1 }}</div>
          <div class="news-list-content">
            <div class="news-list-title" :title="post.title">{{ post.title }}</div>
            <div class="news-list-summary">{{ post.summary }}</div>
            <div class="news-list-meta">
              <span>{{ post.author }}</span>
              <span>{{ formatDate(post.date) }}</span>
            </div>
          </div>
          <img v-if="post.thumbnail" :src="post.thumbnail" class="news-list-thumb"
               @error="$event.target.style.display='none'" />
        </div>

        <div v-if="!listPosts.length" class="text-center text-gray-400 py-8">
          暂无更多帖子
        </div>
      </div>

    </div>
  </div>

  </div><!-- /.news-panel-body -->

  <teleport to="body">
    <el-dialog v-model="giftDialogVisible"
               title="兑换码"
               width="92%"
               top="4vh"
               destroy-on-close
               class="news-dialog news-gift-dialog"
               @closed="onGiftDialogClosed">
      <div class="text-xs text-slate-500 mb-2">
        <p>
          更新时间：<span class="text-slate-700 font-medium">{{ giftLoading ? '同步中…' : (giftUpdatedAt || '—') }}</span>
          <span v-if="giftLoading" class="text-slate-400 ml-2">正在从论坛拉取未过期口令，可能需要数十秒。</span>
        </p>
      </div>
      <div class="rounded-lg border border-gray-200 bg-white overflow-auto" style="max-height:min(72vh,640px);min-height:200px;">
        <table class="w-full text-sm border-collapse">
          <thead class="sticky top-0 z-10">
            <tr class="bg-slate-100 text-slate-600 text-left border-b border-slate-200">
              <th class="px-3 py-2.5 font-semibold">标题</th>
              <th class="px-3 py-2.5 font-semibold">口令</th>
              <th class="px-3 py-2.5 font-semibold">到期时间</th>
              <th class="px-3 py-2.5 font-semibold w-[88px]">复制</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="giftLoading">
              <td colspan="4" class="px-3 py-12 text-center text-slate-400">
                <i class="fa fa-spinner fa-spin text-lg mr-2"></i>正在同步兑换码数据…
              </td>
            </tr>
            <tr v-else-if="giftFetchError">
              <td colspan="4" class="px-3 py-12 text-center text-amber-800">
                <p class="mb-2">{{ giftFetchError }}</p>
                <el-button size="small" type="primary" @click="fetchGiftCodes">重试</el-button>
              </td>
            </tr>
            <template v-else>
              <tr v-for="(r, i) in giftRows" :key="i" class="border-b border-slate-100 align-top hover:bg-slate-50/80">
                <td class="px-3 py-2">
                  <a v-if="r.url" :href="r.url" target="_blank" rel="noopener noreferrer"
                     class="text-primary hover:underline">{{ r.title }}</a>
                  <span v-else>{{ r.title }}</span>
                </td>
                <td class="px-3 py-2 font-mono text-xs break-all text-slate-800">{{ r.code }}</td>
                <td class="px-3 py-2 text-slate-600">{{ r.expires_at }}</td>
                <td class="px-3 py-2">
                  <el-button size="small" type="success" @click="copyGiftCode(r.code)">复制</el-button>
                </td>
              </tr>
              <tr v-if="!giftRows.length">
                <td colspan="4" class="px-3 py-12 text-center text-slate-400">暂无更多兑换码</td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </el-dialog>
  </teleport>

  <!-- iframe 对话框 -->
  <teleport to="body">
    <el-dialog v-model="dialogVisible"
               :title="dialogTitle"
               width="90%"
               top="3vh"
               destroy-on-close
               class="news-dialog"
               @closed="onNewsDialogClosed">
      <div v-if="dialogPost" class="news-dialog-body">
        <section class="news-dialog-lead" aria-label="公告摘要">
          <p class="news-dialog-summary">{{ dialogPost.summary }}</p>
          <div class="news-dialog-lead-foot">
            <span class="news-dialog-meta">
              <i class="fa fa-user-o"></i> {{ dialogPost.author }}
              <span class="news-dialog-meta-sep">·</span>
              <i class="fa fa-calendar-o"></i> {{ formatDate(dialogPost.date) }}
            </span>
            <a class="news-dialog-open-original"
               :href="dialogPost.url"
               target="_blank"
               rel="noopener noreferrer">
              论坛原文 <i class="fa fa-external-link"></i>
            </a>
          </div>
        </section>
        <p class="news-dialog-iframe-hint text-xs text-gray-400">
          下方为论坛页内嵌预览；若站点要求登录，会显示说明页，请使用「论坛原文」在浏览器中阅读全文。
        </p>
        <div class="news-iframe-wrap">
          <iframe v-if="dialogVisible && iframeSrc"
                  :src="iframeSrc"
                  frameborder="0"
                  title="论坛页面"
                  style="width:100%;height:min(52vh,560px);min-height:280px;border:none;border-radius:6px;"></iframe>
        </div>
      </div>
    </el-dialog>
  </teleport>

</div>`,
};
