import { Routes, Route, Navigate, useSearchParams } from 'react-router-dom'
import { useEffect } from 'react'
import { useAuthStore } from './context/authStore'
import { useTenantStore } from './context/tenantStore'
// Layouts
import MainLayout from './components/layout/MainLayout'
import AuthLayout from './components/layout/AuthLayout'
import AdminLayout from './components/layout/AdminLayout'
import SuspensionOverlay from './components/layout/SuspensionOverlay'
import VerificationGate from './components/layout/VerificationGate'
import LoginGate from './components/auth/LoginGate'

// Auth Pages
import Login from './pages/auth/Login'
import Register from './pages/auth/Register'
import VerifyEmail from './pages/auth/VerifyEmail'
import ForgotPassword from './pages/auth/ForgotPassword'
import ResetPassword from './pages/auth/ResetPassword'
import Onboarding from './pages/auth/Onboarding'

// Main Pages
import Dashboard from './pages/Dashboard'
import Study from './pages/Study'
import StudyCourse from './pages/StudyCourse'
import Courses from './pages/Courses'
import CourseDetail from './pages/CourseDetail'
import StudyChapters from './pages/StudyChapters'
import StudyChapterTopics from './pages/StudyChapterTopics'
import StudyTopicContent from './pages/StudyTopicContent'
import TopicView from './pages/TopicView'
import ContentViewer from './pages/ContentViewer'
import Revision from './pages/Revision'
import AssignmentView from './pages/AssignmentView'
import Quiz from './pages/Quiz'
import QuizAttempt from './pages/QuizAttempt'
import QuizReview from './pages/QuizReview'
import MockTest from './pages/MockTest'
import MockTestAttempt from './pages/MockTestAttempt'
import MockTestReview from './pages/MockTestReview'
import Analytics from './pages/Analytics'
import Leaderboard from './pages/Leaderboard'
import XPHistory from './pages/XPHistory'
import Profile from './pages/Profile'
import Notifications from './pages/Notifications'
import AIDoubtSolver from './pages/AIDoubtSolver'
import AILearning from './pages/AILearning'
import AIQuizReview from './pages/AIQuizReview'
import Community from './pages/Community'
import CommunityPost from './pages/CommunityPost'
import Jobs from './pages/Jobs'
import JobDetail from './pages/JobDetail'
import JobManager from './pages/JobManager'
import JobApplicants from './pages/JobApplicants'
import JobApplicationReview from './pages/JobApplicationReview'
import PreviousYearPapers from './pages/PreviousYearPapers'
import AdminDashboard from './pages/AdminDashboard'
import CourseManager from './pages/CourseManager'
import AssignmentGrading from './pages/AssignmentGrading'
import SubmissionReview from './pages/SubmissionReview'
import CodingProblem from './pages/CodingProblem'
import CodingGrading from './pages/CodingGrading'
import CodingSubmissionReview from './pages/CodingSubmissionReview'
import NotebookPage from './pages/NotebookPage'
import NotebookBuilder from './pages/NotebookBuilder'
import NotebookGrading from './pages/NotebookGrading'
import NotebookSubmissionReview from './pages/NotebookSubmissionReview'
import MockTestManager from './pages/MockTestManager'
import MockTestBuilder from './pages/MockTestBuilder'
import AIMockStudioPage from './pages/AIMockStudioPage'
import RichMockAttempt from './pages/RichMockAttempt'
import MockTestGrading from './pages/MockTestGrading'
import MockTestSubmissions from './pages/MockTestSubmissions'
import MockTestSubmissionReview from './pages/MockTestSubmissionReview'
import RichMockReview from './pages/RichMockReview'
import LandingPage from './pages/LandingPage'
import LegalPage from './pages/LegalPage'


// Protected Route Component
const ProtectedRoute = ({ children }) => {
  const { isAuthenticated, isOnboarded } = useAuthStore()

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  if (!isOnboarded) {
    return <Navigate to="/onboarding" replace />
  }

  return children
}

