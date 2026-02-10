// asr_models.js
// Shared ASR model definitions used across main window and settings.

export const ASR_MODELS = [
  { id: 'mlx-community/whisper-large-v3-turbo', name: 'Whisper (large-v3-turbo)' },
  { id: 'mlx-community/parakeet-tdt-0.6b-v2', name: 'Parakeet-TDT-0.6B-v2' },
  { id: 'mlx-community/parakeet-tdt-0.6b-v3', name: 'Parakeet-TDT-0.6B-v3' },
  { id: 'mlx-community/Voxtral-Mini-3B-2507-bf16', name: 'Voxtral Mini 3B (bf16)' },
  { id: 'google/medasr', name: 'MedASR (Medical)' },
  { id: 'apple:speech:ondevice', name: 'Apple Speech (on-device)' }
];

export function getModelName(modelId) {
  const model = ASR_MODELS.find(m => m.id === modelId);
  return model ? model.name : modelId;
}
