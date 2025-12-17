// electron_app_init.js
// Handles app initialization, config, and persistent settings

const Store = require('electron-store');

// Initialize electron-store
const store = new Store({
  defaults: {
    wakeWords: {
      dictate: ['note']
    },
    wakeWordEnabled: true,
    selectedAsrModel: '',
    filterFillerWords: true,
    fillerWords: ['um', 'uh', 'ah', 'er', 'hmm', 'mm', 'mhm'],
    autoStopOnSilence: true
  },
  migrations: {
    '1.0.0-migrateWakeWords': store => {
      const wakeWords = store.get('wakeWords');
      if (Array.isArray(wakeWords)) {
        store.set('wakeWords', {
          dictate: wakeWords
        });
      } else if (typeof wakeWords !== 'object' || wakeWords === null || !Object.prototype.hasOwnProperty.call(wakeWords, 'dictate')) {
        store.set('wakeWords', {
          dictate: ['note']
        });
      } else {
        const dictateWords = Array.isArray(wakeWords.dictate) ? wakeWords.dictate : [];
        store.set('wakeWords', { dictate: dictateWords });
      }
    }
  }
});

module.exports = { store };
