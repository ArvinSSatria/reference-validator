// Preload script for Electron
// This script runs in the renderer process before web content loads
// It has access to both DOM APIs and Node.js APIs

const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods that allow the renderer process to use
// ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electron', {
  // Example: expose methods if needed in the future
  platform: process.platform,
  versions: {
    node: process.versions.node,
    chrome: process.versions.chrome,
    electron: process.versions.electron
  }
});

// Add any additional API exposure here if needed
console.log('Preload script loaded');
