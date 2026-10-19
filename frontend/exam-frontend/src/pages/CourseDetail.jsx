import { useMemo, useState, useEffect } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { courseService } from '../services/courseService'
import { paymentService } from '../services/paymentService'
import { marketingService } from '../services/marketingService'
import { useAuthStore } from '../context/authStore'
import Loading from '../components/common/Loading'
import CourseThumbnail from '../components/course/CourseThumbnail'
import CourseCommunityPreview from '../components/community/CourseCommunityPreview'
import { useTenantStore } from '../context/tenantStore'
import toast from 'react-hot-toast'
import {
  ArrowLeft, ArrowRight, GraduationCap, CheckCircle2, Clock, PlusCircle,
  BookOpen, Layers, ShieldCheck, Sparkles, Users, Tag, Settings2,
  ChevronDown, FileText, Video, ListChecks, ClipboardList, Code2, Award,
  CreditCard,
} from 'lucide-react'

const CURRENCY_SYMBOLS = { INR: '₹', USD: '$', EUR: '€', GBP: '£' }
const money = (currency, amount) => {
  const sym = CURRENCY_SYMBOLS[currency] || `${currency} `
  const n = Number(amount)
  return `${sym}${Number.isFinite(n) ? n.toLocaleString('en-IN') : amount}`
}

