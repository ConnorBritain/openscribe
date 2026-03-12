document.addEventListener('DOMContentLoaded', () => {
  const liveDictationBtn = document.getElementById('btn-live-dictation');
  const fileTranscribeBtn = document.getElementById('btn-file-transcribe');

  liveDictationBtn.addEventListener('click', () => {
    window.homeAPI.openLiveDictation();
  });

  fileTranscribeBtn.addEventListener('click', () => {
    window.homeAPI.openFileTranscribe();
  });
});
