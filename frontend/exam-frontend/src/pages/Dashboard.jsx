import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '../context/authStore'
import { useFeatureLabel } from '../context/tenantStore'
import { analyticsService } from '../services/analyticsService'
import { contentService } from '../services/contentService'
import { quizService } from '../services/quizService'
import { courseService } from '../services/courseService'

// Components
import ProgressRing from '../components/common/ProgressRing'
import StreakFire from '../components/common/StreakFire'
import StatCard from '../components/common/StatCard'
import QuickActionButton from '../components/common/QuickActionButton'
import TopicMasteryChip from '../components/common/TopicMasteryChip'
import Loading from '../components/common/Loading'
import CourseThumbnail from '../components/course/CourseThumbnail'
import {
  Trophy,
  Target,
  Zap,
  BookOpen,
  Timer,
  Crown,
  PenTool,
  Flame,
  Star,
  Sparkles,
  Bot,
  FileText,
  Book,
  PartyPopper,
  Sparkle,
  ChevronRight,
  ChevronLeft,
  ArrowRight,
  Compass,
  Hand,
  CheckCircle2
} from 'lucide-react'

const EnrolledCoursesSlider = ({ courses, navigate }) => {
  const scrollRef = useRef(null)

  const scrollBy = (dir) => {
    const el = scrollRef.current
    if (!el) return
    el.scrollBy({ left: dir * Math.max(el.clientWidth * 0.8, 280), behavior: 'smooth' })
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-3"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-display font-bold flex items-center gap-2">
          <BookOpen size={20} className="text-primary-500" /> Your courses
        </h2>
        <div className="flex items-center gap-2">
          {courses.length > 1 && (
            <div className="hidden sm:flex items-center gap-1">
              <button
                type="button"
                onClick={() => scrollBy(-1)}
                aria-label="Scroll left"
                className="btn-icon border border-surface-200 dark:border-surface-700"
              >
                <ChevronLeft size={18} />
              </button>
              <button
                type="button"
                onClick={() => scrollBy(1)}
                aria-label="Scroll right"
                className="btn-icon border border-surface-200 dark:border-surface-700"
              >
                <ChevronRight size={18} />
              </button>
            </div>
          )}
          <button
            type="button"
            onClick={() => navigate('/study')}
            className="text-sm font-medium text-primary-600 dark:text-primary-400 inline-flex items-center gap-1 hover:gap-1.5 transition-all"
          >
            View all <ArrowRight size={15} />
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="flex gap-4 overflow-x-auto pb-2 -mx-1 px-1 snap-x snap-mandatory scrollbar-hide"
      >
        {courses.map((course) => (
          <button
            key={course.id}
            type="button"
            onClick={() => navigate(`/study/course/${course.id}`)}
            className="group snap-start shrink-0 w-[260px] text-left card p-0 overflow-hidden hover:shadow-lg hover:-translate-y-0.5 transition-all"
          >
            <CourseThumbnail course={course} />
            <div className="p-4">
              <h3 className="font-bold truncate">{course.name}</h3>
              <span className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-primary-600 dark:text-primary-400">
                Continue learning
                <ArrowRight size={14} className="transition-transform group-hover:translate-x-0.5" />
              </span>
            </div>
          </button>
        ))}

        <button
          type="button"
          onClick={() => navigate('/courses')}
          className="snap-start shrink-0 w-[200px] card border-2 border-dashed border-surface-200 dark:border-surface-700 flex flex-col items-center justify-center gap-2 text-surface-500 hover:border-primary-400 hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
        >
          <Compass size={26} />
          <span className="text-sm font-medium">Browse courses</span>
        </button>
      </div>
    </motion.div>
  )
}

