// Practice state is component-local; no settings, credentials or API client are passed in.
const NotificationsTutorial = {
  name: 'NotificationsTutorial',
  emits: ['close'],
  data() {
    return {
      currentStepIndex: 0,
      completedSteps: [],
      feedback: '',
      loginStage: 'idle',
      recipientType: 'private',
      recipientNumber: '',
      testCompleted: false,
      autoPushEnabled: false,
      steps: [
        {
          title: '准备机器人', subtitle: '小号发，主号收', location: '右侧「高级设置」',
          intro: '准备一个专用 QQ 小号发通知，你的主号用来接收。',
          task: '看到「尚未连接本机机器人」时，点「使用本机配置」；已配置好就跳过。',
          caution: '本机地址和令牌自动配置，不需要自己找。第三方机器人有账号风控风险，建议不用常用主号登录。',
        },
        {
          title: '登录并确认', subtitle: '扫码后核对账号', location: '左侧「机器人登录」',
          intro: '填写小号 QQ 号，点「扫码登录」，用这个小号的手机 QQ 扫码。',
          task: '手机确认后，核对「当前已登录」的号码，再点「确认账号」。',
          caution: '切换后，确认账号前暂停通知。实际登录的是手机扫码账号；号码不对就重新扫码。',
        },
        {
          title: '选择接收人', subtitle: '填主号或群号', location: '右侧「接收对象」',
          intro: '选「QQ 好友」填你的主号；选「QQ 群」填群号。这里不是机器人登录号。',
          task: '先在 QQ 中加机器人为好友，或把机器人拉入群，再填写接收号码。',
          caution: '更换接收人不需要切换机器人账号。',
        },
        {
          title: '测试并保存', subtitle: '收到后开启推送', location: '右侧「发送测试」「保存设置」',
          intro: '点「发送测试」，去 QQ 确认收到，再打开「自动推送」并保存设置。',
          task: '在下面试一次测试、开启、保存；回到设置后再做真实操作。',
          caution: '真实测试会发消息，但不会保存设置。没收到就查看错误提示，不要连续重发。',
        },
      ],
    };
  },
  computed: {
    step() {
      return this.steps[this.currentStepIndex];
    },
  },
  methods: {
    goToStep(index) {
      if (index < 0 || index >= this.steps.length) return;
      this.currentStepIndex = index;
      this.feedback = '';
      this.$nextTick(() => {
        this.$refs.stepsNavigation?.querySelector('[aria-current="step"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        this.$refs.tutorialContent?.closest('.el-dialog__body')?.scrollTo({ top: 0 });
      });
    },
    completeStep(message) {
      if (!this.completedSteps.includes(this.currentStepIndex)) this.completedSteps.push(this.currentStepIndex);
      this.feedback = message;
    },
    resetStep() {
      this.completedSteps = this.completedSteps.filter(index => index !== this.currentStepIndex);
      this.feedback = '';
      if (this.currentStepIndex === 1) this.loginStage = 'idle';
      if (this.currentStepIndex === 2) {
        this.recipientType = 'private';
        this.recipientNumber = '';
      }
      if (this.currentStepIndex === 3) {
        this.testCompleted = false;
        this.autoPushEnabled = false;
      }
    },
    confirmDemoLogin() {
      this.loginStage = 'confirmed';
      this.completeStep('已确认示例小号。真实扫码后也要核对号码。');
    },
    confirmDemoRecipient() {
      if (!/^[1-9][0-9]{4,19}$/.test(this.recipientNumber.trim())) {
        this.feedback = '请填一个 5 至 20 位的示例号码，不会保存或发送。';
        return;
      }
      this.completeStep(this.recipientType === 'group' ? '示例群已选好，真实机器人需要先入群。' : '示例接收人已选好，真实账号需要先加好友。');
    },
    testDemoDelivery() {
      this.testCompleted = true;
      this.feedback = '模拟测试完成，没有发送消息。真实使用时请去 QQ 查看。';
    },
    saveDemoSettings() {
      if (!this.testCompleted || !this.autoPushEnabled) {
        this.feedback = '先点发送测试，再打开自动推送。';
        return;
      }
      this.completeStep('演练完成！回到设置，按这四步操作即可。');
    },
  },
  template: `
<el-dialog :model-value="true" title="QQ 通知新手教程" class="editor-tutorial-dialog notifications-tutorial"
  width="min(920px, calc(100vw - 24px))" top="3vh" append-to-body
  :close-on-click-modal="false" @update:model-value="$emit('close')">
  <div class="editor-tutorial-safety"><i class="fa fa-shield" aria-hidden="true"></i><span>放心试：不登录 QQ、不发消息、不修改设置。</span></div>
  <div class="editor-tutorial-layout">
    <nav ref="stepsNavigation" class="editor-tutorial-steps" aria-label="通知教程步骤">
      <button v-for="(item, index) in steps" :key="item.title" type="button"
        :class="{ 'is-current': currentStepIndex === index, 'is-complete': completedSteps.includes(index) }"
        :aria-current="currentStepIndex === index ? 'step' : undefined" @click="goToStep(index)">
        <span class="editor-tutorial-step-number">{{ index + 1 }}</span>
        <span><strong>{{ item.title }}</strong><small>{{ item.subtitle }}</small></span>
      </button>
      <p class="editor-tutorial-progress">可跳步，随时退出或重看。</p>
    </nav>
    <section ref="tutorialContent" class="editor-tutorial-content" :aria-label="step.title">
      <div class="editor-tutorial-heading">
        <span class="editor-tutorial-eyebrow">第 {{ currentStepIndex + 1 }} 步 / {{ steps.length }}</span>
        <h3>{{ step.title }}</h3>
        <p>{{ step.intro }}</p>
        <div class="editor-tutorial-location">页面位置：{{ step.location }}</div>
      </div>
      <div class="editor-tutorial-assignment">{{ step.task }}</div>
      <div class="editor-tutorial-workbench">
        <div class="editor-tutorial-workbench-label"><span>独立练习区</span><el-button text size="small" @click="resetStep">重练本步</el-button></div>
        <div class="editor-tutorial-controls notifications-practice">
          <template v-if="currentStepIndex === 0">
            <p>练习：连接已安装的本机机器人。</p>
            <el-button type="primary" @click="completeStep('本机配置演练完成，无需填写令牌。')">使用本机配置（演练）</el-button>
          </template>
          <template v-else-if="currentStepIndex === 1">
            <p>机器人 QQ 号：示例小号</p>
            <el-button v-if="loginStage === 'idle'" type="primary" @click="loginStage = 'scanning'">扫码登录（演练）</el-button>
            <template v-else-if="loginStage === 'scanning'">
              <p>真实页面会显示二维码，请用小号扫码。</p>
              <el-button type="primary" @click="loginStage = 'scanned'">模拟手机确认</el-button>
            </template>
            <template v-else>
              <p>当前已登录：示例小号</p>
              <el-button type="success" :disabled="loginStage === 'confirmed'" @click="confirmDemoLogin">确认账号（演练）</el-button>
            </template>
          </template>
          <template v-else-if="currentStepIndex === 2">
            <label>接收类型<select v-model="recipientType" aria-label="练习接收类型"><option value="private">QQ 好友</option><option value="group">QQ 群</option></select></label>
            <label>接收号码<input v-model="recipientNumber" aria-label="练习接收号码" placeholder="填一个示例号码" inputmode="numeric" maxlength="20" autocomplete="off"></label>
            <el-button type="primary" @click="confirmDemoRecipient">确认接收人（演练）</el-button>
          </template>
          <template v-else>
            <el-button @click="testDemoDelivery">发送测试（演练）</el-button>
            <el-switch v-model="autoPushEnabled" aria-label="练习自动推送" active-text="自动推送"></el-switch>
            <el-button type="primary" @click="saveDemoSettings">保存（演练）</el-button>
          </template>
        </div>
      </div>
      <p class="editor-tutorial-feedback" :class="{ 'is-complete': completedSteps.includes(currentStepIndex) }" role="status">{{ feedback || '可以自己试，也可以直接看下一步。' }}</p>
      <p class="editor-tutorial-caution">{{ step.caution }}</p>
      <details v-if="currentStepIndex === 0" class="editor-tutorial-details">
        <summary>还没安装，或使用外部机器人？</summary>
        <p>在项目目录运行 <code>scripts\\install.bat qq</code>，装好后点左侧「重新检测」。</p>
        <p>已有外部 OneBot 服务时，在高级设置填写 HTTP 地址和发送令牌，不需要本机登录。请用 HTTPS 和令牌保护外部服务。</p>
      </details>
      <details v-if="currentStepIndex === 1" class="editor-tutorial-details">
        <summary>下次登录与安全提示</summary>
        <p>历史账号可用「快捷登录」，失效后重新扫码。登录前需在本机完成 AutoScriptor 安全验证。</p>
        <p>不用提供 QQ 密码、管理 Token 或 session。不要分享二维码或机器人的本地登录缓存。</p>
      </details>
    </section>
  </div>
  <template #footer>
    <div class="editor-tutorial-footer">
      <el-button @click="$emit('close')">退出教程</el-button>
      <div class="editor-tutorial-actions">
        <el-button :disabled="currentStepIndex === 0" @click="goToStep(currentStepIndex - 1)">上一步</el-button>
        <el-button v-if="currentStepIndex < steps.length - 1" type="primary" @click="goToStep(currentStepIndex + 1)">下一步</el-button>
        <el-button v-else type="primary" @click="$emit('close')">返回设置</el-button>
      </div>
    </div>
  </template>
</el-dialog>`,
};
