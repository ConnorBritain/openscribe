const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

const HISTORY_LOG_PATH = path.resolve(process.cwd(), 'data/history/history.jsonl');

function readHistoryRecords() {
  if (!fs.existsSync(HISTORY_LOG_PATH)) {
    return [];
  }
  const content = fs.readFileSync(HISTORY_LOG_PATH, 'utf8');
  const lines = content.split(/\r?\n/).filter((line) => line.trim().length > 0);
  const records = [];
  for (const line of lines) {
    try {
      const record = JSON.parse(line);
      records.push(record);
    } catch (error) {
      // Skip malformed lines
    }
  }
  return records;
}

function attachAudioPaths(record) {
  if (!record || !record.audioFile) {
    return { ...record, audioFilePath: null, audioFileUrl: null };
  }
  const absolutePath = path.resolve(process.cwd(), record.audioFile);
  const fileUrl = pathToFileURL(absolutePath).href;
  return { ...record, audioFilePath: absolutePath, audioFileUrl: fileUrl };
}

function getHistorySummary() {
  const records = readHistoryRecords();
  records.sort((a, b) => {
    const aDate = new Date(a.createdAt || 0).getTime();
    const bDate = new Date(b.createdAt || 0).getTime();
    return bDate - aDate;
  });
  return records.map((record) => ({
    id: record.id,
    createdAt: record.createdAt,
    durationSeconds: record.durationSeconds,
    metadata: record.metadata || {},
    audioAvailable: Boolean(record.audioFile),
    transcriptPreview: (record.processedTranscript || record.transcript || '').slice(0, 600),
    speakerName: (record.metadata && record.metadata.speakerName) || null
  }));
}

function getHistoryEntry(id) {
  if (!id) {
    return null;
  }
  const records = readHistoryRecords();
  const record = records.find((entry) => entry.id === id);
  if (!record) {
    return null;
  }
  return attachAudioPaths(record);
}

function deleteHistoryEntry(id) {
  if (!id) {
    return { success: false, error: 'Missing entry id.' };
  }

  const records = readHistoryRecords();
  const recordIndex = records.findIndex((entry) => entry.id === id);
  if (recordIndex === -1) {
    return { success: false, error: 'Entry not found.' };
  }

  const target = records[recordIndex];

  // Remove associated audio file if present
  if (target?.audioFile) {
    try {
      const absoluteAudioPath = path.resolve(process.cwd(), target.audioFile);
      const historyDir = path.dirname(HISTORY_LOG_PATH);
      if (absoluteAudioPath.startsWith(historyDir) && fs.existsSync(absoluteAudioPath)) {
        fs.unlinkSync(absoluteAudioPath);
      }
    } catch (error) {
      console.warn('[HistoryService] Unable to remove audio file:', error);
    }
  }

  const remaining = records.filter((entry) => entry.id !== id);
  const serialized = remaining.map((entry) => JSON.stringify(entry)).join('\n');
  fs.writeFileSync(HISTORY_LOG_PATH, serialized ? `${serialized}\n` : '', 'utf8');

  return { success: true, deletedId: id };
}

module.exports = {
  getHistorySummary,
  getHistoryEntry,
  deleteHistoryEntry
};