const Dashboard = () => {
  const navigate = useNavigate()
  const studyLabel = useFeatureLabel('study', 'Study')
  const mockLabel = useFeatureLabel('mock_tests', 'Mock Test')
  const { profile } = useAuthStore()
  const queryClient = useQueryClient()
  const selectedExamId = (typeof localStorage !== 'undefined' && localStorage.getItem('study:lastCourseId')) || ''

  // Fetch dashboard data
  const { data: dashboardStats, isLoading: statsLoading } = useQuery({
    queryKey: ['dashboardStats'],
    queryFn: () => analyticsService.getDashboardStats(),
  })

  const { data: enrolledData } = useQuery({
    queryKey: ['studyCourses'],
    queryFn: () => courseService.getStudyCourses(),
  })
  const enrolledCourses = enrolledData?.courses || []

  const { data: studyPlan, isLoading: planLoading } = useQuery({
    queryKey: ['todayStudyPlan', selectedExamId],
    queryFn: () => contentService.getTodayStudyPlan(selectedExamId || undefined),
  })

  // Create / regenerate today's study plan
  const generatePlan = useMutation({
    mutationFn: () => contentService.generateStudyPlan({
      ...(selectedExamId ? { course_id: selectedExamId } : {}),
      target_minutes: profile?.daily_study_goal_minutes || 60,
      include_revision: true,
      focus_weak_topics: true,
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['todayStudyPlan'] }),
  })

  // Mark a plan item complete (optimistic refetch)
  const completeItem = useMutation({
    mutationFn: (itemId) => contentService.updateStudyPlanItem(itemId, 'complete'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['todayStudyPlan'] }),
  })

  const goToPlanItem = (item) => {
    if (item.item_type === 'mock') return navigate('/mock-test')
    if (item.item_type === 'quiz') return navigate('/quiz')
    if (item.content) return navigate(`/content/${item.content}`)
    if (item.topic) return navigate(`/topic/${item.topic}`)
    return navigate('/study')
  }

  const planItems = studyPlan?.items || []
  const pendingItems = planItems.filter((i) => i.status !== 'completed')
  const completedCount = planItems.length - pendingItems.length
  const allDone = planItems.length > 0 && pendingItems.length === 0

  const { data: weakTopics } = useQuery({
    queryKey: ['weakTopics'],
    queryFn: () => analyticsService.getWeakTopics(),
  })

  const { data: dailyChallenge } = useQuery({
    queryKey: ['dailyChallenge', selectedExamId],
    queryFn: () => quizService.getDailyChallenge(selectedExamId || undefined),
  })

  if (statsLoading) return <Loading fullScreen />

  const stats = dashboardStats || {
    current_streak: 0,
    today: { study_time: 0, questions: 0, goal_progress: 0, goal_met: false },
    weekly: { study_time: 0, questions: 0, accuracy: 0, xp_earned: 0 },
    mastery: { total_topics: 0, mastered: 0, weak: 0, weak_topics: [] },
    profile: { total_xp: 0, level: 1, overall_accuracy: 0 }
  }

  const greeting = () => {
    const hour = new Date().getHours()
    if (hour < 12) return 'Good Morning'
    if (hour < 17) return 'Good Afternoon'
    return 'Good Evening'
  }

  return (
    <div className="space-y-6">
      {/* Header Section */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            {greeting()}, {profile?.user?.first_name || 'Student'}! <Hand className="text-yellow-400 animate-hand-wave" />
          </h1>
          <p className="text-surface-500 mt-1">
            Ready to crush your goals today?
          </p>
        </div>

        {/* Streak & Level */}
        <div className="flex items-center gap-4">
          {stats.current_streak > 0 && (
            <StreakFire streak={stats.current_streak} size="md" />
          )}
          <div className="text-center">
            <p className="text-sm text-surface-500">Level</p>
            <p className="text-2xl font-bold gradient-text">{stats.profile?.level || 1}</p>
          </div>
        </div>
      </div>

      {/* Today's Progress Card */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className={`card overflow-hidden relative ${stats.today.goal_met
          ? 'bg-gradient-to-br from-amber-500 via-orange-500 to-rose-500'
          : 'bg-gradient-to-br from-primary-500 via-primary-600 to-accent-600'
          } text-white`}
      >
        {/* Animated Background for Goal Achieved */}
        {stats.today.goal_met ? (
          <>
            {/* Animated gradient overlay */}
            <motion.div
              animate={{
                backgroundPosition: ['0% 0%', '100% 100%'],
              }}
              transition={{ duration: 3, repeat: Infinity, repeatType: 'reverse' }}
              className="absolute inset-0 bg-gradient-to-br from-yellow-400/30 via-transparent to-pink-500/30"
              style={{ backgroundSize: '200% 200%' }}
            />

            {/* Floating particles */}
            {[...Array(12)].map((_, i) => {
              const IconComponent = [Sparkles, Star, PartyPopper, Sparkle, Star, Flame][i % 6]
              return (
                <motion.div
                  key={i}
                  initial={{
                    y: 100,
                    x: Math.random() * 100,
                    opacity: 0,
                    scale: 0
                  }}
                  animate={{
                    y: -20,
                    opacity: [0, 1, 1, 0],
                    scale: [0, 1, 1, 0.5]
                  }}
                  transition={{
                    duration: 2 + Math.random() * 2,
                    delay: i * 0.2,
                    repeat: Infinity,
                    repeatDelay: Math.random() * 2
                  }}
                  className="absolute text-xl"
                  style={{
                    left: `${5 + (i * 8)}%`,
                    bottom: 0
                  }}
                >
                  <IconComponent size={24} />
                </motion.div>
              )
            })}

            {/* Glow effects */}
            <div className="absolute top-0 left-1/4 w-32 h-32 bg-yellow-300/40 rounded-full blur-3xl" />
            <div className="absolute bottom-0 right-1/4 w-40 h-40 bg-rose-400/30 rounded-full blur-3xl" />
          </>
        ) : (
          <div className="absolute inset-0 opacity-10">
            <div className="absolute top-0 right-0 w-64 h-64 bg-white rounded-full blur-3xl transform translate-x-1/2 -translate-y-1/2" />
            <div className="absolute bottom-0 left-0 w-48 h-48 bg-white rounded-full blur-3xl transform -translate-x-1/2 translate-y-1/2" />
          </div>
        )}

        <div className="relative z-10 p-6">
          {stats.today.goal_met ? (
            /* Celebration Layout */
            <>
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    className="inline-flex items-center gap-2 px-3 py-1.5 bg-white/25 backdrop-blur-sm rounded-full mb-3"
                  >
                    <Trophy size={18} className="text-yellow-300" />
                    <span className="font-bold text-sm">GOAL ACHIEVED!</span>
                  </motion.div>

                  <motion.h2
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="text-2xl font-bold mb-1 flex items-center gap-2"
                  >
                    Incredible Work! <PartyPopper size={24} />
                  </motion.h2>

                  <motion.p
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: 0.2 }}
                    className="text-white/80"
                  >
                    You crushed your daily study goal. Keep this momentum going!
                  </motion.p>
                </div>

                {/* Trophy Animation */}
                <motion.div
                  initial={{ scale: 0, rotate: -180 }}
                  animate={{ scale: 1, rotate: 0 }}
                  transition={{ type: 'spring', damping: 10 }}
                  className="relative"
                >
                  <motion.div
                    animate={{ scale: [1, 1.2, 1] }}
                    transition={{ duration: 2, repeat: Infinity }}
                    className="absolute inset-0 bg-yellow-300/50 rounded-full blur-xl"
                  />
                  <div className="relative w-20 h-20 bg-gradient-to-br from-yellow-300 to-amber-500 rounded-2xl flex items-center justify-center shadow-lg shadow-orange-500/30 text-white">
                    <Trophy size={40} />
                  </div>
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ delay: 0.5 }}
                    className="absolute -top-1 -right-1 w-6 h-6 bg-green-400 rounded-full flex items-center justify-center text-xs font-bold shadow-lg"
                  >
                    ✓
                  </motion.div>
                </motion.div>
              </div>

              {/* Stats with icons */}
              <div className="grid grid-cols-3 gap-3">
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.1 }}
                  className="bg-white/20 backdrop-blur-sm rounded-xl p-4 border border-white/10"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <Timer size={18} className="text-white/70" />
                    <p className="text-white/70 text-sm">Study Time</p>
                  </div>
                  <p className="text-2xl font-bold">{stats.today.study_time}m</p>
                </motion.div>
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 }}
                  className="bg-white/20 backdrop-blur-sm rounded-xl p-4 border border-white/10"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <PenTool size={18} className="text-white/70" />
                    <p className="text-white/70 text-sm">Questions</p>
                  </div>
                  <p className="text-2xl font-bold">{stats.today.questions}</p>
                </motion.div>
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.3 }}
                  className="bg-white/20 backdrop-blur-sm rounded-xl p-4 border border-white/10"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <Target size={18} className="text-white/70" />
                    <p className="text-white/70 text-sm">Accuracy</p>
                  </div>
                  <p className="text-2xl font-bold">{Math.round(stats.today.accuracy || 0)}%</p>
                </motion.div>
              </div>
            </>
          ) : (
            /* Regular Progress Layout */
            <>
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-lg font-semibold text-white/90">Today's Progress</h2>
                  <p className="text-white/70 text-sm">
                    {Math.round(stats.today.goal_progress)}% of daily goal
                  </p>
                </div>
                <ProgressRing
                  value={stats.today.goal_progress}
                  size={80}
                  strokeWidth={8}
                  color="#ffffff"
                  trailColor="rgba(255,255,255,0.2)"
                >
                  <span className="text-lg font-bold text-white">{Math.round(stats.today.goal_progress)}%</span>
                </ProgressRing>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div className="bg-white/10 backdrop-blur-sm rounded-xl p-4">
                  <p className="text-white/70 text-sm">Study Time</p>
                  <p className="text-2xl font-bold">{stats.today.study_time}m</p>
                </div>
                <div className="bg-white/10 backdrop-blur-sm rounded-xl p-4">
                  <p className="text-white/70 text-sm">Questions</p>
                  <p className="text-2xl font-bold">{stats.today.questions}</p>
                </div>
                <div className="bg-white/10 backdrop-blur-sm rounded-xl p-4">
                  <p className="text-white/70 text-sm">Accuracy</p>
                  <p className="text-2xl font-bold">{Math.round(stats.today.accuracy || 0)}%</p>
                </div>
              </div>
            </>
          )}
        </div>
      </motion.div>

      {/* Quick Actions */}
      <div>
        <h2 className="text-lg font-semibold mb-4">Quick Actions</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <QuickActionButton
            title="Daily Challenge"
            subtitle={dailyChallenge
              ? `${dailyChallenge.questions_count} questions • +${dailyChallenge.total_marks * 5} XP`
              : 'Take today\'s challenge'}
            icon={<Target className="text-primary-500" />}
            to="/quiz"
            variant="primary"
            badge={dailyChallenge ? "NEW" : null}
          />
          <QuickActionButton
            title={`Resume ${studyLabel}`}
            subtitle={pendingItems[0]?.title || 'Start learning'}
            icon={<BookOpen className="text-primary-500" />}
            to="/study"
          />
          <QuickActionButton
            title={mockLabel}
            subtitle="Practice with full tests"
            icon={<FileText className="text-primary-500" />}
            to="/mock-test"
          />
        </div>
      </div>

      {/* Enrolled courses — quick access */}
      {enrolledCourses.length > 0 && (
        <EnrolledCoursesSlider courses={enrolledCourses} navigate={navigate} />
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          title="Weekly XP"
          value={stats.weekly.xp_earned?.toLocaleString() || 0}
          icon={<Zap className="text-yellow-500" />}
          subtitle={`${stats.weekly.days_active || 0} active days`}
        />
        <StatCard
          title="Questions Done"
          value={stats.weekly.questions || 0}
          icon={<PenTool className="text-primary-500" />}
          subtitle="This week"
        />
        <StatCard
          title="Accuracy"
          value={`${Math.round(stats.weekly.accuracy || 0)}%`}
          icon={<Target className="text-success-500" />}
          subtitle="Weekly average"
          valueClassName={
            stats.weekly.accuracy >= 70
              ? 'text-success-600 dark:text-success-400'
              : stats.weekly.accuracy >= 50
              ? 'text-amber-600 dark:text-amber-400'
              : stats.weekly.questions > 0
              ? 'text-rose-600 dark:text-rose-400'
              : ''
          }
        />
        <StatCard
          title="Topics Mastered"
          value={stats.mastery.mastered || 0}
          icon={<Crown className="text-warning-500" />}
          subtitle={`of ${stats.mastery.total_topics || 0} topics`}
        />
      </div>

      {/* Two Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Today's Study Plan */}
        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold">Today's Study Plan</h3>
            <button
              onClick={() => navigate('/study')}
              className="text-sm text-primary-600 hover:underline"
            >
              View All
            </button>
          </div>

          {pendingItems.length > 0 ? (
            <div className="space-y-3">
              {completedCount > 0 && (
                <p className="text-xs text-surface-500">
                  {completedCount} of {planItems.length} done — keep going!
                </p>
              )}
              {pendingItems.slice(0, 4).map((item, index) => (
                <div
                  key={item.id || index}
                  onClick={() => goToPlanItem(item)}
                  className="flex items-center gap-3 p-3 rounded-xl bg-surface-50 dark:bg-surface-800 hover:bg-surface-100 dark:hover:bg-surface-700 cursor-pointer transition-colors"
                >
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      completeItem.mutate(item.id)
                    }}
                    disabled={completeItem.isPending}
                    title="Mark as done"
                    className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0 bg-primary-100 dark:bg-primary-900/30 hover:bg-success-100 dark:hover:bg-success-900/30 group"
                  >
                    <BookOpen size={18} className="text-primary-600 group-hover:hidden" />
                    <CheckCircle2 size={18} className="text-success-600 hidden group-hover:block" />
                  </button>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{item.title}</p>
                    <p className="text-xs text-surface-500 capitalize">
                      {item.item_type} • {item.estimated_minutes || 15} min
                    </p>
                  </div>
                  <ChevronRight size={18} className="text-surface-300 shrink-0" />
                </div>
              ))}
              <button
                onClick={() => generatePlan.mutate()}
                disabled={generatePlan.isPending}
                className="btn-secondary w-full text-sm mt-1"
              >
                {generatePlan.isPending ? 'Regenerating…' : 'Regenerate Plan'}
              </button>
            </div>
          ) : allDone ? (
            <div className="text-center py-8 text-surface-500">
              <PartyPopper size={36} className="mx-auto mb-3 text-success-500" />
              <p className="font-medium text-surface-700 dark:text-surface-200">All done for today!</p>
              <p className="text-sm mt-1">You completed all {planItems.length} tasks. 🎉</p>
              <button
                onClick={() => generatePlan.mutate()}
                disabled={generatePlan.isPending}
                className="btn-secondary mt-4 text-sm"
              >
                {generatePlan.isPending ? 'Generating…' : 'Generate New Plan'}
              </button>
            </div>
          ) : (
            <div className="text-center py-8 text-surface-500">
              <p>{studyPlan?.no_exam ? 'Enroll in an exam to get a study plan' : 'No study plan for today'}</p>
              {studyPlan?.no_exam ? (
                <button
                  onClick={() => navigate('/profile')}
                  className="btn-primary mt-4"
                >
                  Manage Exams
                </button>
              ) : (
                <button
                  onClick={() => generatePlan.mutate()}
                  disabled={generatePlan.isPending}
                  className="btn-primary mt-4"
                >
                  {generatePlan.isPending ? 'Creating…' : 'Create Study Plan'}
                </button>
              )}
            </div>
          )}
        </div>

        {/* Weak Topics */}
        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold">Topics to Revise</h3>
            <button
              onClick={() => navigate('/analytics')}
              className="text-sm text-primary-600 hover:underline"
            >
              View All
            </button>
          </div>

          {stats.mastery.weak_topics?.length > 0 ? (
            <div className="space-y-3">
              {stats.mastery.weak_topics.slice(0, 4).map((topic) => (
                <div
                  key={topic.id}
                  onClick={() => navigate(`/topic/${topic.id}`)}
                  className="flex items-center gap-3 p-3 rounded-xl bg-surface-50 dark:bg-surface-800 hover:bg-surface-100 dark:hover:bg-surface-700 cursor-pointer transition-colors"
                >
                  <div className="w-2 h-2 rounded-full bg-warning-500" />
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{topic.name}</p>
                    <p className="text-xs text-surface-500">
                      Level {topic.level} • Needs practice
                    </p>
                  </div>
                  <button className="btn-secondary text-xs px-3 py-1.5">
                    Practice
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-surface-500">
              <div className="flex justify-center mb-2 text-success-500">
                <PartyPopper size={40} />
              </div>
              <p>All topics are in good shape!</p>
              <p className="text-sm mt-1">Keep up the great work</p>
            </div>
          )}
        </div>
      </div>

      {/* AI Doubt Solver CTA */}
      <motion.div
        whileHover={{ scale: 1.01 }}
        className="card p-6 bg-gradient-to-r from-accent-500 to-accent-600 text-white cursor-pointer"
        onClick={() => navigate('/doubt-solver')}
      >
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 bg-white/20 rounded-2xl flex items-center justify-center">
            <Bot size={40} />
          </div>
          <div className="flex-1">
            <h3 className="text-xl font-semibold">AI Doubt Solver</h3>
            <p className="text-white/80">
              Stuck on a problem? Ask our AI tutor for instant help!
            </p>
          </div>
          <ChevronRight size={24} />
        </div>
      </motion.div>
    </div>
  )
}

export default Dashboard
