# Reference Validator - Desktop Application

Aplikasi desktop untuk Reference Validator menggunakan Electron.js yang membungkus Flask backend.

## Prerequisites

Sebelum menjalankan aplikasi desktop, pastikan sudah terinstall:

1. **Node.js** (versi 18 atau lebih baru)
   - Download dari: https://nodejs.org/

2. **Python** (versi 3.8 atau lebih baru)
   - Pastikan Python sudah ada di PATH

3. **Dependencies Python**
   - Install semua requirements: `pip install -r ../requirements.txt`

## Setup Development

1. **Install dependencies Electron:**
   ```bash
   cd electron
   npm install
   ```

2. **Jalankan aplikasi dalam mode development:**
   ```bash
   npm start
   ```

   Aplikasi akan:
   - Menjalankan Flask server di `http://127.0.0.1:5000`
   - Membuka window Electron yang load URL Flask
   - Otomatis buka DevTools untuk debugging

## Build Aplikasi Desktop

### Build untuk Windows:
```bash
npm run build:win
```

Akan menghasilkan:
- `dist/Reference Validator-{version}-win-x64.exe` (installer NSIS)
- `dist/Reference Validator-{version}-win-x64-portable.exe` (portable version)

### Build untuk macOS:
```bash
npm run build:mac
```

Akan menghasilkan:
- `dist/Reference Validator-{version}-mac-x64.dmg`
- `dist/Reference Validator-{version}-mac-arm64.dmg` (Apple Silicon)

### Build untuk Linux:
```bash
npm run build:linux
```

Akan menghasilkan:
- `dist/Reference Validator-{version}-linux-x64.AppImage`
- `dist/Reference Validator-{version}-linux-x64.deb`

### Build semua platform:
```bash
npm run build
```

## Struktur Folder

```
electron/
├── main.js                    # Main process (backend Electron)
├── preload.js                 # Preload script (security)
├── package.json               # Dependencies & scripts
├── electron-builder.json      # Build configuration
├── assets/                    # Icons & resources
│   ├── icon.png              # Linux icon (512x512)
│   ├── icon.ico              # Windows icon
│   └── icon.icns             # macOS icon
└── dist/                      # Build output (generated)
```

## Cara Kerja

1. **Main Process (`main.js`)**:
   - Start Flask server menggunakan `spawn()`
   - Tunggu server ready (max 30 detik)
   - Buat BrowserWindow dan load `http://127.0.0.1:5000`
   - Handle lifecycle events (close, quit, etc)

2. **Renderer Process**:
   - Load aplikasi Flask seperti browser biasa
   - Semua interaksi UI tetap menggunakan HTML/CSS/JS dari Flask

3. **Preload Script (`preload.js`)**:
   - Bridge antara main & renderer process
   - Expose API yang aman ke renderer
   - Context isolation untuk keamanan

## Custom Icons

Untuk mengganti icon aplikasi:

1. **Windows**: Siapkan `icon.ico` (256x256 atau multiple sizes)
2. **macOS**: Siapkan `icon.icns` (512x512@2x atau iconset)
3. **Linux**: Siapkan `icon.png` (512x512 PNG)

Simpan di folder `electron/assets/`

Tool untuk membuat icons:
- Windows: [icoconverter.com](https://icoconvert.com/)
- macOS: Gunakan `iconutil` command atau online converter
- Linux: PNG standard works fine

## Environment Variables

Aplikasi desktop menggunakan environment berikut:

- `FLASK_ENV=production` - Otomatis set saat running via Electron
- `PYTHONUNBUFFERED=1` - Agar log Flask muncul realtime

## Troubleshooting

### Port 5000 sudah digunakan
Aplikasi akan detect otomatis dan skip start Flask jika port sudah digunakan.

### Python tidak ditemukan
Pastikan Python ada di PATH. Test dengan: `python --version`

### Build gagal
1. Hapus `node_modules` dan `package-lock.json`
2. Jalankan `npm install` lagi
3. Coba build ulang

### Aplikasi tidak load
1. Check console log (DevTools)
2. Pastikan Flask server berhasil start
3. Test akses `http://127.0.0.1:5000` di browser biasa

## Notes

- **Development**: Flask server akan restart manual, Electron perlu restart juga
- **Production**: Aplikasi akan bundle semua dependencies, jadi ukuran besar (~100-200MB)
- **Updates**: Untuk update, user perlu download dan install versi baru
- **Railway**: Deployment web tidak terpengaruh, tetap berjalan normal

## Distribution

File installer hasil build bisa didistribusikan langsung:

- **Windows**: NSIS installer atau portable EXE
- **macOS**: DMG file (drag-drop to Applications)
- **Linux**: AppImage (no install needed) atau DEB package

User tidak perlu install Python atau dependencies apapun!

## License

Same as main project (check root LICENSE file)
