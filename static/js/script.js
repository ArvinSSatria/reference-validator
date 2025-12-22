let currentResults = [];
let currentFilter = 'invalid';
let currentSessionId = null; // Store session_id untuk download
let socket = null; // Socket.IO connection

const form = document.getElementById('referenceForm');
const fileInput = document.getElementById('fileInput');
const fileUploadArea = document.getElementById('fileUploadArea');
const fileName = document.getElementById('fileName');
const textInput = document.getElementById('textInput');
const loadingSection = document.getElementById('loadingSection');
const resultsSection = document.getElementById('resultsSection');
const errorSection = document.getElementById('errorSection');

// Initialize Socket.IO connection
function initializeSocket() {
    socket = io();
    
    // Listen for validation progress updates
    socket.on('validation_progress', (data) => {
        console.log('Progress update:', data);
        updateProgressBar(data.progress, data.message, data.cached);
    });
    
    // Listen for PDF generation progress
    socket.on('pdf_generation_progress', (data) => {
        console.log('PDF generation update:', data);
        updatePDFStatus(data.status, data.message);
    });
    
    socket.on('connect', () => {
        console.log('Socket.IO connected');
    });
    
    socket.on('disconnect', () => {
        console.log('Socket.IO disconnected');
    });
}

// Initialize socket on page load
document.addEventListener('DOMContentLoaded', () => {
    initializeSocket();
    initializeBackToTop();
});

// Back to Top Button functionality
function initializeBackToTop() {
    const backToTopBtn = document.getElementById('backToTopBtn');
    
    if (!backToTopBtn) return;
    
    // Show/hide button based on scroll position
    window.addEventListener('scroll', () => {
        if (window.pageYOffset > 300) {
            backToTopBtn.classList.add('show');
        } else {
            backToTopBtn.classList.remove('show');
        }
    });
    
    // Smooth scroll to top when clicked
    backToTopBtn.addEventListener('click', () => {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    });
}

fileUploadArea.addEventListener('click', () => fileInput.click());
fileUploadArea.addEventListener('dragover', handleDragOver);
fileUploadArea.addEventListener('dragleave', handleDragLeave);
fileUploadArea.addEventListener('drop', handleFileDrop);

fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        displayFileName(e.target.files[0]);
        textInput.value = '';
    }
});

function handleDragOver(e) {
    e.preventDefault();
    fileUploadArea.classList.add('dragover');
}

function handleDragLeave(e) {
    e.preventDefault();
    fileUploadArea.classList.remove('dragover');
}

function handleFileDrop(e) {
    e.preventDefault();
    fileUploadArea.classList.remove('dragover');

    const files = e.dataTransfer.files;
    if (files.length > 0) {
        fileInput.files = files;
        displayFileName(files[0]);
        textInput.value = '';
    }
}

function displayFileName(file) {
    const maxSize = 16 * 1024 * 1024; // 16MB
    if (file.size > maxSize) {
        fileName.innerHTML = `<i class="fas fa-exclamation-triangle"></i> File terlalu besar (maksimal 16MB)`;
        fileName.style.color = 'var(--accent-color)';
        fileInput.value = '';
        return;
    }

    const fileSize = (file.size / 1024 / 1024).toFixed(2);
    fileName.innerHTML = `<i class="fas fa-file-check"></i> ${file.name} (${fileSize} MB)`;
    fileName.style.color = 'var(--success-color)';
}

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    await validateReferences();
});

async function validateReferences() {
    const formData = new FormData(form);

    if (!fileInput.files.length && !textInput.value.trim()) {
        showError('Mohon unggah file atau masukkan teks referensi.');
        return;
    }

    showLoading();
    hideError();
    hideResults();

    // Reset progress bar untuk real-time updates
    resetProgress();

    try {
        const response = await fetch('/api/validate', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.error) {
            showError(data.error);
            resetProgress();
            return;
        }

        // Complete progress
        updateProgressBar(100, 'Proses selesai!');
        
        // Small delay to show completion
        await new Promise(resolve => setTimeout(resolve, 500));

        currentResults = data.detailed_results || [];
        currentSessionId = data.session_id || null; // Simpan session_id
        displayResults(data);

    } catch (error) {
        console.error('Error:', error);
        showError('Terjadi kesalahan dalam menghubungi server. Silakan coba lagi.');
        resetProgress();
    } finally {
        hideLoading();
        resetProgress();
    }
}

