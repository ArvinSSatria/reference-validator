const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const find = require('find-process');

let mainWindow;
let flaskProcess;
const FLASK_PORT = 5000;
const FLASK_HOST = '127.0.0.1';

// Determine if running in development or production
const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

// Get the correct paths
const getAppPath = () => {
  if (isDev) {
    // In development, go up one level from electron folder
    return path.join(__dirname, '..');
  } else {
    // In production, resources are extracted
    return process.resourcesPath;
  }
};

// Function to check if port is already in use
async function isPortInUse(port) {
  try {
    const list = await find('port', port);
    return list.length > 0;
  } catch (err) {
    return false;
  }
}

// Function to start Flask server
async function startFlaskServer() {
  const appPath = getAppPath();
  const pythonScript = path.join(appPath, 'run.py');
  
  console.log('Starting Flask server...');
  console.log('App path:', appPath);
  console.log('Python script:', pythonScript);

  // Check if port is already in use
  const portInUse = await isPortInUse(FLASK_PORT);
  if (portInUse) {
    console.log(`Port ${FLASK_PORT} is already in use. Skipping Flask server start.`);
    return null;
  }

  // Determine Python command (try python, python3, py)
  const pythonCommand = process.platform === 'win32' ? 'python' : 'python3';

  try {
    flaskProcess = spawn(pythonCommand, [pythonScript], {
      cwd: appPath,
      env: {
        ...process.env,
        FLASK_ENV: 'production',
        PYTHONUNBUFFERED: '1'
      }
    });

    flaskProcess.stdout.on('data', (data) => {
      console.log(`Flask: ${data}`);
    });

    flaskProcess.stderr.on('data', (data) => {
      console.error(`Flask Error: ${data}`);
    });

    flaskProcess.on('close', (code) => {
      console.log(`Flask process exited with code ${code}`);
    });

    flaskProcess.on('error', (err) => {
      console.error('Failed to start Flask process:', err);
      dialog.showErrorBox(
        'Server Error',
        'Failed to start the application server. Please make sure Python is installed.'
      );
    });

    // Wait for Flask to be ready
    await waitForServer();
    console.log('Flask server is ready!');
    
    return flaskProcess;
  } catch (error) {
    console.error('Error starting Flask:', error);
    dialog.showErrorBox(
      'Startup Error',
      `Failed to start the application: ${error.message}`
    );
    return null;
  }
}

// Function to wait for Flask server to be ready
function waitForServer(maxAttempts = 30) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      
      try {
        const http = require('http');
        const options = {
          host: FLASK_HOST,
          port: FLASK_PORT,
          path: '/',
          method: 'GET',
          timeout: 1000
        };

        const req = http.request(options, (res) => {
          clearInterval(interval);
          resolve();
        });

        req.on('error', () => {
          if (attempts >= maxAttempts) {
            clearInterval(interval);
            reject(new Error('Flask server failed to start'));
          }
        });

        req.end();
      } catch (err) {
        if (attempts >= maxAttempts) {
          clearInterval(interval);
          reject(err);
        }
      }
    }, 1000);
  });
}

// Function to create the main window
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      webSecurity: true
    },
    icon: path.join(__dirname, 'assets', 'icon.png'),
    title: 'Reference Validator',
    show: false // Don't show until ready
  });

  // Load the Flask app
  mainWindow.loadURL(`http://${FLASK_HOST}:${FLASK_PORT}`);

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Open DevTools in development mode
  if (isDev) {
    mainWindow.webContents.openDevTools();
  }

  // Handle window closed
  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // Handle external links
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    require('electron').shell.openExternal(url);
    return { action: 'deny' };
  });
}

// App ready event
app.whenReady().then(async () => {
  try {
    await startFlaskServer();
    createWindow();
  } catch (error) {
    console.error('Failed to start application:', error);
    dialog.showErrorBox(
      'Startup Failed',
      'The application failed to start. Please try again.'
    );
    app.quit();
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

// Quit when all windows are closed
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Cleanup before quit
app.on('before-quit', () => {
  if (flaskProcess) {
    console.log('Stopping Flask server...');
    flaskProcess.kill();
  }
});

// Handle any uncaught exceptions
process.on('uncaughtException', (error) => {
  console.error('Uncaught exception:', error);
  dialog.showErrorBox('Error', `An error occurred: ${error.message}`);
});
