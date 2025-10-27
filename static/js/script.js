let currentResults = [];
let currentFilter = 'indexed';

const form = document.getElementById('referenceForm');
const fileInput = document.getElementById('fileInput');
const fileUploadArea = document.getElementById('fileUploadArea');
const fileName = document.getElementById('fileName');
const textInput = document.getElementById('textInput');
const loadingSection = document.getElementById('loadingSection');
const resultsSection = document.getElementById('resultsSection');
const errorSection = document.getElementById('errorSection');

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
    
    // Start progress animation
    startProgressAnimation();

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
        completeProgress();
        
        // Small delay to show completion
        await new Promise(resolve => setTimeout(resolve, 500));

        currentResults = data.detailed_results || [];
        displayResults(data);

    } catch (error) {
        console.error('Error:', error);
        showError('Terjadi kesalahan dalam menghubungi server. Silakan coba lagi.');
        resetProgress();
    } finally {
        hideLoading();
    }
}

function startProgressAnimation() {
    const steps = [
        { id: 'step1', duration: 2000, progress: 25, label: 'Mengekstrak referensi dari dokumen...' },
        { id: 'step2', duration: 3000, progress: 50, label: 'Memisahkan entri referensi dengan AI...' },
        { id: 'step3', duration: 5000, progress: 75, label: 'Menganalisis setiap referensi...' },
        { id: 'step4', duration: 2000, progress: 95, label: 'Memvalidasi dengan database ScimagoJR...' }
    ];
    
    let currentStep = 0;
    
    function animateStep() {
        if (currentStep >= steps.length) return;
        
        const step = steps[currentStep];
        const stepElement = document.getElementById(step.id);
        const progressFill = document.getElementById('progressFill');
        const progressPercentage = document.getElementById('progressPercentage');
        const progressInfo = document.getElementById('progressInfo');
        
        // Mark current step as active
        stepElement.classList.add('active');
        
        // Update progress bar
        progressFill.style.width = step.progress + '%';
        progressPercentage.textContent = step.progress + '%';
        progressInfo.textContent = step.label;
        
        // After duration, mark as completed and move to next
        setTimeout(() => {
            stepElement.classList.remove('active');
            stepElement.classList.add('completed');
            currentStep++;
            animateStep();
        }, step.duration);
    }
    
    animateStep();
}

function completeProgress() {
    const progressFill = document.getElementById('progressFill');
    const progressPercentage = document.getElementById('progressPercentage');
    const progressInfo = document.getElementById('progressInfo');
    
    // Complete all steps
    ['step1', 'step2', 'step3', 'step4'].forEach(id => {
        const element = document.getElementById(id);
        element.classList.remove('active');
        element.classList.add('completed');
    });
    
    // Set to 100%
    progressFill.style.width = '100%';
    progressPercentage.textContent = '100%';
    progressInfo.textContent = 'Proses selesai! Menampilkan hasil...';
}

function resetProgress() {
    const progressFill = document.getElementById('progressFill');
    const progressPercentage = document.getElementById('progressPercentage');
    const progressInfo = document.getElementById('progressInfo');
    
    // Reset all steps
    ['step1', 'step2', 'step3', 'step4'].forEach(id => {
        const element = document.getElementById(id);
        element.classList.remove('active', 'completed');
    });
    
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
    const { summary, detailed_results, recommendations } = data;
    displaySummary(summary);
    displayRecommendations(recommendations);
    displayDetailedResults(detailed_results);
    updateTabCounts(detailed_results);

    resultsSection.style.display = 'block';
    resultsSection.scrollIntoView({ behavior: 'smooth' });

    document.getElementById('downloadBtn').disabled = false;
}

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
    // Tampilkan badge ini JIKA SUMBERNYA TERINDEKS, apa pun tipenya
    if (result.is_indexed) {
        indexBadgeHTML = `
        <div class="validation-badge badge-valid">
            Terindeks Scimago: ✓
        </div>`;
    }

    let scimagoLinkHTML = '';
    if (result.scimago_link) {
        scimagoLinkHTML = `
            <p class="meta-info">
                <strong>Link Scimago:</strong> 
                <a href="${result.scimago_link}" target="_blank" rel="noopener noreferrer" class="scimago-link">
                    Verifikasi di ScimagoJR <i class="fas fa-external-link-alt"></i>
                </a>
            </p>`;
    }

    let quartileHTML = '';
    if (result.is_indexed) {
        if (result.quartile && result.quartile !== '-') {
            quartileHTML = `
            <p class="meta-info">
                <strong>Kuartil:</strong> 
                <span class="quartile-tag quartile-${result.quartile.toLowerCase()}">${result.quartile}</span>
            </p>`;
        } else {
            quartileHTML = `
            <p class="meta-info">
                <strong>Kuartil:</strong> Tidak Tersedia
            </p>`;
        }
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
            
            ${scimagoLinkHTML}
            ${quartileHTML} 
            
            <div class="feedback"><i class="fas fa-comment-alt"></i> ${result.feedback}</div>
        </div>`;
}

function updateTabCounts(results) {
    const validCount = results.filter(r => r.status === 'valid').length;
    const invalidCount = results.filter(r => r.status !== 'valid').length;
    const indexedCount = results.filter(r => r.is_indexed === true).length;
    document.getElementById('validCount').textContent = validCount;
    document.getElementById('invalidCount').textContent = invalidCount;
    document.getElementById('indexedCount').textContent = indexedCount;
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
    return results;
}

textInput.addEventListener('input', () => {
    if (textInput.value.trim()) {
        fileInput.value = '';
        fileName.innerHTML = '';
    }
});

const downloadBtn = document.getElementById('downloadBtn');
downloadBtn.addEventListener('click', () => {
    // Cukup buka URL endpoint GET di tab baru
    window.open('/api/download_report', '_blank');
});