// Update progress bar with percentage and message
function updateProgressBar(progress, message, isCached = false) {
    const progressFill = document.getElementById('progressFill');
    const progressPercentage = document.getElementById('progressPercentage');
    const progressInfo = document.getElementById('progressInfo');
    
    if (progressFill && progressPercentage && progressInfo) {
        progressFill.style.width = progress + '%';
        progressPercentage.textContent = progress + '%';
        progressInfo.textContent = message;
        
        if (isCached || message.includes('⚡') || message.includes('cache') || message.includes('cepat')) {
            progressFill.style.background = 'linear-gradient(90deg, #34495e, #5d6d7e)'; // Gradient for fast processing
        } else {
            progressFill.style.background = '#2c3e50'; // Default color
        }
    }
}

function startProgressAnimation() {
    // Deprecated - now using real-time updates via WebSocket
    // Keep for backward compatibility
    updateProgressBar(0, 'Memulai proses validasi...');
}

function resetProgress() {
    const progressFill = document.getElementById('progressFill');
    const progressPercentage = document.getElementById('progressPercentage');
    const progressInfo = document.getElementById('progressInfo');
    
    // Reset progress bar
    progressFill.style.width = '0%';
    progressPercentage.textContent = '0%';
    progressInfo.textContent = '';
}

function showLoading() {
    loadingSection.style.display = 'block';
    document.getElementById('validateBtn').disabled = true;
}

function hideLoading() {
    loadingSection.style.display = 'none';
    document.getElementById('validateBtn').disabled = false;
}

function showError(message) {
    document.getElementById('errorMessage').textContent = message;
    errorSection.style.display = 'block';
    resultsSection.style.display = 'none';
}

function hideError() {
    errorSection.style.display = 'none';
}

function hideResults() {
    resultsSection.style.display = 'none';
}

function displayResults(data) {
    const { summary, detailed_results, recommendations, from_cache } = data;
    
    // Store cache status for summary display
    window.currentResultsFromCache = from_cache || false;
    
    displaySummary(summary);
    displayRecommendations(recommendations);
    displayDetailedResults(detailed_results);
    updateTabCounts(detailed_results);

    resultsSection.style.display = 'block';
    resultsSection.scrollIntoView({ behavior: 'smooth' });

    // Enable download button HANYA jika input dari file (bukan text)
    const downloadBtn = document.getElementById('downloadBtn');
    const downloadBibtexAllBtn = document.getElementById('downloadBibtexAllBtn');
    
    if (data.has_file) {
        // Tombol download selalu enabled - PDF dibuat on-demand saat klik
        downloadBtn.style.display = 'inline-block';
        downloadBtn.disabled = false;
        downloadBtn.innerHTML = '<i class="fas fa-download"></i> Download PDF Beranotasi';
    } else {
        // Untuk text input, sembunyikan tombol download PDF
        downloadBtn.style.display = 'none';
    }
    
    // Enable download all BibTeX jika ada referensi dengan BibTeX
    const hasBibtex = detailed_results.some(r => r.bibtex_available);
    if (hasBibtex) {
        downloadBibtexAllBtn.disabled = false;
        downloadBibtexAllBtn.style.display = 'inline-block';
    } else {
        downloadBibtexAllBtn.style.display = 'none';
    }
}

// Function untuk update status PDF generation dari SocketIO
function displaySummary(summary) {
    const summaryGrid = document.getElementById('summaryGrid');
    
    summaryGrid.innerHTML = `
        <div class="summary-item">
            <div class="summary-number">${summary.total_references}</div>
            <div class="summary-label">Total Referensi</div>
        </div>
        <div class="summary-item success">
            <div class="summary-number">${summary.valid_references}</div>
            <div class="summary-label">Referensi Valid</div>
        </div>
        <div class="summary-item error">
            <div class="summary-number">${summary.invalid_references}</div>
            <div class="summary-label">Referensi Invalid</div>
        </div>
        <div class="summary-item">
            <div class="summary-number">${summary.validation_rate}%</div>
            <div class="summary-label">Tingkat Validitas</div>
        </div>
        ${summary.distribution_analysis ? `
        <div class="summary-item ${summary.distribution_analysis.meets_journal_requirement ? 'success' : 'warning'}">
            <div class="summary-number">${summary.distribution_analysis.journal_percentage}%</div>
            <div class="summary-label">Artikel Jurnal</div>
        </div>
        ` : ''}
    `;
}

function displayRecommendations(recommendations) {
    const recommendationsList = document.getElementById('recommendationsList');
    if (!recommendations || recommendations.length === 0) {
        recommendationsList.innerHTML = '<li>Tidak ada rekomendasi khusus.</li>';
        return;
    }
    recommendationsList.innerHTML = recommendations.map(rec => `<li>${rec}</li>`).join('');
}

