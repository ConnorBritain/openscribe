// electron_menu.js
// Application menu bar for OpenScribe

const { Menu, app, shell } = require('electron');

function createAppMenu({ createSettingsWindow, createHistoryWindow, createFileTranscribeWindow, getMainWindow }) {
  const isMac = process.platform === 'darwin';

  const template = [
    // App menu (macOS only)
    ...(isMac ? [{
      label: app.name,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        {
          label: 'Settings...',
          accelerator: 'CmdOrCtrl+,',
          click: () => createSettingsWindow()
        },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' }
      ]
    }] : []),

    // File menu
    {
      label: 'File',
      submenu: [
        {
          label: 'Transcribe File...',
          accelerator: 'CmdOrCtrl+O',
          click: () => createFileTranscribeWindow()
        },
        { type: 'separator' },
        {
          label: 'History',
          accelerator: 'CmdOrCtrl+H',
          click: () => createHistoryWindow()
        },
        { type: 'separator' },
        ...(!isMac ? [
          {
            label: 'Settings...',
            accelerator: 'CmdOrCtrl+,',
            click: () => createSettingsWindow()
          },
          { type: 'separator' },
        ] : []),
        isMac ? { role: 'close' } : { role: 'quit' }
      ]
    },

    // Edit menu
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        ...(isMac ? [
          { role: 'pasteAndMatchStyle' },
          { role: 'delete' },
          { role: 'selectAll' },
        ] : [
          { role: 'delete' },
          { type: 'separator' },
          { role: 'selectAll' }
        ])
      ]
    },

    // View menu
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },

    // Window menu
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        { type: 'separator' },
        {
          label: 'Dictation',
          click: () => {
            const win = getMainWindow();
            if (win) win.show();
          }
        },
        {
          label: 'Transcribe File',
          click: () => createFileTranscribeWindow()
        },
        {
          label: 'History',
          click: () => createHistoryWindow()
        },
        {
          label: 'Settings',
          click: () => createSettingsWindow()
        },
        { type: 'separator' },
        ...(isMac ? [
          { role: 'front' },
        ] : [
          { role: 'close' }
        ])
      ]
    },

    // Help menu
    {
      label: 'Help',
      submenu: [
        {
          label: 'OpenScribe Website',
          click: async () => {
            await shell.openExternal('https://openscribe.org');
          }
        }
      ]
    }
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

module.exports = { createAppMenu };
