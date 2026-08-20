const BASE = import.meta.env.VITE_API_BASE || ''

export const api = {
  async createRun(files, rulebook = '') {
    const form = new FormData()
    if (rulebook) form.append('rulebook', rulebook)
    files.forEach(f => form.append('files', f))
    const r = await fetch(`${BASE}/api/runs`, { method: 'POST', body: form })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },

  async getRunStatus(runId) {
    const r = await fetch(`${BASE}/api/runs/${runId}`)
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },

  async getRunLogs(runId) {
    const r = await fetch(`${BASE}/api/runs/${runId}/logs`)
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },

  async getReviewItems(runId, stage) {
    const url = stage
      ? `${BASE}/api/runs/${runId}/review?stage=${stage}`
      : `${BASE}/api/runs/${runId}/review`
    const r = await fetch(url)
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },

  async approveItem(runId, itemId, reviewerNote = '') {
    const r = await fetch(`${BASE}/api/runs/${runId}/review/${itemId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reviewer_note: reviewerNote }),
    })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },

  async rejectItem(runId, itemId, reviewerNote = '') {
    const r = await fetch(`${BASE}/api/runs/${runId}/review/${itemId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reviewer_note: reviewerNote }),
    })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },

  async resumeRun(runId, stage) {
    const r = await fetch(`${BASE}/api/runs/${runId}/resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stage }),
    })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },

  async getReport(runId) {
    const r = await fetch(`${BASE}/api/runs/${runId}/report`)
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },

  async getCost(runId) {
    const r = await fetch(`${BASE}/api/runs/${runId}/cost`)
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },

  async addWatchedDocs(runId, files) {
    const form = new FormData()
    files.forEach(f => form.append('files', f))
    const r = await fetch(`${BASE}/api/runs/${runId}/watch`, { method: 'POST', body: form })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },
}