function displayDetailedResults(results) {
    const detailedResultsContainer = document.getElementById('detailedResults');
    if (!results || results.length === 0) {
        detailedResultsContainer.innerHTML = '<p>Tidak ada hasil detail yang tersedia.</p>';
        return;
    }
    const filteredResults = filterResults(results, currentFilter);
    detailedResultsContainer.innerHTML = filteredResults.map((result, index) => createReferenceItemHTML(result, index)).join('');
}

function createReferenceItemHTML(result, index) {
    const statusClass = result.status === 'valid' ? 'valid' : 'invalid';
    const statusIcon = result.status === 'valid' ? 'fas fa-check-circle' : 'fas fa-times-circle';
    const statusText = result.status.toUpperCase();

    let validationDetailsHTML = '';
    if (result.validation_details) {
        validationDetailsHTML = `
            <div class="validation-badge ${result.validation_details.format_correct ? 'badge-valid' : 'badge-invalid'}">Format: ${result.validation_details.format_correct ? '✓' : '✗'}</div>
            <div class="validation-badge ${result.validation_details.complete ? 'badge-valid' : 'badge-invalid'}">Lengkap: ${result.validation_details.complete ? '✓' : '✗'}</div>
            <div class="validation-badge ${result.validation_details.year_recent ? 'badge-valid' : 'badge-invalid'}">Tahun: ${result.validation_details.year_recent ? '✓' : '✗'}</div>
        `;
    }

    let indexBadgeHTML = '';
    // Tampilkan badge untuk Scimago dan/atau Scopus
    if (result.is_indexed_scimago) {
        indexBadgeHTML += `
        <div class="validation-badge badge-scimago">
            <i class="fas fa-star"></i> Terindeks ScimagoJR
        </div>`;
    }
    
    if (result.is_indexed_scopus) {
        indexBadgeHTML += `
        <div class="validation-badge badge-scopus">
            <i class="fas fa-certificate"></i> Terindeks Scopus
        </div>`;
    }

    let databaseLinksHTML = '';
    if (result.scimago_link) {
        databaseLinksHTML += `
            <p class="meta-info">
                <strong>Link ScimagoJR:</strong> 
                <a href="${result.scimago_link}" target="_blank" rel="noopener noreferrer" class="scimago-link">
                    Verifikasi di ScimagoJR <i class="fas fa-external-link-alt"></i>
                </a>
            </p>`;
    }
    
    if (result.scopus_link) {
        databaseLinksHTML += `
            <p class="meta-info">
                <strong>Link Scopus:</strong> 
                <a href="${result.scopus_link}" target="_blank" rel="noopener noreferrer" class="scopus-link">
                    Verifikasi di Scopus <i class="fas fa-external-link-alt"></i>
                </a>
            </p>`;
    }

    let quartileHTML = '';
    if (result.is_indexed_scimago) {
        if (result.quartile && result.quartile !== '-') {
            quartileHTML = `
            <p class="meta-info">
                <strong>Kuartil ScimagoJR:</strong> ${result.quartile}
            </p>`;
        } else {
            quartileHTML = `
            <p class="meta-info">
                <strong>Kuartil ScimagoJR:</strong> Tidak Tersedia
            </p>`;
        }
    }

    // BibTeX Download Button
    let bibtexHTML = '';
    if (result.bibtex_available) {
        const linkClass = result.bibtex_partial ? 'bibtex-link partial' : 'bibtex-link';
        const linkText = result.bibtex_partial ? 'Download .bib (Partial)' : 'Download BibTeX';
        const warningHTML = result.bibtex_warning ? `<p class="bibtex-warning"><i class="fas fa-exclamation-triangle"></i> ${result.bibtex_warning}</p>` : '';
        
        bibtexHTML = `
            ${warningHTML}
            <p class="meta-info">
                <strong>Download:</strong> 
                <a href="#" class="${linkClass}" onclick="event.preventDefault(); downloadBibTeX(${result.reference_number});">
                    ${linkText} <i class="fas fa-download"></i>
                </a>
            </p>`;
    }

    return `
        <div class="reference-item ${statusClass}">
            <div class="reference-status ${statusClass === 'valid' ? 'status-valid' : 'status-invalid'}">
                <i class="${statusIcon}"></i>
                Referensi #${result.reference_number || index + 1} - ${statusText}
            </div>
            <div class="reference-text">${result.reference_text}</div>
            
            <div class="details-grid">
                ${validationDetailsHTML}
                ${indexBadgeHTML}
            </div>

            <p class="meta-info"><strong>Sumber Terdeteksi:</strong> ${result.parsed_journal || 'Tidak terdeteksi'}</p>
            <p class="meta-info"><strong>Jenis Terdeteksi:</strong> ${result.reference_type || 'Tidak terdeteksi'}</p>
            
            ${databaseLinksHTML}
            ${quartileHTML}
            ${bibtexHTML}
            
            <div class="feedback"><i class="fas fa-comment-alt"></i> ${result.feedback}</div>
        </div>`;
}

