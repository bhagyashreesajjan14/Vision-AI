/**
 * Real-time polling script for Batch Inspection progress.
 */
document.addEventListener('DOMContentLoaded', function () {
    const batchContainer = document.getElementById('batchStatusContainer');
    if (!batchContainer) return;

    const batchId = batchContainer.getAttribute('data-batch-id');
    if (!batchId) return;

    const progressBar = document.getElementById('batchProgressBar');
    const badgeQueued = document.getElementById('countQueued');
    const badgeProcessing = document.getElementById('countProcessing');
    const badgeCompleted = document.getElementById('countCompleted');
    const badgeFailed = document.getElementById('countFailed');
    const statusAlert = document.getElementById('batchStatusAlert');

    let pollInterval = null;

    function pollStatus() {
        fetch(`/api/batches/${batchId}/status/`, {
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => {
            if (!response.ok) throw new Error(`HTTP error ${response.status}`);
            return response.json();
        })
        .then(data => {
            const total = data.total_items || 1;
            const completed = data.completed_count || 0;
            const failed = data.failed_count || 0;
            const processing = data.processing_count || 0;
            const queued = data.queued_count || 0;

            const finishedItems = completed + failed;
            const percent = Math.round((finishedItems / total) * 100);

            if (progressBar) {
                progressBar.style.width = `${percent}%`;
                progressBar.textContent = `${percent}%`;
            }

            if (badgeQueued) badgeQueued.textContent = queued;
            if (badgeProcessing) badgeProcessing.textContent = processing;
            if (badgeCompleted) badgeCompleted.textContent = completed;
            if (badgeFailed) badgeFailed.textContent = failed;

            // Update item rows
            if (data.items && Array.isArray(data.items)) {
                data.items.forEach(item => {
                    const row = document.getElementById(`item-row-${item.id}`);
                    if (row) {
                        const statusBadge = row.querySelector('.item-status-badge');
                        const predCell = row.querySelector('.item-prediction-cell');
                        const confCell = row.querySelector('.item-confidence-cell');

                        if (statusBadge) {
                            statusBadge.className = `badge item-status-badge badge-status-${item.status.toLowerCase()}`;
                            statusBadge.textContent = item.status;
                        }

                        if (predCell) {
                            if (item.status === 'COMPLETED' && item.predicted_class) {
                                const badgeClass = item.predicted_class === 'Defective' ? 'badge-pred-defective' : 'badge-pred-normal';
                                predCell.innerHTML = `<span class="badge ${badgeClass}">${item.predicted_class}</span>`;
                            } else if (item.status === 'FAILED') {
                                predCell.innerHTML = `<span class="text-danger small" title="${item.failure_reason || ''}"><i class="bi bi-exclamation-triangle"></i> Rejected</span>`;
                            } else {
                                predCell.innerHTML = `<span class="text-muted small"><span class="spinner-border spinner-border-sm me-1"></span> Pending</span>`;
                            }
                        }

                        if (confCell) {
                            if (item.status === 'COMPLETED' && item.confidence !== null) {
                                const confPct = (item.confidence * 100).toFixed(1);
                                confCell.innerHTML = `<strong>${confPct}%</strong>`;
                            } else if (item.status === 'FAILED') {
                                confCell.innerHTML = `<span class="badge bg-danger">Invalid</span>`;
                            }
                        }
                    }
                });
            }

            // Check if finished
            if (data.is_finished) {
                if (statusAlert) {
                    statusAlert.className = 'alert alert-success d-flex align-items-center mb-4';
                    statusAlert.innerHTML = `<i class="bi bi-check-circle-fill fs-4 me-2"></i><div><strong>Batch Processing Complete:</strong> ${completed} succeeded, ${failed} failed.</div>`;
                }
                if (progressBar) {
                    progressBar.classList.remove('progress-bar-animated', 'progress-bar-striped');
                    progressBar.classList.add('bg-success');
                }
                clearInterval(pollInterval);
            }
        })
        .catch(err => {
            console.error('Error polling batch status:', err);
        });
    }

    // Initial poll and set interval every 1.5 seconds
    pollStatus();
    pollInterval = setInterval(pollStatus, 1500);
});

