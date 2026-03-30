const NewsPanel = {
  name: 'NewsPanel',
  data() {
    return {
      posts: [],
      loading: true,
      error: '',
      dialogVisible: false,
      dialogTitle: '',
      iframeSrc: '',
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
        const res = await fetch('/api/news/posts' + qs);
        const data = await res.json();
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
      this.dialogTitle = post.title;
      this.iframeSrc = '/api/news/proxy?url=' + encodeURIComponent(post.url);
      this.dialogVisible = true;
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
    </div>
    <div class="flex items-center gap-2">
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

  <!-- iframe 对话框 -->
  <teleport to="body">
    <el-dialog v-model="dialogVisible"
               :title="dialogTitle"
               width="90%"
               top="3vh"
               destroy-on-close
               class="news-dialog">
      <div class="news-iframe-wrap">
        <iframe v-if="dialogVisible" :src="iframeSrc" frameborder="0"
                style="width:100%;height:75vh;border:none;border-radius:6px;"></iframe>
      </div>
    </el-dialog>
  </teleport>

</div>`,
};