function updateTabCounts(results) {
    const validCount = results.filter(r => r.status === 'valid').length;
    const invalidCount = results.filter(r => r.status !== 'valid').length;
    const indexedCount = results.filter(r => r.is_indexed === true).length;
    const allCount = results.length;
    document.getElementById('validCount').textContent = validCount;
    document.getElementById('invalidCount').textContent = invalidCount;
    document.getElementById('indexedCount').textContent = indexedCount;
    document.getElementById('allCount').textContent = allCount;
}

function showTab(event, filter) {
    currentFilter = filter;
    document.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
    event.currentTarget.classList.add('active');
    displayDetailedResults(currentResults);
}

function filterResults(results, filter) {
    if (filter === 'valid') return results.filter(r => r.status === 'valid');
    if (filter === 'invalid') return results.filter(r => r.status !== 'valid');
    if (filter === 'indexed') return results.filter(r => r.is_indexed === true);
    if (filter === 'all') return results;
    return results;
}

textInput.addEventListener('input', () => {
    if (textInput.value.trim()) {
        fileInput.value = '';
        fileName.innerHTML = '';
    }
});

const downloadBtn = document.getElementById('downloadBtn');
downloadBtn.addEventListener('click', async () => {
    // Kirim session_id sebagai query parameter
    const url = currentSessionId 
        ? `/api/download_report?session_id=${currentSessionId}` 
        : '/api/download_report';
    
    try {
        downloadBtn.disabled = true;
        downloadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating PDF...';
        
        const response = await fetch(url);
        
        if (!response.ok) {
            // Jika error, coba parse JSON error message
            const errorData = await response.json();
            throw new Error(errorData.error || 'Download failed');
        }
        
        // Download berhasil, ambil blob
        const blob = await response.blob();
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = 'annotated_report.pdf';
        
        if (contentDisposition) {
            const matches = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(contentDisposition);
            if (matches && matches[1]) {
                filename = matches[1].replace(/['"]/g, '');
            }
        }
        
        // Create download link
        const blobUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(blobUrl);
        
        downloadBtn.disabled = false;
        downloadBtn.innerHTML = '<i class="fas fa-download"></i> Download PDF Beranotasi';
    } catch (error) {
        console.error('Download error:', error);
        alert(`Gagal download PDF: ${error.message}`);
        downloadBtn.disabled = false;
        downloadBtn.innerHTML = '<i class="fas fa-download"></i> Download PDF Beranotasi';
    }
});

const downloadBibtexAllBtn = document.getElementById('downloadBibtexAllBtn');
downloadBibtexAllBtn.addEventListener('click', () => {
    downloadAllBibTeX();
});

// Function untuk download BibTeX
function downloadBibTeX(refNumber) {
    if (currentSessionId) {
        window.open(`/api/download_bibtex/${refNumber}?session_id=${currentSessionId}`, '_blank');
    } else {
        // Fallback ke cookie-based session (backward compatibility)
        window.open(`/api/download_bibtex/${refNumber}`, '_blank');
    }
}

// Function untuk download semua BibTeX sekaligus
function downloadAllBibTeX() {
    if (!currentResults || currentResults.length === 0) {
        alert('Tidak ada hasil referensi yang tersedia.');
        return;
    }
    
    // Filter hanya referensi yang punya BibTeX
    const referencesWithBibtex = currentResults.filter(r => r.bibtex_available && r.bibtex_string);
    
    if (referencesWithBibtex.length === 0) {
        alert('Tidak ada referensi dengan BibTeX yang tersedia untuk diunduh.');
        return;
    }
    
    // Gabungkan semua BibTeX entries
    const allBibtex = referencesWithBibtex.map(r => r.bibtex_string).join('\n\n');
    
    // Buat file dan download
    const blob = new Blob([allBibtex], { type: 'text/plain;charset=utf-8' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    
    // Generate filename dengan timestamp
    const timestamp = new Date().toISOString().slice(0, 10);
    link.download = `references_${timestamp}.bib`;
    
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
    
    // Log info
    console.log(`Downloaded ${referencesWithBibtex.length} BibTeX entries`);
}