// App shell that renders for everyone, including anonymous visitors, so they can
// explore public sections (courses, jobs). Authenticated-but-not-onboarded users
// are still routed to onboarding. Pages that require login gate themselves via
// <LoginGate>, which shows a blurred screen + login prompt to anonymous users.
const AppShell = () => {
  const { isAuthenticated, isOnboarded } = useAuthStore()

  if (isAuthenticated && !isOnboarded) {
    return <Navigate to="/onboarding" replace />
  }

  return <MainLayout />
}

// Root route: anonymous visitors see the tenant's public landing page;
// authenticated (onboarded) users are sent to their dashboard. Admins can
// still preview the live landing via `/?preview=1`.
const RootRoute = () => {
  const { isAuthenticated, isOnboarded } = useAuthStore()
  const [searchParams] = useSearchParams()
  const preview = searchParams.get('preview') === '1'
  if (preview) {
    return <LandingPage />
  }
  // Authenticated users who haven't finished onboarding still need to complete
  // it first; everyone else (anonymous or fully logged-in) sees the public
  // landing page at "/".
  if (isAuthenticated && !isOnboarded) {
    return <Navigate to="/onboarding" replace />
  }
  return <LandingPage />
}

// Catch-all redirect: send authenticated users to their dashboard and
// anonymous visitors to the public landing page.
const RootRedirect = () => {
  const { isAuthenticated } = useAuthStore()
  return <Navigate to={isAuthenticated ? '/dashboard' : '/'} replace />
}

// Admin-only Route Component
const AdminRoute = ({ children }) => {
  const { user, profile } = useAuthStore()
  const role = user?.role || profile?.user?.role
  if (role !== 'admin') {
    return <Navigate to="/dashboard" replace />
  }
  return children
}

// Course editor route: admins and instructors (backend scopes instructors to
// their assigned courses).
const EditorRoute = ({ children }) => {
  const { user, profile } = useAuthStore()
  const role = user?.role || profile?.user?.role
  if (role !== 'admin' && role !== 'instructor') {
    return <Navigate to="/dashboard" replace />
  }
  return children
}

// Public Route (redirect if authenticated)
const PublicRoute = ({ children }) => {
  const { isAuthenticated, isOnboarded } = useAuthStore()

  if (isAuthenticated && isOnboarded) {
    return <Navigate to="/dashboard" replace />
  }

  return children
}

// Feature-gated route: redirect to dashboard when the tenant admin has disabled
// the feature. Defaults to enabled so nothing breaks before the config loads.
const FeatureRoute = ({ feature, children }) => {
  const isFeatureEnabled = useTenantStore((s) => s.isFeatureEnabled)
  if (feature && !isFeatureEnabled(feature)) {
    return <Navigate to="/dashboard" replace />
  }
  return children
}

