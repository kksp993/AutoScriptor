(function (global) {
  function replaceReactiveObject(target, source) {
    if (!target || !source || typeof source !== 'object') return;
    Object.keys(target).forEach((key) => delete target[key]);
    Object.assign(target, source);
  }

  function assignObject(target, source) {
    if (!target || !source || typeof source !== 'object') return;
    Object.assign(target, source);
  }

  function applySnapshot(state, payload) {
    if (!payload || payload.error) return false;

    if (payload.credential && 'unlocked' in payload.credential) {
      state.overviewSecurityUnlocked.value = !!payload.credential.unlocked;
    }
    if (payload.current_account !== undefined) {
      state.currentAccount.value = payload.current_account || '';
    }
    if (Array.isArray(payload.accounts)) {
      state.accounts.value = payload.accounts;
    }
    if (payload.active_character) {
      Object.assign(state.activeCharacter, { server: '', name: '' }, payload.active_character);
    }
    if (payload.character_name !== undefined) {
      state.characterName.value = payload.character_name || '';
      if (!state.configData.game) state.configData.game = {};
      state.configData.game.character_name = state.characterName.value;
    }
    const characters = payload.characters || payload.characters_summary;
    if (characters) {
      replaceReactiveObject(state.charactersTree, characters);
    }
    if (payload.game_professions_by_character) {
      replaceReactiveObject(state.gameProfessionsByCharacter, payload.game_professions_by_character);
    }
    if (Array.isArray(payload.game_profession_options)) {
      state.gameProfessionOptions.value = payload.game_profession_options;
    }
    if (Array.isArray(payload.dispatch_queue)) {
      state.dispatchQueue.value = payload.dispatch_queue;
    }
    if (payload.all_tasks_summary) {
      replaceReactiveObject(state.allTasksSummary, payload.all_tasks_summary);
    }
    if (payload.overview) {
      const overview = payload.overview;
      if (overview.scheduler) assignObject(state.overviewData.scheduler, overview.scheduler);
      if (overview.stats) assignObject(state.overviewData.stats, overview.stats);
      if (overview.stats_all) assignObject(state.overviewData.statsAll, overview.stats_all);
      if (overview.overall_next_execution !== undefined) {
        state.overviewData.overall_next_execution = overview.overall_next_execution;
      }
      if (Array.isArray(overview.upcoming)) state.overviewData.upcoming = overview.upcoming;
      if (overview.runtime) assignObject(state.overviewData.runtime, overview.runtime);
    }
    if (payload.scheduler) {
      assignObject(state.schedulerStatus, payload.scheduler);
    }
    if (payload.runtime) {
      state.directRunRunning.value = !!payload.runtime.direct_running;
      if (payload.runtime.scheduler) assignObject(state.schedulerStatus, payload.runtime.scheduler);
    }
    return true;
  }

  global.WebUIRuntimeStore = {
    applySnapshot,
    replaceReactiveObject,
    assignObject,
  };
})(window);
