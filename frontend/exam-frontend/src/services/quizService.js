import api from './api'

export const quizService = {
  // Get quizzes with filters
  getQuizzes: async (params = {}) => {
    const response = await api.get('/quiz/quizzes/', { params })
    return response.data
  },

  // Get filter options
  getFilterOptions: async () => {
    const response = await api.get('/quiz/quizzes/filter_options/')
    return response.data
  },

  // Get quiz details
  getQuizDetails: async (quizId) => {
    const response = await api.get(`/quiz/quizzes/${quizId}/`)
    return response.data
  },

  // Get daily challenge
  getDailyChallenge: async (courseId) => {
    const response = await api.get('/quiz/quizzes/daily_challenge/', {
      params: courseId ? { course_id: courseId } : {},
    })
    return response.data
  },

  // Start quiz
  startQuiz: async (quizId) => {
    const response = await api.post(`/quiz/quizzes/${quizId}/start/`)
    return response.data
  },

  reportProctoringEvent: async (quizId, eventType) => {
    const response = await api.post(`/quiz/quizzes/${quizId}/proctoring_event/`, {
      event_type: eventType,
    })
    return response.data
  },

  // Submit quiz
  submitQuiz: async (quizId, data) => {
    const response = await api.post(`/quiz/quizzes/${quizId}/submit/`, data)
    return response.data
  },

  // Get quiz attempts
  getAttempts: async () => {
    const response = await api.get('/quiz/attempts/')
    return response.data
  },

  // Get recent attempts
  getRecentAttempts: async () => {
    const response = await api.get('/quiz/attempts/recent/')
    return response.data
  },

  // Get attempt details
  getAttemptDetails: async (attemptId) => {
    const response = await api.get(`/quiz/attempts/${attemptId}/`)
    return response.data
  },

  // Get my attempts for a specific quiz
  getQuizAttempts: async (quizId) => {
    const response = await api.get(`/quiz/quizzes/${quizId}/my_attempts/`)
    return response.data
  },

  // Get attempt review (with answers and correct options)
  getAttemptReview: async (attemptId) => {
    const response = await api.get(`/quiz/attempts/${attemptId}/review/`)
    return response.data
  },

  // Mock Tests
  getMockTests: async (params = {}) => {
    const response = await api.get('/quiz/mock-tests/', { params })
    return response.data
  },

  // Get mock test filter options
  getMockTestFilterOptions: async () => {
    const response = await api.get('/quiz/mock-tests/filter_options/')
    return response.data
  },

  getMockTestDetails: async (testId) => {
    const response = await api.get(`/quiz/mock-tests/${testId}/`)
    return response.data
  },

  startMockTest: async (testId) => {
    const response = await api.post(`/quiz/mock-tests/${testId}/start/`)
    return response.data
  },

  submitMockTest: async (testId, data) => {
    const response = await api.post(`/quiz/mock-tests/${testId}/submit/`, data)
    return response.data
  },

  // Get my attempts for a specific mock test
  getMockTestAttempts: async (testId) => {
    const response = await api.get(`/quiz/mock-tests/${testId}/my_attempts/`)
    return response.data
  },

  // Get mock test attempts
  getMockAttempts: async () => {
    const response = await api.get('/quiz/mock-attempts/')
    return response.data
  },

  // Get mock attempt details
  getMockAttemptDetails: async (attemptId) => {
    const response = await api.get(`/quiz/mock-attempts/${attemptId}/`)
    return response.data
  },

  // Get mock attempt review (with answers and correct options)
  getMockAttemptReview: async (attemptId) => {
    const response = await api.get(`/quiz/mock-attempts/${attemptId}/review/`)
    return response.data
  },

  // Questions by topic
  getQuestionsByTopic: async (topicId, limit = 10, difficulty) => {
    const response = await api.get('/quiz/questions/by_topic/', {
      params: { topic_id: topicId, limit, difficulty },
    })
    return response.data
  },

  // Report a question problem
  reportQuestion: async (data) => {
    const response = await api.post('/quiz/reports/', data)
    return response.data
  },

  // Get user's question reports
  getMyReports: async () => {
    const response = await api.get('/quiz/reports/my_reports/')
    return response.data
  },

  // Get quiz leaderboard
  getQuizLeaderboard: async (quizId) => {
    const response = await api.get(`/quiz/quizzes/${quizId}/leaderboard/`)
    return response.data
  },

  // Get mock test leaderboard
  getMockTestLeaderboard: async (testId) => {
    const response = await api.get(`/quiz/mock-tests/${testId}/leaderboard/`)
    return response.data
  },

  // ─── Previous Year Papers ─────────────────────────────────────────

  getPYPByYear: async (params = {}) => {
    const response = await api.get('/quiz/pyp/by_year/', { params })
    return response.data
  },

  getPYPFilterOptions: async () => {
    const response = await api.get('/quiz/pyp/filter_options/')
    return response.data
  },

  startPYP: async (testId) => {
    const response = await api.post(`/quiz/pyp/${testId}/start/`)
    return response.data
  },

  submitPYP: async (testId, data) => {
    const response = await api.post(`/quiz/pyp/${testId}/submit/`, data)
    return response.data
  },

  getPYPLeaderboard: async (testId) => {
    const response = await api.get(`/quiz/pyp/${testId}/leaderboard/`)
    return response.data
  },
}
