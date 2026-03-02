// python_config_payload.js
// Shared helper to build CONFIG payloads sent to the Python backend.

const {
  ELECTRON_DEFAULTS,
  PYTHON_CONFIG_KEYS,
  PYTHON_CONFIG_OPTIONAL_STRING_KEYS
} = require('./settings_contract');

function addNonEmptyStringField(target, field, value) {
  if (typeof value === 'string' && value.trim()) {
    target[field] = value;
  }
}

function buildPythonConfigFromStore(store, options = {}) {
  const {
    overrides = {},
    includeSelectedAsrModel = true,
    includeSecondaryAsrModel = true,
  } = options;

  const payload = {};
  for (const key of PYTHON_CONFIG_KEYS) {
    if (key === 'selectedAsrModel' && !includeSelectedAsrModel) {
      continue;
    }
    if (key === 'secondaryAsrModel' && !includeSecondaryAsrModel) {
      continue;
    }
    const defaultValue = Object.prototype.hasOwnProperty.call(ELECTRON_DEFAULTS, key)
      ? ELECTRON_DEFAULTS[key]
      : undefined;
    const value = store.get(key, defaultValue);

    // Secondary ASR must always be explicit so Python can clear stale in-memory state
    // when user selects "None" in settings.
    if (key === 'secondaryAsrModel') {
      payload[key] = (typeof value === 'string' && value.trim()) ? value : null;
      continue;
    }

    if (PYTHON_CONFIG_OPTIONAL_STRING_KEYS.has(key)) {
      addNonEmptyStringField(payload, key, value);
      continue;
    }
    payload[key] = value;
  }

  return {
    ...payload,
    ...overrides,
  };
}

module.exports = {
  buildPythonConfigFromStore,
};
