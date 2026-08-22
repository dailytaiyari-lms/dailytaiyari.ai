import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
    MessageCircle, MessageSquare, ThumbsUp, Eye, CheckCircle,
    Plus, Filter, TrendingUp, Clock, HelpCircle,
    BarChart3, Zap, Trophy, Users, BookOpen, Globe, Calendar, EyeOff,
    Maximize2, Minimize2, X
} from 'lucide-react'
import { communityService } from '../services/communityService'
import { useFeatureLabel } from '../context/tenantStore'
import { useAuthStore } from '../context/authStore'
import CreatePostModal from '../components/community/CreatePostModal'
import PostCard from '../components/community/PostCard'
import CommunityLeaderboard from '../components/community/CommunityLeaderboard'
import SearchableSelect from '../components/common/SearchableSelect'
import toast from 'react-hot-toast'

const Community = () => {
    const navigate = useNavigate()
    const communityLabel = useFeatureLabel('community', 'Community Forum')
    const queryClient = useQueryClient()
    const [searchParams, setSearchParams] = useSearchParams()
    const { user, profile } = useAuthStore()
    const role = user?.role || profile?.user?.role
    const isAdmin = role === 'admin' || role === 'instructor'
    const [activeTab, setActiveTab] = useState('all')
    const [sortBy, setSortBy] = useState('recent')
    // Deep links from a course page land here as /community?course=<id> so the
    // forum opens already focused on that course's discussions.
    const [courseFilter, setCourseFilter] = useState(() => searchParams.get('course') || 'all')
    const [showCreateModal, setShowCreateModal] = useState(false)
    const [createType, setCreateType] = useState('question')
    const [focusMode, setFocusMode] = useState(false)
    const containerRef = useRef(null)

    // Keep the URL in sync so the scoped view is shareable / refresh-safe.
    useEffect(() => {
        const current = searchParams.get('course') || 'all'
        if (current === courseFilter) return
        const next = new URLSearchParams(searchParams)
        if (courseFilter === 'all') next.delete('course')
        else next.set('course', courseFilter)
        setSearchParams(next, { replace: true })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [courseFilter])

    // Back/forward navigation should move the filter too.
    useEffect(() => {
        const fromUrl = searchParams.get('course') || 'all'
        if (fromUrl !== courseFilter) setCourseFilter(fromUrl)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [searchParams])

    // Immersive "full screen" reading mode for the forum.
    const toggleFocusMode = () => {
        const next = !focusMode
        setFocusMode(next)
        try {
            if (next && containerRef.current?.requestFullscreen) {
                containerRef.current.requestFullscreen().catch(() => { })
            } else if (!next && document.fullscreenElement) {
                document.exitFullscreen?.().catch(() => { })
            }
        } catch {
            /* Fullscreen API unavailable — the in-page overlay still applies. */
        }
    }

    useEffect(() => {
        const onFsChange = () => {
            if (!document.fullscreenElement) setFocusMode(false)
        }
        const onKey = (e) => {
            if (e.key === 'Escape') setFocusMode(false)
        }
        document.addEventListener('fullscreenchange', onFsChange)
        document.addEventListener('keydown', onKey)
        return () => {
            document.removeEventListener('fullscreenchange', onFsChange)
            document.removeEventListener('keydown', onKey)
        }
    }, [])

    // Courses the user belongs to (for scoping the forum by course).
    const { data: filterOptions } = useQuery({
        queryKey: ['communityFilterOptions'],
        queryFn: () => communityService.getFilterOptions()
    })
    const courses = filterOptions?.courses || []

    // Fetch posts. The "hidden" tab is admin-only and asks the backend for
    // moderated posts (status=hidden) so admins can review and restore them.
    const isHiddenView = activeTab === 'hidden'
    const { data: postsData, isLoading: postsLoading } = useQuery({
        queryKey: ['communityPosts', activeTab, sortBy, courseFilter],
        queryFn: () => communityService.getPosts({
            type: (activeTab === 'all' || activeTab === 'my_posts' || isHiddenView) ? undefined : activeTab,
            sort: sortBy,
            my_posts: activeTab === 'my_posts' ? 'true' : undefined,
            status: isHiddenView ? 'hidden' : undefined,
            course: courseFilter === 'all' ? undefined : courseFilter
        })
    })

    // Fetch user stats
    const { data: myStats } = useQuery({
        queryKey: ['communityStats'],
        queryFn: () => communityService.getMyStats()
    })

    // Like mutation
    const likeMutation = useMutation({
        mutationFn: (postId) => communityService.likePost(postId),
        onSuccess: () => {
            queryClient.invalidateQueries(['communityPosts'])
        }
    })

    const hideMutation = useMutation({
        mutationFn: (postId) => communityService.hidePost(postId),
        onSuccess: () => {
            toast.success('Post hidden')
            queryClient.invalidateQueries(['communityPosts'])
        },
        onError: () => toast.error('Could not hide post')
    })

    const unhideMutation = useMutation({
        mutationFn: (postId) => communityService.unhidePost(postId),
        onSuccess: () => {
            toast.success('Post restored')
            queryClient.invalidateQueries(['communityPosts'])
        },
        onError: () => toast.error('Could not restore post')
    })

    const deleteMutation = useMutation({
        mutationFn: (postId) => communityService.deletePost(postId),
        onSuccess: () => {
            toast.success('Post deleted')
            queryClient.invalidateQueries(['communityPosts'])
        },
        onError: () => toast.error('Could not delete post')
    })

    const posts = postsData?.results || postsData || []

    const tabs = [
        { id: 'all', label: 'All Posts', icon: Users },
        { id: 'question', label: 'Questions', icon: HelpCircle },
        { id: 'poll', label: 'Polls', icon: BarChart3 },
        { id: 'quiz', label: 'Quizzes', icon: Zap },
        { id: 'event', label: 'Events', icon: Calendar },
        { id: 'my_posts', label: 'My Posts', icon: MessageCircle },
        ...(isAdmin ? [{ id: 'hidden', label: 'Hidden', icon: EyeOff }] : []),
    ]

    const sortOptions = [
        { id: 'recent', label: 'Recent', icon: Clock },
        { id: 'popular', label: 'Popular', icon: TrendingUp },
        { id: 'unanswered', label: 'Unanswered', icon: HelpCircle },
    ]

    const handleCreatePost = (type) => {
        setCreateType(type)
        setShowCreateModal(true)
    }

    const activeCourse = courses.find((c) => String(c.id) === String(courseFilter))

    return (
        <div
            ref={containerRef}
            className={
                focusMode
                    ? 'fixed inset-0 z-50 overflow-y-auto bg-surface-50 dark:bg-surface-950 p-4 sm:p-8 space-y-6'
                    : 'space-y-6'
            }
        >
            {/* Course scope banner — shown when the forum was opened from a course */}
            {activeCourse && (
                <motion.div
                    initial={{ opacity: 0, y: -8 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-primary-600 to-accent-600 text-white px-5 py-4 flex flex-wrap items-center justify-between gap-3"
                >
                    <div className="absolute -top-10 -right-6 w-32 h-32 rounded-full bg-white/10" />
                    <div className="relative min-w-0">
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-white/70">
                            Focused discussions
                        </p>
                        <h2 className="text-lg font-display font-bold truncate flex items-center gap-2">
                            <BookOpen size={18} /> {activeCourse.name}
                        </h2>
                    </div>
                    <button
                        onClick={() => setCourseFilter('all')}
                        className="relative inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-sm font-medium bg-white/15 hover:bg-white/25 ring-1 ring-white/20 backdrop-blur-sm transition-colors"
                    >
                        <X size={14} /> Clear course filter
                    </button>
                </motion.div>
            )}

            {/* Header */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                    <h1 className="text-2xl font-display font-bold">{communityLabel}</h1>
                    <p className="text-surface-500 mt-1">
                        Ask questions, share knowledge, earn XP!
                    </p>
                </div>

                {/* Create Buttons */}
                <div className="flex items-center gap-2">
                    <button
                        onClick={toggleFocusMode}
                        className="btn-secondary flex items-center gap-2"
                        title={focusMode ? 'Exit full screen' : 'Read the forum full screen'}
                    >
                        {focusMode ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
                        <span className="hidden lg:inline">{focusMode ? 'Exit full screen' : 'Full screen'}</span>
                    </button>
                    <motion.button
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => handleCreatePost('question')}
                        className="btn-primary flex items-center gap-2"
                    >
                        <Plus size={18} />
                        <span className="hidden sm:inline">Ask Question</span>
                    </motion.button>
                    <motion.button
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => handleCreatePost('poll')}
                        className="btn-secondary flex items-center gap-2"
                    >
                        <BarChart3 size={18} />
                        <span className="hidden sm:inline">Create Poll</span>
                    </motion.button>
                    <motion.button
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => handleCreatePost('quiz')}
                        className="btn-secondary flex items-center gap-2"
                    >
                        <Zap size={18} />
                        <span className="hidden sm:inline">Create Quiz</span>
                    </motion.button>
                    {isAdmin && (
                        <motion.button
                            whileHover={{ scale: 1.02 }}
                            whileTap={{ scale: 0.98 }}
                            onClick={() => handleCreatePost('event')}
                            className="btn-secondary flex items-center gap-2"
                        >
                            <Calendar size={18} />
                            <span className="hidden sm:inline">Create Event</span>
                        </motion.button>
                    )}
                </div>
            </div>

            {/* Stats Cards */}
            {myStats && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="card p-4 text-center"
                    >
                        <div className="text-2xl font-bold text-primary-600">{myStats.posts_count || 0}</div>
                        <div className="text-sm text-surface-500">Posts</div>
                    </motion.div>
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.1 }}
                        className="card p-4 text-center"
                    >
                        <div className="text-2xl font-bold text-accent-600">{myStats.answers_count || 0}</div>
                        <div className="text-sm text-surface-500">Answers</div>
                    </motion.div>
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.2 }}
                        className="card p-4 text-center"
                    >
                        <div className="text-2xl font-bold text-warning-600 flex items-center justify-center gap-1">
                            <Trophy size={20} />
                            {myStats.best_answers_count || 0}
                        </div>
                        <div className="text-sm text-surface-500">Best Answers</div>
                    </motion.div>
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.3 }}
                        className="card p-4 text-center"
                    >
                        <div className="text-2xl font-bold text-success-600">{myStats.total_community_xp || 0}</div>
                        <div className="text-sm text-surface-500">Community XP</div>
                    </motion.div>
                </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
                {/* Main Content */}
                <div className="lg:col-span-3 space-y-4">
                    {/* Tabs */}
                    <div className="card p-2">
                        <div className="flex flex-wrap gap-1">
                            {tabs.map((tab) => (
                                <button
                                    key={tab.id}
                                    onClick={() => setActiveTab(tab.id)}
                                    className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === tab.id
                                        ? 'bg-primary-500 text-white'
                                        : 'text-surface-600 hover:bg-surface-100 dark:hover:bg-surface-800'
                                        }`}
                                >
                                    <tab.icon size={16} />
                                    {tab.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Course Filter */}
                    <div className="flex items-center gap-2 flex-wrap">
                        <BookOpen size={16} className="text-surface-500" />
                        <span className="text-sm text-surface-500">Course:</span>
                        <button
                            onClick={() => setCourseFilter('all')}
                            className={`flex items-center gap-1 px-3 py-1.5 rounded-full text-sm transition-all ${courseFilter === 'all'
                                ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-600'
                                : 'text-surface-500 hover:bg-surface-100 dark:hover:bg-surface-800'
                                }`}
                        >
                            <Users size={14} />
                            All
                        </button>
                        <button
                            onClick={() => setCourseFilter('global')}
                            className={`flex items-center gap-1 px-3 py-1.5 rounded-full text-sm transition-all ${courseFilter === 'global'
                                ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-600'
                                : 'text-surface-500 hover:bg-surface-100 dark:hover:bg-surface-800'
                                }`}
                        >
                            <Globe size={14} />
                            Everyone
                        </button>
                        {courses.length > 0 && (
                            <SearchableSelect
                                options={courses.map((c) => ({ value: c.id, label: c.name }))}
                                value={courseFilter === 'all' || courseFilter === 'global' ? '' : courseFilter}
                                onChange={(val) => setCourseFilter(val || 'all')}
                                placeholder="Filter by course"
                                searchPlaceholder="Search courses..."
                                buttonClassName={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm transition-all border ${courseFilter !== 'all' && courseFilter !== 'global'
                                    ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-600 border-primary-200 dark:border-primary-800'
                                    : 'text-surface-500 border-surface-200 dark:border-surface-700 hover:bg-surface-100 dark:hover:bg-surface-800'
                                    }`}
                            />
                        )}
                    </div>

                    {/* Sort Options */}
                    <div className="flex items-center gap-2">
                        <Filter size={16} className="text-surface-500" />
                        <span className="text-sm text-surface-500">Sort by:</span>
                        {sortOptions.map((option) => (
                            <button
                                key={option.id}
                                onClick={() => setSortBy(option.id)}
                                className={`flex items-center gap-1 px-3 py-1.5 rounded-full text-sm transition-all ${sortBy === option.id
                                    ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-600'
                                    : 'text-surface-500 hover:bg-surface-100 dark:hover:bg-surface-800'
                                    }`}
                            >
                                <option.icon size={14} />
                                {option.label}
                            </button>
                        ))}
                    </div>

                    {/* Posts List */}
                    <div className="space-y-4">
                        {isHiddenView && posts.length > 0 && (
                            <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-sm text-amber-800 dark:text-amber-300">
                                <EyeOff size={16} className="mt-0.5 shrink-0" />
                                <span>These posts are hidden from the community. Use a post's menu to <strong>Unhide</strong> and restore it, or delete it permanently.</span>
                            </div>
                        )}
                        <AnimatePresence mode="popLayout">
                            {postsLoading ? (
                                <motion.div key="loading" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
                                    {[0, 1, 2].map((i) => (
                                        <div key={i} className="card p-5 animate-pulse space-y-3">
                                            <div className="flex items-center gap-3">
                                                <div className="w-10 h-10 rounded-full bg-surface-200 dark:bg-surface-800" />
                                                <div className="h-3 w-32 rounded bg-surface-200 dark:bg-surface-800" />
                                            </div>
                                            <div className="h-4 w-3/4 rounded bg-surface-200 dark:bg-surface-800" />
                                            <div className="h-3 w-full rounded bg-surface-100 dark:bg-surface-800" />
                                        </div>
                                    ))}
                                </motion.div>
                            ) : posts.length > 0 ? (
                                posts.map((post, index) => (
                                    <motion.div
                                        key={post.id}
                                        initial={{ opacity: 0, y: 20 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        exit={{ opacity: 0, y: -20 }}
                                        transition={{ delay: index * 0.05 }}
                                    >
                                        <PostCard
                                            post={post}
                                            onLike={() => likeMutation.mutate(post.id)}
                                            onClick={() => navigate(`/community/${post.id}`)}
                                            isAdmin={isAdmin}
                                            isAuthor={user?.id === post.author?.id}
                                            onHide={() => hideMutation.mutate(post.id)}
                                            onUnhide={() => unhideMutation.mutate(post.id)}
                                            onDelete={() => {
                                                if (window.confirm('Delete this post permanently?')) {
                                                    deleteMutation.mutate(post.id)
                                                }
                                            }}
                                        />
                                    </motion.div>
                                ))
                            ) : (
                                <motion.div
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="card p-12 text-center"
                                >
                                    {isHiddenView ? (
                                        <>
                                            <EyeOff size={48} className="text-surface-400 mb-4 mx-auto" />
                                            <h3 className="text-lg font-semibold mb-2">No hidden posts</h3>
                                            <p className="text-surface-500">
                                                Posts you hide from the community will appear here so you can review or restore them.
                                            </p>
                                        </>
                                    ) : (
                                        <>
                                            <MessageSquare size={48} className="text-surface-400 mb-4 mx-auto" />
                                            <h3 className="text-lg font-semibold mb-2">No posts yet</h3>
                                            <p className="text-surface-500 mb-4">
                                                Be the first to start a discussion!
                                            </p>
                                            <button
                                                onClick={() => handleCreatePost('question')}
                                                className="btn-primary"
                                            >
                                                Ask a Question
                                            </button>
                                        </>
                                    )}
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </div>
                </div>

                {/* Sidebar - Leaderboard */}
                <div className="lg:col-span-1">
                    <CommunityLeaderboard />
                </div>
            </div>

            {/* Create Post Modal */}
            <CreatePostModal
                isOpen={showCreateModal}
                onClose={() => setShowCreateModal(false)}
                postType={createType}
                defaultCourseId={activeCourse ? String(activeCourse.id) : null}
            />
        </div>
    )
}

export default Community