// Icon + accent per content-type bucket returned by the curriculum API.
const CONTENT_TYPE_META = {
  reading: { icon: FileText, cls: 'text-sky-600 dark:text-sky-400 bg-sky-50 dark:bg-sky-900/30' },
  videos: { icon: Video, cls: 'text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-900/30' },
  quizzes: { icon: ListChecks, cls: 'text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-900/30' },
  assignments: { icon: ClipboardList, cls: 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/30' },
  coding: { icon: Code2, cls: 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30' },
}

const RichText = ({ value }) => {
  const text = (value || '').trim()
  if (!text) return <p className="text-surface-500">No description provided yet.</p>
  return (
    <div className="prose dark:prose-invert max-w-none prose-headings:font-display prose-p:leading-relaxed prose-img:rounded-xl prose-ul:my-3 prose-table:my-4 [&_.katex-display]:overflow-x-auto">
      {text.startsWith('<') ? (
        <div dangerouslySetInnerHTML={{ __html: text }} />
      ) : (
        <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[rehypeKatex]}>
          {text}
        </ReactMarkdown>
      )}
    </div>
  )
}

const ContentTypeBadges = ({ types }) => (
  <div className="flex flex-wrap gap-1.5">
    {types.map((t) => {
      const meta = CONTENT_TYPE_META[t.key] || CONTENT_TYPE_META.reading
      const Icon = meta.icon
      return (
        <span
          key={t.key}
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold ${meta.cls}`}
          title={`${t.count} ${t.label}`}
        >
          <Icon size={12} /> {t.count} {t.label}
        </span>
      )
    })}
  </div>
)

const TabButton = ({ active, onClick, children }) => (
  <button
    type="button"
    onClick={onClick}
    className={`relative px-1 pb-3 text-sm font-medium whitespace-nowrap transition-colors ${
      active
        ? 'text-primary-600 dark:text-primary-400'
        : 'text-surface-500 hover:text-surface-800 dark:hover:text-surface-200'
    }`}
  >
    {children}
    {active && (
      <motion.span
        layoutId="courseDetailTab"
        className="absolute left-0 right-0 -bottom-px h-0.5 rounded-full bg-primary-500"
      />
    )}
  </button>
)

const CourseDetail = () => {
  const { courseId } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const { user, profile, isAuthenticated } = useAuthStore()
  const role = user?.role || profile?.user?.role
  const isAdmin = role === 'admin'
  const communityEnabled = useTenantStore((s) => s.isFeatureEnabled)('community')
  const communityLabel = useTenantStore((s) => s.featureLabel)('community', 'Community')

  const [tab, setTab] = useState('overview')
  const [requesting, setRequesting] = useState(false)
  const [openSubjects, setOpenSubjects] = useState(() => new Set())
  // Coupon state for paid-course checkout.
  const [couponCode, setCouponCode] = useState('')
  const [appliedCoupon, setAppliedCoupon] = useState(null) // validated quote
  const [couponError, setCouponError] = useState('')
  const [validatingCoupon, setValidatingCoupon] = useState(false)

  const toggleSubject = (id) =>
    setOpenSubjects((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const { data: course, isLoading, isError } = useQuery({
    queryKey: ['courseDetail', courseId],
    queryFn: () => courseService.getCourseDetails(courseId),
    enabled: !!courseId,
  })

  const { data: studyData = { courses: [], pending: [] } } = useQuery({
    queryKey: ['studyCourses'],
    queryFn: () => courseService.getStudyCourses(),
    enabled: isAuthenticated,
  })

  const status = useMemo(() => {
    if ((studyData.courses || []).some((c) => String(c.id) === String(courseId))) return 'approved'
    if ((studyData.pending || []).some((c) => String(c.id) === String(courseId))) return 'pending'
    return null
  }, [studyData, courseId])

  // Redirect-based providers (PayU) return here with ?payment=success|failed.
  useEffect(() => {
    const result = searchParams.get('payment')
    if (!result) return
    if (result === 'success') {
      toast.success('Payment successful — you are enrolled!')
      queryClient.invalidateQueries({ queryKey: ['studyCourses'] })
      queryClient.invalidateQueries({ queryKey: ['enrollments'] })
    } else {
      toast.error('Payment was not completed. Please try again.')
    }
    // Strip the flag so a refresh doesn't re-trigger the toast.
    searchParams.delete('payment')
    setSearchParams(searchParams, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const requestEnroll = async () => {
    if (!isAuthenticated) {
      navigate('/login', { state: { from: `/courses/${courseId}` } })
      return
    }
    setRequesting(true)
    try {
      const res = await courseService.requestEnrollment(courseId)
      // Free courses with self-enrolment turned on come back already approved.
      if (res?.status === 'approved') {
        toast.success('Enrolled! You can start learning now.')
      } else {
        toast.success('Enrollment request sent for admin approval')
      }
      queryClient.invalidateQueries({ queryKey: ['studyCourses'] })
      queryClient.invalidateQueries({ queryKey: ['enrollments'] })
    } catch (err) {
      toast.error(
        err?.response?.data?.course?.[0] ||
        err?.response?.data?.detail ||
        'Request failed'
      )
    } finally {
      setRequesting(false)
    }
  }

  const applyCoupon = async () => {
    const code = couponCode.trim()
    if (!code) return
    setValidatingCoupon(true)
    setCouponError('')
    try {
      const quote = await marketingService.validateCoupon(code, courseId)
      setAppliedCoupon(quote)
      toast.success(`Coupon ${quote.code} applied`)
    } catch (err) {
      setAppliedCoupon(null)
      setCouponError(err?.response?.data?.detail || 'Coupon could not be applied')
    } finally {
      setValidatingCoupon(false)
    }
  }

  const removeCoupon = () => {
    setAppliedCoupon(null)
    setCouponCode('')
    setCouponError('')
  }

  const payAndEnroll = async () => {
    if (!isAuthenticated) {
      navigate('/login', { state: { from: `/courses/${courseId}` } })
      return
    }
    setRequesting(true)
    try {
      const returnUrl = `${window.location.origin}/courses/${courseId}`
      const result = await paymentService.checkout(
        course, user, returnUrl, appliedCoupon?.code
      )
      if (result?.enrolled) {
        toast.success('Payment successful — you are enrolled!')
        queryClient.invalidateQueries({ queryKey: ['studyCourses'] })
        queryClient.invalidateQueries({ queryKey: ['enrollments'] })
      } else {
        toast('Payment is being confirmed. Access unlocks once it clears.', { icon: '⏳' })
      }
    } catch (err) {
      const msg = err?.message === 'cancelled'
        ? 'Payment cancelled'
        : (err?.response?.data?.detail || 'Payment could not be completed')
      if (err?.message !== 'cancelled') toast.error(msg)
    } finally {
      setRequesting(false)
    }
  }

  if (isLoading) return <Loading fullScreen />
  if (isError || !course) {
    return (
      <div className="card p-10 text-center text-surface-500">
        <GraduationCap size={48} className="mx-auto mb-3 text-surface-300" />
        <p className="font-medium">Course not found</p>
        <button onClick={() => navigate('/courses')} className="btn-secondary mt-4">
          <ArrowLeft size={16} /> Back to courses
        </button>
      </div>
    )
  }

  const isFree = course.is_free || course.pricing_type === 'free' || !Number(course.price)
  const hasDiscount = Number(course.discount_percent) > 0 && course.original_price
  const highlights = Array.isArray(course.highlights) ? course.highlights : []
  const subjects = Array.isArray(course.subjects) ? course.subjects : []
  const instructors = Array.isArray(course.instructors) ? course.instructors : []

  const tabs = [
    { key: 'overview', label: 'Overview' },
    { key: 'curriculum', label: 'Curriculum' },
    ...(instructors.length ? [{ key: 'instructors', label: 'Faculty' }] : []),
    ...(communityEnabled ? [{ key: 'community', label: communityLabel }] : []),
  ]

  const enrollMode = course.enroll_mode || 'request'

  const EnrollAction = () => {
    if (status === 'approved') {
      return (
        <button onClick={() => navigate(`/study/course/${course.id}`)} className="btn-primary w-full group/btn">
          Enter course
          <ArrowRight size={16} className="transition-transform group-hover/btn:translate-x-0.5" />
        </button>
      )
    }
    if (status === 'pending') {
      return (
        <span className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800/60">
          <Clock size={16} /> Awaiting admin approval
        </span>
      )
    }
    if (!isAuthenticated) {
      return (
        <button onClick={() => navigate('/login', { state: { from: `/courses/${courseId}` } })} className="btn-primary w-full">
          <PlusCircle size={18} /> Log in to enroll
        </button>
      )
    }
    // Paid course in pay-to-enrol mode → open the payment checkout.
    if (enrollMode === 'payment') {
      const payable = appliedCoupon ? appliedCoupon.final_amount : course.price
      return (
        <div className="space-y-3">
          {/* Coupon input */}
          {appliedCoupon ? (
            <div className="flex items-center justify-between gap-2 px-3 py-2 rounded-xl bg-success-50 dark:bg-success-900/20 border border-success-200 dark:border-success-800/60">
              <span className="inline-flex items-center gap-1.5 text-sm font-medium text-success-700 dark:text-success-300">
                <Tag size={14} /> {appliedCoupon.code} applied · you save{' '}
                {money(appliedCoupon.currency, appliedCoupon.discount_amount)}
              </span>
              <button onClick={removeCoupon} className="text-xs font-medium text-surface-500 hover:text-error-500">
                Remove
              </button>
            </div>
          ) : (
            <div>
              <div className="flex gap-2">
                <input
                  value={couponCode}
                  onChange={(e) => setCouponCode(e.target.value.toUpperCase())}
                  onKeyDown={(e) => e.key === 'Enter' && applyCoupon()}
                  placeholder="Have a coupon code?"
                  className="input flex-1 uppercase !py-2.5"
                />
                <button
                  onClick={applyCoupon}
                  disabled={validatingCoupon || !couponCode.trim()}
                  className="btn-secondary shrink-0 disabled:opacity-60"
                >
                  {validatingCoupon ? 'Checking…' : 'Apply'}
                </button>
              </div>
              {couponError && <p className="text-xs text-error-500 mt-1">{couponError}</p>}
            </div>
          )}

          {appliedCoupon && (
            <div className="flex items-baseline justify-between text-sm px-1">
              <span className="text-surface-500">Total</span>
              <span className="flex items-baseline gap-2">
                <span className="text-surface-400 line-through">{money(course.currency, appliedCoupon.original_amount)}</span>
                <span className="text-lg font-display font-bold text-primary-600 dark:text-primary-400">
                  {money(appliedCoupon.currency, payable)}
                </span>
              </span>
            </div>
          )}

          <button onClick={payAndEnroll} disabled={requesting} className="btn-primary w-full disabled:opacity-70">
            <CreditCard size={18} />
            {requesting ? 'Processing…' : `Pay ${money(course.currency, payable)} & enroll`}
          </button>
        </div>
      )
    }
    // Free course with self-enrolment enabled → instant join.
    if (enrollMode === 'self') {
      return (
        <button onClick={requestEnroll} disabled={requesting} className="btn-primary w-full disabled:opacity-70">
          <PlusCircle size={18} />
          {requesting ? 'Enrolling…' : 'Enroll now · Free'}
        </button>
      )
    }
    // Default: request → admin approval.
    return (
      <button onClick={requestEnroll} disabled={requesting} className="btn-primary w-full disabled:opacity-70">
        <PlusCircle size={18} />
        {requesting
          ? 'Sending…'
          : isFree
          ? 'Request enrollment · Free'
          : 'Request enrollment'}
      </button>
    )
  }

  return (
    <div className="space-y-6">
      <button
        onClick={() => navigate('/courses')}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-surface-500 hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
      >
        <ArrowLeft size={16} /> Back to courses
      </button>

      {/* Hero banner */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-primary-600 to-primary-700 text-white">
        <div className="absolute -top-10 -right-10 w-56 h-56 rounded-full bg-white/10" />
        <div className="absolute -bottom-16 -left-10 w-64 h-64 rounded-full bg-black/10" />
        <div className="relative p-6 sm:p-10">
          {course.course_type && (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold uppercase tracking-wide bg-white/15 backdrop-blur-sm">
              {course.course_type}
            </span>
          )}
          <h1 className="mt-3 text-2xl sm:text-4xl font-display font-bold leading-tight max-w-3xl">
            {course.name}
          </h1>
          {course.subtitle && (
            <p className="mt-2 text-white/85 max-w-2xl">{course.subtitle}</p>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-white/85">
            <span className="inline-flex items-center gap-1.5"><Layers size={15} /> {course.subjects_count || subjects.length || 0} subjects</span>
            <span className="inline-flex items-center gap-1.5"><BookOpen size={15} /> {course.mock_tests_count || 0} tests</span>
            {instructors.length > 0 && (
              <span className="inline-flex items-center gap-1.5"><Users size={15} /> {instructors.map((i) => i.name).join(', ')}</span>
            )}
          </div>
          {course.certificate_enabled && (
            <div className="mt-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-400/20 ring-1 ring-amber-200/40 text-amber-50 text-sm font-medium backdrop-blur-sm">
              <Award size={16} className="text-amber-200" />
              Certificate of completion — earn it by finishing 100% of this course
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        {/* Main content */}
        <div className="lg:col-span-2 space-y-6">
          {/* Tabs */}
          <div className="border-b border-surface-200 dark:border-surface-800">
            <div className="flex items-center gap-6 overflow-x-auto">
              {tabs.map((t) => (
                <TabButton key={t.key} active={tab === t.key} onClick={() => setTab(t.key)}>
                  {t.label}
                </TabButton>
              ))}
            </div>
          </div>

          {tab === 'overview' && (
            <div className="space-y-8">
              <section>
                <h2 className="text-lg font-display font-bold mb-2">Description</h2>
                <RichText value={course.description} />
              </section>

              {highlights.length > 0 && (
                <section>
                  <h2 className="text-lg font-display font-bold mb-3 flex items-center gap-2">
                    <Sparkles size={18} className="text-primary-500" /> What you will get
                  </h2>
                  <ul className="space-y-2.5">
                    {highlights.map((h, i) => (
                      <li key={i} className="flex items-start gap-2.5 text-surface-700 dark:text-surface-300">
                        <CheckCircle2 size={18} className="text-success-500 mt-0.5 shrink-0" />
                        <span>{h}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {course.refund_policy && (
                <section className="rounded-xl border border-surface-200 dark:border-surface-800 bg-surface-50 dark:bg-surface-900 p-4">
                  <h3 className="font-semibold flex items-center gap-2 mb-1.5">
                    <ShieldCheck size={17} className="text-primary-500" /> Refund Policy
                  </h3>
                  <p className="text-sm text-surface-600 dark:text-surface-400 leading-relaxed whitespace-pre-line">
                    {course.refund_policy}
                  </p>
                </section>
              )}

              {communityEnabled && (
                <section>
                  <div className="flex items-center justify-between gap-3 mb-3">
                    <h2 className="text-lg font-display font-bold flex items-center gap-2">
                      <Users size={18} className="text-primary-500" /> {communityLabel}
                    </h2>
                    <button
                      onClick={() => setTab('community')}
                      className="text-sm font-medium text-primary-600 dark:text-primary-400 hover:underline"
                    >
                      See more
                    </button>
                  </div>
                  <CourseCommunityPreview
                    courseId={course.id}
                    courseName={course.name}
                    accentColor={course.color}
                  />
                </section>
              )}
            </div>
          )}

          {tab === 'community' && communityEnabled && (
            <div className="space-y-4">
              <CourseCommunityPreview
                courseId={course.id}
                courseName={course.name}
                accentColor={course.color}
              />
              <p className="text-sm text-surface-500 leading-relaxed">
                Every question, poll, quiz and live event posted here is scoped to{' '}
                <span className="font-medium text-surface-700 dark:text-surface-200">{course.name}</span>,
                so the discussion stays focused on what you are actually studying. Answer
                well and you earn community XP that counts towards your level.
              </p>
            </div>
          )}

          {tab === 'curriculum' && (
            <div className="space-y-3">
              {subjects.length === 0 ? (
                <div className="card p-8 text-center text-surface-500">
                  <Layers size={40} className="mx-auto mb-3 text-surface-300" />
                  <p>Curriculum will be shared soon.</p>
                </div>
              ) : (
                subjects.map((s, i) => {
                  const chapters = Array.isArray(s.chapters) ? s.chapters : []
                  const isOpen = openSubjects.has(s.id)
                  return (
                    <div key={s.id} className="card overflow-hidden">
                      <button
                        type="button"
                        onClick={() => toggleSubject(s.id)}
                        className="w-full flex items-center gap-3 p-4 text-left hover:bg-surface-50 dark:hover:bg-surface-800/50 transition-colors"
                        aria-expanded={isOpen}
                      >
                        <span className="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400 flex items-center justify-center font-semibold shrink-0">
                          {i + 1}
                        </span>
                        <div className="min-w-0 flex-1">
                          <h3 className="font-semibold truncate">{s.name}</h3>
                          <p className="text-xs text-surface-400">
                            {chapters.length} {chapters.length === 1 ? 'chapter' : 'chapters'}
                            {' · '}{(s.topics_count || s.total_topics || 0)} topics
                          </p>
                        </div>
                        <ChevronDown
                          size={18}
                          className={`shrink-0 text-surface-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
                        />
                      </button>

                      <AnimatePresence initial={false}>
                        {isOpen && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.2 }}
                            className="overflow-hidden"
                          >
                            <div className="border-t border-surface-200 dark:border-surface-800 divide-y divide-surface-100 dark:divide-surface-800/70">
                              {chapters.length === 0 ? (
                                <p className="px-4 py-3 text-sm text-surface-400">Chapters coming soon.</p>
                              ) : (
                                chapters.map((ch, ci) => (
                                  <div key={ch.id} className="px-4 py-3">
                                    <div className="flex items-start gap-3">
                                      <span className="text-xs font-mono text-surface-400 mt-0.5 shrink-0 w-8">
                                        {i + 1}.{ci + 1}
                                      </span>
                                      <div className="min-w-0 flex-1 space-y-1.5">
                                        <div className="flex items-center justify-between gap-2">
                                          <h4 className="text-sm font-medium text-surface-800 dark:text-surface-100">{ch.name}</h4>
                                          {Number(ch.estimated_hours) > 0 && (
                                            <span className="text-[11px] text-surface-400 inline-flex items-center gap-1 shrink-0">
                                              <Clock size={11} /> {ch.estimated_hours}h
                                            </span>
                                          )}
                                        </div>
                                        {Array.isArray(ch.content_types) && ch.content_types.length > 0 ? (
                                          <ContentTypeBadges types={ch.content_types} />
                                        ) : (
                                          <p className="text-[11px] text-surface-400">Content coming soon</p>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                ))
                              )}
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  )
                })
              )}
            </div>
          )}

          {tab === 'instructors' && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {instructors.map((ins) => (
                <div key={ins.id} className="card p-4 flex items-center gap-3">
                  <span className="w-11 h-11 rounded-full bg-gradient-to-br from-primary-400 to-primary-600 text-white flex items-center justify-center font-semibold shrink-0">
                    {ins.name?.charAt(0).toUpperCase() || 'I'}
                  </span>
                  <div className="min-w-0">
                    <h3 className="font-semibold truncate">{ins.name}</h3>
                    <p className="text-xs text-surface-400">Faculty</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Pricing / enroll card */}
        <div className="lg:sticky lg:top-6">
          <div className="card overflow-hidden">
            <CourseThumbnail course={course} />
            <div className="p-5 space-y-4">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-surface-400">Price</p>
                {isFree ? (
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-2xl font-display font-bold text-success-600 dark:text-success-400">Free</span>
                  </div>
                ) : (
                  <div className="mt-1 flex flex-wrap items-baseline gap-2">
                    <span className="text-3xl font-display font-bold text-primary-600 dark:text-primary-400">
                      {money(course.currency, course.price)}
                    </span>
                    {hasDiscount && (
                      <>
                        <span className="text-surface-400 line-through text-sm">
                          {money(course.currency, course.original_price)}
                        </span>
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-success-50 dark:bg-success-900/30 text-success-700 dark:text-success-400">
                          <Tag size={11} /> {course.discount_percent}% off
                        </span>
                      </>
                    )}
                  </div>
                )}
              </div>

              <EnrollAction />

              {status !== 'approved' && status !== 'pending' && (
                <p className="text-xs text-center text-surface-400">
                  {enrollMode === 'payment'
                    ? 'Secure payment. Access unlocks as soon as your payment is confirmed.'
                    : enrollMode === 'self'
                    ? 'Free course — you get instant access after enrolling.'
                    : 'Your request goes to the admin for approval.'}
                </p>
              )}

              {isAdmin && (
                <button
                  onClick={() => navigate(`/courses/${course.id}/manage`)}
                  className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-surface-600 dark:text-surface-300 bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 transition-colors"
                >
                  <Settings2 size={15} /> Manage course
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default CourseDetail
