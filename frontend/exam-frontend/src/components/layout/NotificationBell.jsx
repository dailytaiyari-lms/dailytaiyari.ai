import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, CheckCheck, GraduationCap, CheckCircle2, XCircle, Megaphone, BookOpen, UserPlus } from 'lucide-react'

import { notificationService } from '../../services/notificationService'

export const NOTIFICATION_META = {
    enrollment_request: { Icon: GraduationCap, color: 'text-amber-500', bg: 'bg-amber-100 dark:bg-amber-900/30' },
    enrollment_approved: { Icon: CheckCircle2, color: 'text-green-500', bg: 'bg-green-100 dark:bg-green-900/30' },
    enrollment_rejected: { Icon: XCircle, color: 'text-red-500', bg: 'bg-red-100 dark:bg-red-900/30' },
    announcement: { Icon: Megaphone, color: 'text-primary-500', bg: 'bg-primary-100 dark:bg-primary-900/30' },
    course_assigned: { Icon: BookOpen, color: 'text-blue-500', bg: 'bg-blue-100 dark:bg-blue-900/30' },
    account_created: { Icon: UserPlus, color: 'text-primary-500', bg: 'bg-primary-100 dark:bg-primary-900/30' },
}

export const timeAgo = (iso) => {
    if (!iso) return ''
    const diff = Date.now() - new Date(iso).getTime()
    const s = Math.floor(diff / 1000)
    if (s < 60) return 'just now'
    const m = Math.floor(s / 60)
    if (m < 60) return `${m}m ago`
    const h = Math.floor(m / 60)
    if (h < 24) return `${h}h ago`
    const d = Math.floor(h / 24)
    if (d < 7) return `${d}d ago`
    return new Date(iso).toLocaleDateString()
}

const NotificationBell = () => {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [open, setOpen] = useState(false)
    const ref = useRef(null)

    const { data: unreadCount = 0 } = useQuery({
        queryKey: ['notifications', 'unread-count'],
        queryFn: () => notificationService.getUnreadCount(),
        refetchInterval: 45 * 1000,
        refetchOnWindowFocus: true,
    })

    const { data: listData, isLoading } = useQuery({
        queryKey: ['notifications', 'recent'],
        queryFn: () => notificationService.getNotifications({ page_size: 8 }),
        enabled: open,
    })
    const items = listData?.results || []

    // Close on outside click.
    useEffect(() => {
        if (!open) return
        const onClick = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
        document.addEventListener('mousedown', onClick)
        return () => document.removeEventListener('mousedown', onClick)
    }, [open])

    const refreshCounts = () => {
        queryClient.invalidateQueries({ queryKey: ['notifications'] })
    }

    const openItem = async (n) => {
        setOpen(false)
        try {
            if (!n.is_read) {
                await notificationService.markRead(n.id)
                refreshCounts()
            }
        } catch { /* non-blocking */ }
        if (n.link) navigate(n.link)
    }

    const markAll = async () => {
        try { await notificationService.markAllRead(); refreshCounts() } catch { /* noop */ }
    }

    return (
        <div className="relative" ref={ref}>
            <button
                onClick={() => setOpen((v) => !v)}
                className="btn-icon relative"
                aria-label="Notifications"
            >
                <Bell className="w-5 h-5" />
                {unreadCount > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 flex items-center justify-center rounded-full bg-red-500 text-white text-[10px] font-bold leading-none ring-2 ring-white dark:ring-surface-900">
                        {unreadCount > 99 ? '99+' : unreadCount}
                    </span>
                )}
            </button>

            <AnimatePresence>
                {open && (
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: 10 }}
                        className="absolute right-0 mt-2 w-80 sm:w-96 max-w-[calc(100vw-2rem)] card shadow-xl overflow-hidden z-50"
                    >
                        <div className="flex items-center justify-between px-4 py-3 border-b border-surface-200 dark:border-surface-700">
                            <p className="font-semibold">Notifications</p>
                            {unreadCount > 0 && (
                                <button onClick={markAll} className="text-xs font-medium text-primary-600 hover:underline flex items-center gap-1">
                                    <CheckCheck className="w-3.5 h-3.5" /> Mark all read
                                </button>
                            )}
                        </div>

                        <div className="max-h-96 overflow-y-auto">
                            {isLoading ? (
                                <div className="p-6 text-center text-sm text-surface-500">Loading…</div>
                            ) : items.length === 0 ? (
                                <div className="p-8 text-center">
                                    <Bell className="w-8 h-8 mx-auto text-surface-300 mb-2" />
                                    <p className="text-sm text-surface-500">You're all caught up.</p>
                                </div>
                            ) : (
                                items.map((n) => {
                                    const meta = NOTIFICATION_META[n.type] || NOTIFICATION_META.announcement
                                    const { Icon } = meta
                                    return (
                                        <button
                                            key={n.id}
                                            onClick={() => openItem(n)}
                                            className={`w-full text-left flex gap-3 px-4 py-3 border-b border-surface-100 dark:border-surface-800 hover:bg-surface-50 dark:hover:bg-surface-800/50 transition-colors ${!n.is_read ? 'bg-primary-50/40 dark:bg-primary-900/10' : ''}`}
                                        >
                                            <div className={`shrink-0 w-9 h-9 rounded-full flex items-center justify-center ${meta.bg}`}>
                                                <Icon className={`w-4.5 h-4.5 ${meta.color}`} />
                                            </div>
                                            <div className="min-w-0 flex-1">
                                                <p className={`text-sm ${!n.is_read ? 'font-semibold' : 'font-medium'} truncate`}>{n.title}</p>
                                                {n.body && <p className="text-xs text-surface-500 line-clamp-2 mt-0.5">{n.body}</p>}
                                                <p className="text-[11px] text-surface-400 mt-1">{timeAgo(n.created_at)}</p>
                                            </div>
                                            {!n.is_read && <span className="shrink-0 w-2 h-2 rounded-full bg-primary-500 mt-2" />}
                                        </button>
                                    )
                                })
                            )}
                        </div>

                        <button
                            onClick={() => { setOpen(false); navigate('/notifications') }}
                            className="w-full py-3 text-sm font-medium text-primary-600 hover:bg-surface-50 dark:hover:bg-surface-800/50 transition-colors border-t border-surface-200 dark:border-surface-700"
                        >
                            See all notifications
                        </button>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    )
}

export default NotificationBell
