// settings_contract.js
// Shared settings schema helpers backed by shared/settings_contract.json.

const contract = require('../shared/settings_contract.json');

const DEFAULT_CONTRACT = {
  version: 1,
  keys: [],
  electronDefaults: {},
  pythonDefaults: {},
  pythonConfigKeys: [],
  pythonConfigOptionalStringKeys: []
};

const SETTINGS_CONTRACT = Object.freeze({
  ...DEFAULT_CONTRACT,
  ...(contract || {})
});

const SETTINGS_SCHEMA_VERSION = Number.isFinite(Number(SETTINGS_CONTRACT.version))
  ? Number(SETTINGS_CONTRACT.version)
  : 1;

const SETTINGS_KEYS = Object.freeze(
  Array.isArray(SETTINGS_CONTRACT.keys) ? [...SETTINGS_CONTRACT.keys] : []
);

const ELECTRON_DEFAULTS = Object.freeze({
  ...(SETTINGS_CONTRACT.electronDefaults || {})
});

const PYTHON_DEFAULTS = Object.freeze({
  ...(SETTINGS_CONTRACT.pythonDefaults || {})
});

const PYTHON_CONFIG_KEYS = Object.freeze(
  Array.isArray(SETTINGS_CONTRACT.pythonConfigKeys)
    ? [...SETTINGS_CONTRACT.pythonConfigKeys]
    : []
);

const PYTHON_CONFIG_OPTIONAL_STRING_KEYS = new Set(
  Array.isArray(SETTINGS_CONTRACT.pythonConfigOptionalStringKeys)
    ? SETTINGS_CONTRACT.pythonConfigOptionalStringKeys
    : []
);

module.exports = {
  SETTINGS_CONTRACT,
  SETTINGS_SCHEMA_VERSION,
  SETTINGS_KEYS,
  ELECTRON_DEFAULTS,
  PYTHON_DEFAULTS,
  PYTHON_CONFIG_KEYS,
  PYTHON_CONFIG_OPTIONAL_STRING_KEYS
};
