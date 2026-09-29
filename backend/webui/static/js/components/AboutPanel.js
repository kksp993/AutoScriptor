/** 与 webapp/package.json version 保持同步。 */
const APP_DISPLAY_VERSION = '1.0.3';

const AboutPanel = {
  name: 'AboutPanel',
  data() {
    return {
      appVersion: APP_DISPLAY_VERSION,
      copyrightYear: new Date().getFullYear(),
    };
  },
  template: `
<div class="bg-white rounded-xl shadow-md p-8 h-full overflow-y-auto max-w-3xl">
  <div class="mb-8">
    <h1 class="text-2xl font-bold text-slate-800 mb-1">造笔</h1>
    <p class="text-slate-500 text-sm font-medium tracking-wide">AutoScriptor</p>
    <p class="mt-3 text-sm text-slate-600">软件版本 <span class="font-mono text-slate-800">{{ appVersion }}</span></p>
    <p class="mt-1 text-sm text-slate-600">仓库作者 <span class="font-medium text-slate-800">Kksp993</span></p>
  </div>

  <el-divider />

  <section class="space-y-4 text-sm text-slate-700 leading-relaxed">
    <p class="font-semibold text-slate-800">版权声明</p>
    <p>
      本软件及其文档受著作权法与国际条约保护。未经权利人书面许可，任何单位或个人不得以任何形式复制、修改、传播、
      出租、出售或用于商业再分发；不得对本软件实施反向工程、反编译或试图获取源代码，法律法规另有规定的除外。
    </p>
    <p class="text-slate-600">
      请仅从官方发布渠道获取与更新本软件。非官方渠道获得的副本可能已被篡改，使用风险由使用者自行承担。
    </p>
  </section>

  <el-divider />

  <section class="space-y-3 text-sm text-slate-700 leading-relaxed">
    <p class="font-semibold text-slate-800">免责声明</p>
    <ul class="list-disc pl-5 space-y-2 text-slate-600">
      <li>📌 本项目仅供学习交流，开发者团队保留最终解释权</li>
      <li>⚖️ 使用本工具产生的一切风险需自行承担</li>
      <li>🚫 本项目未授权任何个人、商家、自媒体账号等进行售卖</li>
      <li>🚫 若您遇到商家使用本软件进行代练并收费，产生的任何问题及后果与本软件无关</li>
      <li>🚫 开发者团队不会为您提供任何"售后"服务，作者及贡献者对任何人因使用本代码导致的任何损失、账号封禁或法律纠纷不承担任何直接或间接的责任。一切后果由使用者自行承担。</li>
    </ul>
  </section>
</div>`,
};
