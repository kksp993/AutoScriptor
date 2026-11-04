/** Viewport-aware menu panels shared by the recorder and function editor. */
const EditorMenuBar = {
  name: 'EditorMenuBar',
  props: { groups: { type: Array, required: true } },
  emits: ['action'],
  template: `
<nav class="editor-menubar" ref="menuRoot" @click.stop>
  <button v-for="group in groups" :key="group.label" type="button"
          class="editor-menubar-item" :class="{ 'is-open': openPanels[0]?.key === group.label }"
          aria-haspopup="menu" :aria-expanded="openPanels[0]?.key === group.label"
          @click="togglePanel(group.label, 0, $event.currentTarget)">
    {{ group.label }}
  </button>
  <teleport to="body">
    <div v-for="(panel, depth) in visiblePanels" :key="panel.key"
         :ref="element => positionPanel(element, panel, depth)"
         class="editor-menu-panel" role="menu" :style="{ zIndex: 3000 + depth }"
         @click.stop @scroll="closeDescendants(depth)">
      <button v-for="item in panel.items" :key="item.key" type="button"
              class="editor-menu-item" role="menuitem"
              :class="{ 'is-disabled': item.disabled && item.disabled() }"
              :disabled="item.disabled && item.disabled()"
              :aria-haspopup="item.children ? 'menu' : undefined"
              :aria-expanded="item.children ? openPanels[depth + 1]?.key === item.key : undefined"
              @click="activateItem(item, depth, $event.currentTarget)">
        <i :class="item.icon"></i><span>{{ item.label }}</span>
        <i v-if="item.children" class="fa fa-angle-right editor-menu-arrow"></i>
      </button>
    </div>
  </teleport>
</nav>`,
  setup(props, { emit }) {
    const { ref, computed, onMounted, onBeforeUnmount } = Vue;
    const menuRoot = ref(null);
    const openPanels = ref([]);
    const panelElements = [];
    const visiblePanels = computed(() => {
      let items = [];
      return openPanels.value.map((panel, depth) => {
        items = depth
          ? items.find(item => item.key === panel.key)?.children || []
          : props.groups.find(group => group.label === panel.key)?.items || [];
        return { ...panel, items };
      });
    });

    function closeMenus() {
      openPanels.value = [];
    }

    function closeDescendants(depth) {
      if (openPanels.value.length > depth + 1) {
        openPanels.value = openPanels.value.slice(0, depth + 1);
      }
    }

    function togglePanel(key, depth, anchor) {
      const alreadyOpen = openPanels.value[depth]?.key === key;
      openPanels.value = openPanels.value.slice(0, depth);
      if (!alreadyOpen) {
        openPanels.value.push({ key, anchor: anchor.getBoundingClientRect() });
      }
    }

    function activateItem(item, depth, anchor) {
      if (item.disabled && item.disabled()) return;
      if (item.children) {
        togglePanel(item.key, depth + 1, anchor);
      } else {
        closeMenus();
        emit('action', item);
      }
    }

    function positionPanel(element, panel, depth) {
      panelElements[depth] = element;
      if (!element) return;
      const gutter = 8;
      const gap = 4;
      const viewportWidth = document.documentElement.clientWidth;
      const viewportHeight = document.documentElement.clientHeight;
      const bounds = element.getBoundingClientRect();
      let left = depth ? panel.anchor.right + gap : panel.anchor.left;
      let top = depth ? panel.anchor.top : panel.anchor.bottom + gap;
      if (depth && left + bounds.width > viewportWidth - gutter) {
        left = panel.anchor.left - bounds.width - gap;
      }
      if (!depth && top + bounds.height > viewportHeight - gutter) {
        top = panel.anchor.top - bounds.height - gap;
      }
      // Every level is teleported separately, so scrolling a parent cannot clip its child.
      element.style.left = `${Math.max(gutter, Math.min(left, viewportWidth - bounds.width - gutter))}px`;
      element.style.top = `${Math.max(gutter, Math.min(top, viewportHeight - bounds.height - gutter))}px`;
    }

    function onDocumentKeydown(event) {
      if (event.key === 'Escape') closeMenus();
    }

    function onDocumentClick(event) {
      const insideMenu = menuRoot.value?.contains(event.target)
        || panelElements.some(element => element?.contains(event.target));
      if (!insideMenu) closeMenus();
    }

    function onWindowScroll(event) {
      if (!event.target.closest?.('.editor-menu-panel')) closeMenus();
    }

    onMounted(() => {
      document.addEventListener('click', onDocumentClick, true);
      document.addEventListener('keydown', onDocumentKeydown);
      window.addEventListener('resize', closeMenus);
      window.addEventListener('scroll', onWindowScroll, true);
    });
    onBeforeUnmount(() => {
      document.removeEventListener('click', onDocumentClick, true);
      document.removeEventListener('keydown', onDocumentKeydown);
      window.removeEventListener('resize', closeMenus);
      window.removeEventListener('scroll', onWindowScroll, true);
    });

    return { menuRoot, openPanels, visiblePanels, togglePanel, activateItem, positionPanel, closeDescendants };
  },
};
