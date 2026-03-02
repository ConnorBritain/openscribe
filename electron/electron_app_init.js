// electron_app_init.js
// Handles app initialization, config, and persistent settings

const Store = require('electron-store');
const { ELECTRON_DEFAULTS } = require('./settings_contract');
const DEFAULT_WAKE_WORDS = ELECTRON_DEFAULTS.wakeWords || { dictate: ['note'] };

// Initialize electron-store
const store = new Store({
  defaults: ELECTRON_DEFAULTS,
  migrations: {
    '1.0.0-migrateWakeWords': store => {
      const wakeWords = store.get('wakeWords');
      if (Array.isArray(wakeWords)) {
        store.set('wakeWords', {
          dictate: wakeWords
        });
      } else if (typeof wakeWords !== 'object' || wakeWords === null || !Object.prototype.hasOwnProperty.call(wakeWords, 'dictate')) {
        store.set('wakeWords', DEFAULT_WAKE_WORDS);
      } else {
        const dictateWords = Array.isArray(wakeWords.dictate) ? wakeWords.dictate : [];
        store.set('wakeWords', { dictate: dictateWords });
      }
    }
  }
});

module.exports = { store };
