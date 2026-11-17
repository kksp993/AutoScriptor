/** Isolated practice: no editor drafts, API calls, Python execution or persistent state. */
const EditorTutorial = {
  name: 'EditorTutorial',
  components: { EditorCanvas, EditorMenuBar },
  emits: ['close'],
  template: `
<el-dialog :model-value="true" title="编辑器新手教程" class="editor-tutorial-dialog"
  width="min(1120px, calc(100vw - 24px))" top="3vh" append-to-body
  :close-on-click-modal="false" @update:model-value="closeTutorial">
  <div class="editor-tutorial-safety">
    <i class="fa fa-shield" aria-hidden="true"></i>
    <span><strong>放心试，全部是本地演练。</strong>不连接模拟器、不执行 Python、不写入文件，也不改动你的图片和代码。</span>
  </div>
  <div class="editor-tutorial-layout">
    <nav ref="stepsNavigation" class="editor-tutorial-steps" aria-label="教程步骤">
      <p class="editor-tutorial-eyebrow">从一张图到一个脚本</p>
      <button v-for="(item, index) in steps" :key="item.title" type="button"
        :class="{ 'is-current': currentStepIndex === index, 'is-complete': completedSteps.includes(index) }"
        :aria-current="currentStepIndex === index ? 'step' : undefined" @click="goToStep(index)">
        <span class="editor-tutorial-step-number">{{ completedSteps.includes(index) ? '✓' : index + 1 }}</span>
        <span><strong>{{ item.title }}</strong><small>{{ item.subtitle }}</small></span>
      </button>
      <p class="editor-tutorial-progress">已体验 {{ completedSteps.length }} / {{ steps.length }} 步<br>可跳步，随时退出或重新打开。</p>
    </nav>
    <section ref="tutorialContent" class="editor-tutorial-content" :aria-label="step.title">
      <div class="editor-tutorial-heading">
        <span class="editor-tutorial-eyebrow">第 {{ currentStepIndex + 1 }} 步 / {{ steps.length }}</span>
        <h3>{{ step.title }}</h3>
        <p>{{ step.intro }}</p>
        <div class="editor-tutorial-location"><i class="fa fa-map-marker" aria-hidden="true"></i> 页面位置：{{ step.location }}</div>
      </div>
      <div class="editor-tutorial-assignment">
        <span><strong>试试看：</strong>{{ step.task }}</span>
        <div class="editor-tutorial-actions">
          <el-button v-if="!demonstrating" size="small" type="primary" @click="runDemonstration">
            <i class="fa fa-play-circle-o mr-1" aria-hidden="true"></i>演示给我看
          </el-button>
          <el-button v-else size="small" @click="resetStep">停止演示，自己试试</el-button>
          <el-button v-if="!demonstrating" size="small" text @click="resetStep">重练本步</el-button>
        </div>
      </div>

      <div class="editor-tutorial-workbench" :class="{ 'is-demonstrating': demonstrating }" :key="currentStepIndex">
        <div class="editor-tutorial-workbench-label">
          <span><i class="fa fa-flask" aria-hidden="true"></i> 独立练习区</span>
          <span>{{ demonstrating ? '正在演示操作…' : '所有按钮都只影响这里' }}</span>
        </div>
        <fieldset :disabled="demonstrating" class="editor-tutorial-controls">
          <legend class="editor-tutorial-sr-only">本步练习操作</legend>
          <div v-if="currentStepIndex === 0" class="editor-tutorial-actions">
            <el-button size="small" type="primary" @click="captureDemoFrame">刷新截图</el-button>
            <el-button size="small" :type="playing ? 'warning' : ''" :aria-pressed="playing" @click="toggleDemoPlayback">
              <i class="fa mr-1" :class="playing ? 'fa-pause' : 'fa-play'" aria-hidden="true"></i>{{ playing ? '暂停' : '播放' }}
            </el-button>
            <el-button size="small" @click="importDemoImage">导入示例图片</el-button>
            <span class="editor-tutorial-muted">{{ playing ? '本地动态画面' : '静态画面' }} · 第 {{ frameNumber }} 帧</span>
          </div>
          <p v-else-if="currentStepIndex === 1" class="editor-tutorial-muted">在下图右下角「邮件」上按住鼠标左键拖出矩形；不方便拖拽可使用「演示给我看」。</p>
          <div v-else-if="currentStepIndex === 2" class="editor-tutorial-actions">
            <label>目标类型
              <select v-model="targetKind" aria-label="目标类型">
                <option value="T">T · 文字（名称：邮件）</option>
                <option value="I">I · 图像（勾选图像匹配）</option>
                <option value="B">B · 坐标（名称留空）</option>
              </select>
            </label>
            <el-button size="small" type="success" @click="generateDemoTarget">生成对象</el-button>
            <el-button size="small" @click="previewSelectionSave">保存选区（演示）</el-button>
          </div>
          <div v-else-if="currentStepIndex === 3" class="editor-tutorial-actions">
            <span class="editor-tutorial-mode">遥控模式：模拟（练习区锁定）</span>
            <el-button size="small" type="primary" :disabled="!selection" @click="recordDemoClick">点击</el-button>
            <el-button size="small" :disabled="!selection" @click="recordDemoSwipe">向右滑动</el-button>
            <el-button size="small" @click="clearDemoOverlays">清除虚拟标注</el-button>
          </div>
          <div v-else-if="currentStepIndex === 4">
            <editor-menu-bar :groups="menuGroups" @action="runMenuAction" />
            <p class="editor-tutorial-muted">这里演练常用菜单项；选一项，看下方代码如何变化。</p>
          </div>
          <div v-else-if="currentStepIndex === 5" class="editor-tutorial-execution">
            <label>自定义代码（固定示例，不执行 Python）<pre>locate(T("邮件"))</pre></label>
            <div class="editor-tutorial-actions">
              <el-button size="small" type="primary" :disabled="executionRunning" @click="runDemoCode">执行（演示）</el-button>
              <el-button size="small" type="danger" plain :disabled="!executionRunning" @click="stopDemoCode">终止执行</el-button>
            </div>
            <output class="editor-tutorial-result" aria-live="polite">{{ executionResult || '点击执行，观察示例返回值；也可以在等待时终止。' }}</output>
          </div>
          <form v-else class="editor-tutorial-save" @submit.prevent="previewTaskSave">
            <label>脚本名称（自定义任务/ 之后）<input v-model="taskName" placeholder="入门/查看邮件" autocomplete="off"></label>
            <label>任务起点（ensure_in）
              <select v-model="taskStart"><option value="">请选择起点</option><option value="村庄">村庄（示例）</option></select>
            </label>
            <el-button size="small" type="primary" native-type="submit">预演保存（不写文件）</el-button>
            <output v-if="savePreview" class="editor-tutorial-result">{{ savePreview }}</output>
          </form>
        </fieldset>

        <div v-if="currentStepIndex <= 3" class="editor-tutorial-scene" :class="{ 'is-interactive': currentStepIndex === 1 || currentStepIndex === 3 }">
          <editor-canvas v-if="frameLoaded" :image-src="frameSource" :selection="selection"
            :img-width="1280" :img-height="720" :virtual-click-markers="clickMarkers" :virtual-swipe-lines="swipeLines"
            @selection-change="onDemoSelection" @canvas-remote-click="onDemoCanvasClick" @canvas-remote-swipe="onDemoCanvasSwipe" />
          <div v-else class="editor-tutorial-scene-empty"><i class="fa fa-picture-o" aria-hidden="true"></i><span>还没有画面</span><small>点「刷新截图」加载本地示例</small></div>
        </div>
        <div v-if="currentStepIndex === 1" class="editor-tutorial-coordinate">{{ selectionDescription }} · 原图 1280 × 720，缩放显示不会改变坐标</div>
        <div v-if="currentStepIndex >= 2 && currentStepIndex !== 5" class="editor-tutorial-code">
          <span>{{ currentStepIndex === 2 ? '对象预览：还不是一个动作' : '操作录制区：本地示例代码，未执行' }}</span>
          <pre>{{ currentStepIndex === 2 ? (generatedCode || '选择一种目标，再点「生成对象」') : (recordedCode || '# 操作后，生成的代码会出现在这里') }}</pre>
        </div>
      </div>
      <p class="editor-tutorial-feedback" :class="{ 'is-complete': completedSteps.includes(currentStepIndex) }" role="status">{{ feedback || '可以自己操作，也可以先看一次演示。' }}</p>
      <p class="editor-tutorial-caution"><i class="fa fa-lightbulb-o" aria-hidden="true"></i><span>{{ step.caution }}</span></p>
      <details class="editor-tutorial-details" :key="'tips-' + currentStepIndex">
        <summary>更多按钮与避坑提示 · {{ step.tips.length }} 条</summary>
        <dl><template v-for="tip in step.tips" :key="tip[0]"><dt>{{ tip[0] }}</dt><dd>{{ tip[1] }}</dd></template></dl>
      </details>
    </section>
  </div>
  <template #footer>
    <div class="editor-tutorial-footer">
      <el-button @click="closeTutorial">退出教程</el-button>
      <span class="editor-tutorial-muted">{{ completedSteps.length === steps.length ? '已走完流程，现在可以回到编辑器练习了。' : '无需做完练习，也可以继续下一步。' }}</span>
      <div class="editor-tutorial-actions">
        <el-button :disabled="currentStepIndex === 0" @click="goToStep(currentStepIndex - 1)">上一步</el-button>
        <el-button v-if="currentStepIndex < steps.length - 1" type="primary" @click="goToStep(currentStepIndex + 1)">下一步</el-button>
        <el-button v-else type="primary" @click="closeTutorial">返回编辑器</el-button>
      </div>
    </div>
  </template>
</el-dialog>`,
  setup(props, { emit }) {
    const { ref, computed, onBeforeUnmount, nextTick } = Vue;
    const steps = [
      {
        title: '先有一张画面', subtitle: '刷新 / 播放 / 导图', location: '左上「图片编辑器」与右侧画布',
        intro: '先拿到画面，再在画面上找目标，最后把操作变成代码。先认识这三个区域，就知道从哪里开始了。',
        task: '刷新一张示例图，再试试播放、暂停，观察画面里的光点与帧数。',
        caution: '播放用来看变化；框选、识别前先暂停。教程里的画面都是绘制的示意图，不是真实游戏截图。',
        tips: [
          ['刷新截图 / 遥控器「刷新」', '获取一张当前模拟器画面。真实页面的截图功能可能初始化设备会话；教程不会。'],
          ['播放 / 暂停', '连续更新 / 停在最后一帧，恢复静态标注。导图、离开编辑页会停止播放；点击画布或编辑选区控件也会暂停。'],
          ['拖入图片', '把本地图片拖到右侧画布即可离线标注，默认使用「模拟」遥控。先用截图练习最安全。'],
          ['三块区域', '左上识别和保存目标；左下遥控与代码调试；右侧看图、框选和编辑录制代码。'],
        ],
      },
      {
        title: '框出想操作的目标', subtitle: '左键框选 / 坐标 / 识别', location: '右侧画布 → 左上名称、Box、T/I 校验',
        intro: '尽量只框按钮或文字，不要把整屏都框进去。框选决定要识别什么、到哪里找。',
        task: '按住鼠标左键，拖出包含右下角「邮件」按钮的矩形。',
        caution: '本练习只检查矩形是否框住示例按钮，不跑 OCR。真实页面的绿色定位框、√ / X 才是当前截图的校验结果。',
        tips: [
          ['名称', '框选后尝试 OCR 填入名称；识别错了可以手改。文字目标用屏幕上的字，图像目标用保存的资源名。'],
          ['中心点 / Box', '中心点是一个位置；Box 是左、上、宽、高。坐标始终以原图为准，不用按画布显示大小换算。'],
          ['边缘阈值', '调整色差边缘收缩，松开后重算选区、OCR、颜色和校验；不是文字识别的置信度。'],
          ['0.5 / 0.75 / 1.0', '不同缩放下的定位检查；√ 为找到、X 为未找到。一次命中不保证后续所有游戏场景都成功。'],
        ],
      },
      {
        title: '把目标变成对象', subtitle: 'T / I / B 与保存选区', location: '左上「生成对象」「保存选区」及选项开关',
        intro: '有字优先 T，有图用 I，固定位置用 B。对象只描述目标，要交给 click、locate 等动作使用。',
        task: '分别选择 T、I、B，点击「生成对象」，对比代码；再试一次保存选区演示。',
        caution: '「保存选区」保存识别资源，不是保存任务。要在正式脚本里使用 I 图像模板，应先保存选区。',
        tips: [
          ['T / I / B', '名称非空时生成 T；勾选图像匹配改用 I；名称留空时生成 B 坐标区域。B 不会主动寻找文字，位置变动时更容易点错。'],
          ['生成对象', '将目标插入录制区当前光标位置。例外：执行模式下向 seq_click 的目标列表添加对象，还会真实点击一次并刷新；条件 ui_T() 内不会额外点击。'],
          ['固定名称 / 锁定颜色', '固定名称避免新框选覆盖已有名字；锁定颜色增加目标颜色约束，颜色变化时也可能找不到。'],
          ['x轴自由 / y轴自由', '沿对应轴扩大搜索范围；范围更宽不等于更准确，可能命中其他同名目标。'],
          ['图像匹配 / 仅OCR', '图像匹配选择 I 目标及模板校验；仅OCR影响保存资源时是否保存模板图，不是让所有代码只执行 OCR。'],
        ],
      },
      {
        title: '操作一次，录下一行', subtitle: '点击 / 滑动 / 模拟模式', location: '左下「遥控器」与右侧「操作录制」',
        intro: '遥控器会把动作追加到录制区。先用模拟模式确认位置，再决定是否向真机发送操作。',
        task: '点一次「点击」，再向右滑动；也可以在示例画布上右键单击或拖拽。',
        caution: '红点和蓝线仅表示模拟输入的位置，不会打开游戏页面。正式页面切到「执行」会触控真机，需要解锁且执行权空闲。',
        tips: [
          ['点击 / 滑动方向', '点击当前选区；滑动沿所选方向在选区内完成。箭头指手指移动方向，不是页面滚动方向。'],
          ['画布右键', '单击录制坐标点击，拖拽录制起终点滑动，并清除原选区。此步预选了邮件；右键后可重练本步恢复选区，正式页面则用左键重新框选。'],
          ['清除虚拟标注 / 清空', '前者清掉画布红点蓝线；录制区「清空」只清代码。两者不会撤销已经发给真机的动作。'],
          ['真实操作之后', '遥控操作后等待约 1.5 秒刷新截图。代码生成或输入发出，不代表游戏已完成预期动作。'],
        ],
      },
      {
        title: '用菜单拼出流程', subtitle: '等待 / 判断 / 连续点击', location: '操作录制区顶部菜单栏',
        intro: '不必背所有函数。菜单把常用模板写进代码；先等目标出现，再点击，比盲目加固定延时更可靠。',
        task: '打开「操作 → 等待 → 等待出现」，再添加「点击」，看看两行代码。',
        caution: '菜单主要生成代码，但提取会做识别预览，序列录制也可能触发真实点击；不要把整个编辑器当成安全沙箱。',
        tips: [
          ['操作', '点击、长按、滑动、输入、等待、提取文字/前后缀数字/颜色。阻塞等待只是 sleep；条件等待要有 T/I 目标。'],
          ['序列点击 / 直到出现', 'seq_click([]) 放连续目标；click(..., until=lambda: ui_T(...)) 区分被点击目标与完成条件，条件位置也能用「生成对象」填入。'],
          ['定位', 'locate 返回位置；ui_T / ui_F 判断存在或不在；match 做区域匹配。不是每个动作都要点屏幕。'],
          ['后台 / 角色技能 / 工具', '后台组织作用域、监听和信号；角色技能插入 h 的动作；工具提供导航、地图位置、数字网格和日志。先掌握基本流程再用它们。'],
          ['代码编辑', '可以直接修改录制区；Tab 缩进四空格、Shift-Tab 回退，双击函数行可单独编辑函数。复制只复制，不会执行。'],
        ],
      },
      {
        title: '先验证，再执行', subtitle: '自定义代码 / 返回值 / 终止', location: '左下「自定义代码执行」',
        intro: '把要验证的一小段代码放到自定义代码区。先试定位、判断，再测试有实际副作用的操作。',
        task: '执行固定的 locate 示例，读一次返回值；重试时也可以点「终止执行」。',
        caution: '这里仅演示结果展示，不执行任何 Python。真实编辑器的模拟模式不是任意 Python 的安全沙箱，不要运行不可信代码。',
        tips: [
          ['返回值', '最后一行表达式显示它的值；末行赋值显示左侧变量，也可写 __result__。标准输出会一起显示，没有返回值不代表失败。'],
          ['执行 / 操作录制', '自定义代码执行不会自动追加进录制区；它是调试入口，不是录制区全部代码的运行按钮。'],
          ['终止执行', '发送协作式取消请求，需要当前动作响应；不是撤销操作。不要连续重复执行，也不要把请求返回当作业务成功。'],
          ['结束后截图', '真实执行结束（包括报错或取消）会补刷截图；模拟执行保留离线图片和标记。被拒绝或网络异常不等于执行结束。'],
        ],
      },
      {
        title: '保存成可复用任务', subtitle: '脚本名称 / 起点 / 参数', location: '操作录制 → 文件 → 保存脚本',
        intro: '脚本需要明确从哪里开始。保存后会重载任务列表，但不会自动运行任务。',
        task: '填「入门/查看邮件」，选择示例起点「村庄」，预演一次保存。',
        caution: '正式保存会合并录制区和自定义代码区；不想保存的临时测试代码，请先从自定义代码区清掉。此处不创建任何文件。',
        tips: [
          ['脚本名称', '写在「自定义任务/」之后，如 入门/查看邮件，对应 data/custom_task/入门/查看邮件.py。目录不是任务起点。'],
          ['任务起点 ensure_in', '选择已注册起点，保存后由注册入口统一导航，正文不重复导航。无位置要求选择“任意位置”（ANYWHERE）；完整任务源码同样遵守声明，debug 不跳过入口。'],
          ['描述 / task_docs / 参数', '描述写用途，task_docs 写注意事项；参数填写字段名、类型和解释，Enum 选项使用 JSON 数组。'],
          ['文件菜单', '保存脚本已可用；「加载脚本」「另存为」当前未实现。保存选区则是另一回事：只保存识别目标资源。'],
          ['回到正式页面', '先取图 → 暂停框选 → 校验目标 → 模拟录制 → 小段调试 → 保存；最后按授权在真机上验证实际结果。'],
        ],
      },
    ];
    const currentStepIndex = ref(0);
    const tutorialContent = ref(null);
    const stepsNavigation = ref(null);
    const step = computed(() => steps[currentStepIndex.value]);
    const completedSteps = ref([]);
    const feedback = ref('');
    const demonstrating = ref(false);
    const frameLoaded = ref(false);
    const frameNumber = ref(0);
    const playing = ref(false);
    const selection = ref(null);
    const targetKind = ref('T');
    const generatedCode = ref('');
    const recordedCode = ref('');
    const clickMarkers = ref([]);
    const swipeLines = ref([]);
    const executionRunning = ref(false);
    const executionResult = ref('');
    const taskName = ref('');
    const taskStart = ref('');
    const savePreview = ref('');
    const pendingTimers = new Set();
    let playbackTimer = null;
    let executionTimer = null;
    let closed = false;
    const exampleSelection = () => ({ left: 930, top: 500, right: 1150, bottom: 590 });
    const selectionDescription = computed(() => {
      const rectangle = selection.value;
      return rectangle
        ? `Box(${rectangle.left}, ${rectangle.top}, ${rectangle.right - rectangle.left}, ${rectangle.bottom - rectangle.top})`
        : '尚未框选';
    });
    // Vector scene is deterministic, bundled and explicitly not a captured game frame.
    const frameSource = computed(() => {
      const lightPosition = 180 + (frameNumber.value % 8) * 55;
      const scene = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
        <rect width="1280" height="720" fill="#e0f2f1"/>
        <path d="M0 450L230 200L440 440L700 140L1080 450L1280 280V720H0Z" fill="#abcac2"/>
        <path d="M0 570Q420 380 730 540T1280 470V720H0Z" fill="#6f9b83"/>
        <rect x="340" y="355" width="245" height="210" rx="8" fill="#f4e4c4"/>
        <path d="M300 365L460 235L625 365Z" fill="#536c69"/>
        <rect x="425" y="445" width="76" height="120" rx="5" fill="#947953"/>
        <circle cx="${lightPosition}" cy="175" r="22" fill="#fcd970"/>
        <rect x="32" y="28" width="1216" height="76" rx="15" fill="#173b34"/>
        <g font-family="Microsoft YaHei, sans-serif"><text x="58" y="78" font-size="30" fill="white">村庄 · 教程示意图</text>
        <text x="910" y="77" font-size="25" fill="#bce7d4">本地第 ${frameNumber.value} 帧</text>
        <rect x="930" y="500" width="220" height="90" rx="18" fill="#ffdb7f" stroke="#594d2c" stroke-width="4"/>
        <text x="1040" y="558" text-anchor="middle" font-size="38" fill="#3b3424">邮件</text>
        <text x="58" y="665" font-size="24" fill="white">练习用画面，不是真实游戏 / OCR 结果</text></g></svg>`;
      return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(scene);
    });

    function schedule(callback, milliseconds) {
      const identifier = setTimeout(() => {
        pendingTimers.delete(identifier);
        if (!closed) callback();
      }, milliseconds);
      pendingTimers.add(identifier);
      return identifier;
    }

    function cancelTimer(identifier) {
      if (identifier !== null) clearTimeout(identifier);
      pendingTimers.delete(identifier);
    }

    function clearPendingWork() {
      pendingTimers.forEach(identifier => clearTimeout(identifier));
      pendingTimers.clear();
      playbackTimer = null;
      executionTimer = null;
      playing.value = false;
      executionRunning.value = false;
      demonstrating.value = false;
    }

    function completeStep(message) {
      if (!completedSteps.value.includes(currentStepIndex.value)) {
        completedSteps.value = [...completedSteps.value, currentStepIndex.value];
      }
      feedback.value = message;
    }

    function resetStep() {
      clearPendingWork();
      completedSteps.value = completedSteps.value.filter(index => index !== currentStepIndex.value);
      feedback.value = '';
      frameLoaded.value = currentStepIndex.value > 0;
      frameNumber.value = frameLoaded.value ? 1 : 0;
      selection.value = currentStepIndex.value >= 2 ? exampleSelection() : null;
      targetKind.value = 'T';
      generatedCode.value = '';
      recordedCode.value = currentStepIndex.value === 6 ? 'wait_for_appear(T("邮件"))\nclick(T("邮件"))' : '';
      clickMarkers.value = [];
      swipeLines.value = [];
      executionResult.value = '';
      taskName.value = '';
      taskStart.value = '';
      savePreview.value = '';
    }

    function goToStep(index) {
      if (closed || !Number.isInteger(index) || index < 0 || index >= steps.length) return;
      const progress = completedSteps.value;
      currentStepIndex.value = index;
      resetStep();
      completedSteps.value = progress;
      nextTick(() => {
        const scrollContainer = tutorialContent.value?.closest('.el-dialog__body');
        if (scrollContainer) scrollContainer.scrollTop = 0;
        stepsNavigation.value?.querySelector('[aria-current="step"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      });
    }

    function captureDemoFrame() {
      frameLoaded.value = true;
      frameNumber.value += 1;
      completeStep('已有一张画面。试试播放后再暂停：停住的那一帧才适合仔细框选。');
    }

    function advanceDemoFrame() {
      frameNumber.value += 1;
      if (playing.value) playbackTimer = schedule(advanceDemoFrame, 500);
    }

    function toggleDemoPlayback() {
      playing.value = !playing.value;
      frameLoaded.value = true;
      if (playing.value) {
        advanceDemoFrame();
        feedback.value = '播放中：只改变本地帧数与光点位置，不请求模拟器。';
      } else {
        cancelTimer(playbackTimer);
        playbackTimer = null;
        completeStep('已暂停，保留最后一帧。正式编辑器中现在就可以开始框选了。');
      }
    }

    function importDemoImage() {
      if (playing.value) toggleDemoPlayback();
      captureDemoFrame();
      feedback.value = '示例图片已载入。正式页面把本地图片拖进画布即可导入，并默认进入模拟模式。';
    }

    function onDemoSelection(rectangle) {
      if (currentStepIndex.value !== 1) return;
      selection.value = { ...rectangle };
      const coversTarget = rectangle.left <= 945 && rectangle.top <= 515
        && rectangle.right >= 1135 && rectangle.bottom >= 575;
      const area = (rectangle.right - rectangle.left) * (rectangle.bottom - rectangle.top);
      if (!coversTarget || area > 1280 * 720 * 0.45) {
        feedback.value = '再试一次：框住右下角「邮件」整个按钮，别框整屏。这里只校验示例位置，不做 OCR。';
        return;
      }
      completeStep('框选成功！真实页面会尝试填入名称、计算颜色并校验目标；识别错字时可手动修改名称。');
    }

    function generateDemoTarget() {
      generatedCode.value = targetKind.value === 'B'
        ? 'B(930,500,220,90)'
        : `${targetKind.value}("邮件", box=Box(930,500,220,90).margin())`;
      completeStep(targetKind.value === 'I'
        ? '这是图像目标 I。正式脚本使用前先保存模板；这里只展示代码，不会保存资源。'
        : '生成的是目标对象，不会点击。把它放进 click(...) 才是点击动作。');
    }

    function previewSelectionSave() {
      feedback.value = '演示：保存选区会登记「邮件」识别资源，并按「仅OCR」选项决定是否保存模板图；不是保存任务。这里未写文件。';
    }

    function appendPracticeCode(code) {
      recordedCode.value += (recordedCode.value ? '\n' : '') + code;
    }

    function recordDemoClick() {
      if (!selection.value) return;
      clickMarkers.value = [...clickMarkers.value, { x: 1040, y: 545 }];
      appendPracticeCode('click(T("邮件", box=Box(930,500,220,90).margin()))');
      completeStep('红点标出点击位置，录制区多了一行代码。模拟不会打开邮件；它只帮你检查输入位置。');
    }

    function onDemoCanvasClick(point) {
      if (currentStepIndex.value !== 3) return;
      selection.value = null;
      clickMarkers.value = [...clickMarkers.value, point];
      appendPracticeCode(`click(B(${point.x},${point.y}))`);
      completeStep('右键单击录制的是坐标 B；与按名称找文字的 T 不同。此处没有触控真机。');
    }

    function appendDemoSwipe(points) {
      swipeLines.value = [...swipeLines.value, points];
      appendPracticeCode(`swipe(B(${points.x1},${points.y1}), B(${points.x2},${points.y2}), duration_s=1)`);
      completeStep('蓝线是手指滑动路线，代码记录起点和终点。画面不会滚动，因为这里只画模拟标记。');
    }

    function onDemoCanvasSwipe(points) {
      if (currentStepIndex.value !== 3) return;
      selection.value = null;
      appendDemoSwipe(points);
    }

    function recordDemoSwipe() {
      if (!selection.value) return;
      appendDemoSwipe({ x1: 930, y1: 545, x2: 1150, y2: 545 });
    }

    function clearDemoOverlays() {
      clickMarkers.value = [];
      swipeLines.value = [];
      feedback.value = '标记已清除，录制代码仍在。清除标记和清空代码是两个操作。';
    }

    function insertMenuExample(code) {
      appendPracticeCode(code);
      completeStep('菜单已将模板追加到示例录制区，没有执行代码。可以继续选其他菜单，组合自己的流程。');
    }

    const menuGroups = computed(() => [
      { label: '操作', items: [
        { key: 'wait', label: '等待', icon: 'fa fa-clock-o', children: [
          { key: 'wait-appear', label: '等待出现', action: () => insertMenuExample('wait_for_appear(T("邮件"))') },
        ] },
        { key: 'click', label: '点击', children: [
          { key: 'click-once', label: '点击', action: () => insertMenuExample('click(T("邮件"))') },
        ] },
        { key: 'sequence', label: '序列点击', action: () => insertMenuExample('seq_click([])  # 在列表里添加目标') },
      ] },
      { label: '定位', items: [
        { key: 'exists', label: '判断存在', action: () => insertMenuExample('ui_T(T("邮件"))') },
        { key: 'locate', label: '定位坐标', action: () => insertMenuExample('locate(T("邮件"))') },
      ] },
      { label: '工具', items: [
        { key: 'navigate', label: '导航到...', children: [
          { key: 'village', label: '村庄', action: () => insertMenuExample('ensure_in("村庄")') },
        ] },
        { key: 'log', label: '打印日志（log）', action: () => insertMenuExample('logger.info("检查邮件目标")') },
      ] },
    ]);

    function runMenuAction(item) {
      if (!demonstrating.value) item.action();
    }

    function runDemoCode() {
      if (executionRunning.value) return;
      executionRunning.value = true;
      executionResult.value = '演示等待中…（未执行 Python）';
      executionTimer = schedule(() => {
        executionTimer = null;
        executionRunning.value = false;
        executionResult.value = '示例返回值 (repr)：930,500,220,90\n依次是左、上、宽、高；仅示意位置，不是真实 OCR 结果。';
        completeStep('定位返回一个位置，不是点击动作。正式调试也应先核对返回值，再决定是否执行真实输入。');
      }, 1400);
    }

    function stopDemoCode() {
      cancelTimer(executionTimer);
      executionTimer = null;
      executionRunning.value = false;
      executionResult.value = '演示已终止。真实任务的终止是协作式取消，不会撤销已完成的操作。';
      feedback.value = '可以再次执行固定示例，等待一次完整返回。';
    }

    function previewTaskSave() {
      savePreview.value = '';
      const segments = taskName.value.trim().split('/');
      if (!segments.every(segment => segment.trim() && segment === segment.trim()
        && segment !== '.' && segment !== '..' && !/[\\:*?"<>|]/.test(segment))) {
        feedback.value = '请填写有效脚本名称，例如「入门/查看邮件」，不要使用绝对路径或 ..。';
        return;
      }
      if (taskStart.value !== '村庄') {
        feedback.value = '请选择明确的任务起点。目录名不会自动变成起点，不能留空。';
        return;
      }
      savePreview.value = `预演路径：data/custom_task/${segments.join('/')}.py\n起点：${taskStart.value}；正式保存会生成对应导航并重载任务。\n本次仅预演，未写文件、未运行任务。`;
      completeStep('已走通保存流程！回到正式页面前，别忘记检查自定义代码区是否还有不想保存的调试片段。');
    }

    function runDemonstration() {
      resetStep();
      demonstrating.value = true;
      const demonstrations = [
        [captureDemoFrame, toggleDemoPlayback, toggleDemoPlayback],
        [() => { selection.value = { left: 920, top: 490, right: 990, bottom: 530 }; }, () => onDemoSelection(exampleSelection())],
        [generateDemoTarget, () => { targetKind.value = 'I'; generateDemoTarget(); }, () => { targetKind.value = 'B'; generateDemoTarget(); }],
        [recordDemoClick, recordDemoSwipe],
        [() => {
          insertMenuExample('wait_for_appear(T("邮件"))');
          feedback.value = '演示：操作 → 等待 → 等待出现，先等邮件目标能被找到。';
        }, () => {
          insertMenuExample('click(T("邮件"))');
          feedback.value = '演示：操作 → 点击 → 点击，再追加点击动作；两行组合成先等后点。';
        }],
        [runDemoCode, () => { feedback.value = 'locate 返回坐标；这里只演示返回值，未调用识别或执行接口。'; }],
        [() => { taskName.value = '入门/查看邮件'; feedback.value = '第一步：填脚本名称，可以带目录。'; },
          () => { taskStart.value = '村庄'; feedback.value = '第二步：明确选择起点，不靠目录猜测。'; }, previewTaskSave],
      ][currentStepIndex.value];
      demonstrations.forEach((action, index) => schedule(action, 350 + index * 1000));
      schedule(() => { demonstrating.value = false; }, 600 + demonstrations.length * 1000);
    }

    function closeTutorial() {
      if (closed) return;
      closed = true;
      clearPendingWork();
      emit('close');
    }

    onBeforeUnmount(() => { closed = true; clearPendingWork(); });
    return {
      steps, step, currentStepIndex, tutorialContent, stepsNavigation, completedSteps, feedback, demonstrating,
      frameLoaded, frameNumber, frameSource, playing, selection, selectionDescription,
      targetKind, generatedCode, recordedCode, clickMarkers, swipeLines,
      executionRunning, executionResult, taskName, taskStart, savePreview, menuGroups,
      goToStep, resetStep, closeTutorial, runDemonstration,
      captureDemoFrame, toggleDemoPlayback, importDemoImage, onDemoSelection,
      generateDemoTarget, previewSelectionSave, recordDemoClick, recordDemoSwipe,
      onDemoCanvasClick, onDemoCanvasSwipe, clearDemoOverlays, runMenuAction,
      runDemoCode, stopDemoCode, previewTaskSave,
    };
  },
};