function App() {
  const { fetchTenantConfig, isLoading } = useTenantStore()

  useEffect(() => {
    fetchTenantConfig()
  }, [])

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-50 dark:bg-surface-950">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500"></div>
      </div>
    )
  }

  return (
    <>
      <SuspensionOverlay />
      <VerificationGate />
      <Routes>
        {/* Auth Routes */}
        <Route element={<AuthLayout />}>
          <Route
            path="/login"
            element={
              <PublicRoute>
                <Login />
              </PublicRoute>
            }
          />
          <Route
            path="/register"
            element={
              <PublicRoute>
                <Register />
              </PublicRoute>
            }
          />
          <Route
            path="/verify-email"
            element={
              <PublicRoute>
                <VerifyEmail />
              </PublicRoute>
            }
          />
          <Route
            path="/forgot-password"
            element={
              <PublicRoute>
                <ForgotPassword />
              </PublicRoute>
            }
          />
          <Route
            path="/reset-password"
            element={
              <PublicRoute>
                <ResetPassword />
              </PublicRoute>
            }
          />
          <Route path="/onboarding" element={<Onboarding />} />
        </Route>

        {/* Main App Routes */}
        <Route element={<AppShell />}>
          <Route path="/dashboard" element={<LoginGate><Dashboard /></LoginGate>} />
          {/* Public: anyone can browse the course catalog and course details */}
          <Route path="/courses" element={<FeatureRoute feature="courses"><Courses /></FeatureRoute>} />
          <Route path="/courses/:courseId" element={<FeatureRoute feature="courses"><CourseDetail /></FeatureRoute>} />
          <Route path="/courses/:courseId/manage" element={<LoginGate><EditorRoute><CourseManager /></EditorRoute></LoginGate>} />
          <Route path="/courses/:courseId/manage/assignments/:assignmentId" element={<LoginGate><EditorRoute><AssignmentGrading /></EditorRoute></LoginGate>} />
          <Route path="/courses/:courseId/manage/assignments/:assignmentId/submissions/:submissionId" element={<LoginGate><EditorRoute><SubmissionReview /></EditorRoute></LoginGate>} />
          <Route path="/courses/:courseId/manage/coding/:problemId" element={<LoginGate><EditorRoute><CodingGrading /></EditorRoute></LoginGate>} />
          <Route path="/courses/:courseId/manage/coding/:problemId/submissions/:submissionId" element={<LoginGate><EditorRoute><CodingSubmissionReview /></EditorRoute></LoginGate>} />
          <Route path="/courses/:courseId/manage/notebooks/:notebookId/edit" element={<LoginGate><EditorRoute><NotebookBuilder /></EditorRoute></LoginGate>} />
          <Route path="/courses/:courseId/manage/notebooks/:notebookId" element={<LoginGate><EditorRoute><NotebookGrading /></EditorRoute></LoginGate>} />
          <Route path="/courses/:courseId/manage/notebooks/:notebookId/submissions/:submissionId" element={<LoginGate><EditorRoute><NotebookSubmissionReview /></EditorRoute></LoginGate>} />
          <Route path="/study" element={<LoginGate><FeatureRoute feature="study"><Study /></FeatureRoute></LoginGate>} />
          <Route path="/study/course/:courseId" element={<LoginGate><FeatureRoute feature="study"><StudyCourse /></FeatureRoute></LoginGate>} />
          <Route path="/study/:subjectId" element={<LoginGate><FeatureRoute feature="study"><StudyChapters /></FeatureRoute></LoginGate>} />
          <Route path="/study/chapter/:chapterId" element={<LoginGate><FeatureRoute feature="study"><StudyChapterTopics /></FeatureRoute></LoginGate>} />
          <Route path="/study/chapter/:chapterId/topic/:topicId" element={<LoginGate><FeatureRoute feature="study"><StudyTopicContent /></FeatureRoute></LoginGate>} />
          <Route path="/topic/:topicId" element={<LoginGate><FeatureRoute feature="study"><TopicView /></FeatureRoute></LoginGate>} />
          <Route path="/content/:contentId" element={<LoginGate><FeatureRoute feature="study"><ContentViewer /></FeatureRoute></LoginGate>} />
          <Route path="/revision" element={<LoginGate><FeatureRoute feature="study"><Revision /></FeatureRoute></LoginGate>} />
          <Route path="/assignment/:assignmentId" element={<LoginGate><AssignmentView /></LoginGate>} />
          <Route path="/coding/:problemId" element={<LoginGate><CodingProblem /></LoginGate>} />
          <Route path="/notebooks/:notebookId" element={<LoginGate><NotebookPage /></LoginGate>} />
          <Route path="/quiz" element={<LoginGate><FeatureRoute feature="quiz"><Quiz /></FeatureRoute></LoginGate>} />
          <Route path="/quiz/:quizId" element={<LoginGate><FeatureRoute feature="quiz"><QuizAttempt /></FeatureRoute></LoginGate>} />
          <Route path="/quiz/review/:attemptId" element={<LoginGate><FeatureRoute feature="quiz"><QuizReview /></FeatureRoute></LoginGate>} />
          <Route path="/mock-test" element={<LoginGate><FeatureRoute feature="mock_tests"><MockTest /></FeatureRoute></LoginGate>} />
          <Route path="/mock-test/live/:testId" element={<LoginGate><FeatureRoute feature="mock_tests"><RichMockAttempt /></FeatureRoute></LoginGate>} />
          <Route path="/mock-test/live-review/:attemptId" element={<LoginGate><FeatureRoute feature="mock_tests"><RichMockReview /></FeatureRoute></LoginGate>} />
          <Route path="/mock-test/:testId" element={<LoginGate><FeatureRoute feature="mock_tests"><MockTestAttempt /></FeatureRoute></LoginGate>} />
          <Route path="/mock-test/review/:attemptId" element={<LoginGate><FeatureRoute feature="mock_tests"><MockTestReview /></FeatureRoute></LoginGate>} />
          <Route path="/pyp" element={<LoginGate><FeatureRoute feature="pyq"><PreviousYearPapers /></FeatureRoute></LoginGate>} />
          <Route path="/analytics" element={<LoginGate><FeatureRoute feature="analytics"><Analytics /></FeatureRoute></LoginGate>} />
          <Route path="/leaderboard" element={<LoginGate><FeatureRoute feature="leaderboard"><Leaderboard /></FeatureRoute></LoginGate>} />
          <Route path="/profile" element={<LoginGate><Profile /></LoginGate>} />
          <Route path="/notifications" element={<LoginGate><Notifications /></LoginGate>} />
          <Route path="/xp" element={<LoginGate><XPHistory /></LoginGate>} />
          <Route path="/doubt-solver" element={<LoginGate><FeatureRoute feature="ai"><AIDoubtSolver /></FeatureRoute></LoginGate>} />
          <Route path="/ai-doubt-solver" element={<LoginGate><FeatureRoute feature="ai"><AIDoubtSolver /></FeatureRoute></LoginGate>} />
          <Route path="/ai-learning" element={<LoginGate><FeatureRoute feature="ai"><AILearning /></FeatureRoute></LoginGate>} />
          <Route path="/ai-quiz-review/:attemptId" element={<LoginGate><FeatureRoute feature="ai"><AIQuizReview /></FeatureRoute></LoginGate>} />
          <Route path="/community" element={<LoginGate><FeatureRoute feature="community"><Community /></FeatureRoute></LoginGate>} />
          <Route path="/community/:id" element={<LoginGate><FeatureRoute feature="community"><CommunityPost /></FeatureRoute></LoginGate>} />

          {/* Job Portal (students) — public browsing, login required to apply */}
          <Route path="/jobs" element={<FeatureRoute feature="jobs"><Jobs /></FeatureRoute>} />
          <Route path="/jobs/:jobId" element={<FeatureRoute feature="jobs"><JobDetail /></FeatureRoute>} />

          {/* Admin Job Portal & Mock Tests now live under the full-page Admin View below */}
        </Route>

        {/* Full-page Admin View */}
        <Route
          element={
            <ProtectedRoute>
              <AdminRoute>
                <AdminLayout />
              </AdminRoute>
            </ProtectedRoute>
          }
        >
          <Route path="/admin-dashboard" element={<AdminDashboard />} />
          <Route path="/admin-dashboard/content/:courseId" element={<CourseManager />} />

          {/* Job Portal (admin) */}
          <Route path="/admin/jobs" element={<JobManager />} />
          <Route path="/admin/jobs/:jobId" element={<JobApplicants />} />
          <Route path="/admin/jobs/:jobId/applications/:applicationId" element={<JobApplicationReview />} />

          {/* Mock Tests (admin) */}
          <Route path="/admin/mock-tests" element={<MockTestManager />} />
          <Route path="/admin/mock-tests/ai" element={<AIMockStudioPage />} />
          <Route path="/admin/mock-tests/grading" element={<MockTestGrading />} />
          <Route path="/admin/mock-tests/:testId/submissions" element={<MockTestSubmissions />} />
          <Route path="/admin/mock-tests/:testId/submissions/:attemptId" element={<MockTestSubmissionReview />} />
          <Route path="/admin/mock-tests/:testId" element={<MockTestBuilder />} />
        </Route>


        {/* Public standalone pages (no app shell, no login required) */}
        <Route path="/" element={<RootRoute />} />
        <Route path="/refund-policy" element={<LegalPage slug="refund-policy" />} />
        <Route path="/privacy-policy" element={<LegalPage slug="privacy-policy" />} />
        <Route path="/terms" element={<LegalPage slug="terms" />} />

        {/* Redirects */}
        <Route path="*" element={<RootRedirect />} />
      </Routes>
    </>
  )
}

export default App

