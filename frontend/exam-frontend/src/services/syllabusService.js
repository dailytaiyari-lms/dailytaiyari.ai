import api from './api'

const BASE = '/tenant-admin/intelligence/syllabus'
const data = (promise) => promise.then((response) => response.data)

export const syllabusService = {
  getTree: (courseId) => data(api.get(`${BASE}/courses/${courseId}/tree/`)),
  estimateBuild: (courseId, body = {}) => data(api.post(`${BASE}/courses/${courseId}/tree/estimate/`, body)),
  startBuild: (courseId, body = {}) => data(api.post(`${BASE}/courses/${courseId}/tree/build/`, body)),
  mapExam: (courseId, body) => data(api.post(`${BASE}/courses/${courseId}/tree/exam/`, body)),
  addNode: (courseId, body) => data(api.post(`${BASE}/courses/${courseId}/nodes/`, body)),
  updateNode: (nodeId, body) => data(api.patch(`${BASE}/nodes/${nodeId}/`, body)),
  mergeNode: (nodeId, into) => data(api.post(`${BASE}/nodes/${nodeId}/merge/`, { into })),
  setSkillPacks: (courseId, packs) => data(api.patch(`${BASE}/courses/${courseId}/skill-packs/`, { packs })),
  estimateTagging: (courseId) => data(api.post(`${BASE}/courses/${courseId}/tagging/estimate/`, {})),
  startTagging: (courseId) => data(api.post(`${BASE}/courses/${courseId}/tagging/run/`, {})),
  getJob: (jobId) => data(api.get(`${BASE}/jobs/${jobId}/`)),
  getReview: (params) => data(api.get(`${BASE}/review/`, { params })),
  getReviewRow: (id) => data(api.get(`${BASE}/review/${id}/`)),
  acceptReview: (id) => data(api.post(`${BASE}/review/${id}/accept/`)),
  bulkAccept: (ids) => data(api.post(`${BASE}/review/bulk-accept/`, { ids })),
  saveTags: (id, body) => data(api.put(`${BASE}/review/${id}/`, body)),
  retag: (id) => data(api.post(`${BASE}/review/${id}/retag/`)),
  addToTree: (id, topic) => data(api.post(`${BASE}/review/${id}/add-to-tree/`, topic ? { topic } : {})),
  getItemTags: (kind, id) => data(api.get(`${BASE}/items/${kind}/${id}/tags/`)),
}

// "Thing went wrong" text from a DRF error response.
export const errorText = (error) => error?.response?.data?.error || 'Something went wrong — try again.'
