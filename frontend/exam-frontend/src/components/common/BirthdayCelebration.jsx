import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import confetti from 'canvas-confetti'
import { Cake, Gift, PartyPopper, Sparkles, X } from 'lucide-react'

import { notificationService } from '../../services/notificationService'
import { useAuthStore } from '../../context/authStore'
import { useTenantStore } from '../../context/tenantStore'

/**
 * Full-screen birthday moment.
 *
 * Polls for a pending birthday greeting (created by the backend's daily sweep)
 * and, when one exists, takes over the screen with a confetti-backed greeting
 * card branded with the institution's logo and name. Dismissing marks the
 * underlying notification read, so the celebration plays exactly once — it
 * stays in the notification bell afterwards.
 */

// Balloon positions/colours are fixed rather than random so the composition is
// deliberately balanced instead of occasionally clumping.
const BALLOONS = [
    { left: '6%', delay: 0, hue: 'from-pink-400 to-rose-500', size: 44 },
    { left: '20%', delay: 0.5, hue: 'from-amber-300 to-orange-500', size: 32 },
    { left: '35%', delay: 1.1, hue: 'from-violet-400 to-purple-600', size: 38 },
    { left: '58%', delay: 0.3, hue: 'from-sky-400 to-blue-600', size: 36 },
    { left: '74%', delay: 1.4, hue: 'from-emerald-400 to-teal-600', size: 30 },
    { left: '89%', delay: 0.8, hue: 'from-fuchsia-400 to-pink-600', size: 42 },
]

const CONFETTI_COLORS = ['#f97316', '#fbbf24', '#ec4899', '#8b5cf6', '#3b82f6', '#10b981']

const fireConfetti = () => {
    const base = { colors: CONFETTI_COLORS, disableForReducedMotion: true, zIndex: 10000 }
    // Opening burst from the centre, then two side cannons for depth.
    confetti({ ...base, particleCount: 120, spread: 90, startVelocity: 45, origin: { y: 0.5 } })
    setTimeout(() => {
        confetti({ ...base, particleCount: 70, angle: 60, spread: 70, origin: { x: 0, y: 0.7 } })
        confetti({ ...base, particleCount: 70, angle: 120, spread: 70, origin: { x: 1, y: 0.7 } })
    }, 280)
}

const BirthdayCelebration = () => {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
    const tenant = useTenantStore((s) => s.tenant)
    const [dismissed, setDismissed] = useState(false)
    const timers = useRef([])

    const { data: celebration } = useQuery({
        queryKey: ['notifications', 'birthday'],
        queryFn: () => notificationService.getBirthday(),
        enabled: Boolean(isAuthenticated),
        // A user can cross midnight with the tab open; an hourly re-check picks
        // the greeting up without needing a reload.
        refetchInterval: 60 * 60 * 1000,
        refetchOnWindowFocus: false,
        retry: false,
        staleTime: 5 * 60 * 1000,
    })

    const open = Boolean(celebration) && !dismissed

    useEffect(() => {
        if (!open) return
        fireConfetti()
        // A second, gentler wave keeps the moment alive while the card settles.
        timers.current.push(setTimeout(fireConfetti, 2200))
        return () => {
            timers.current.forEach(clearTimeout)
            timers.current = []
        }
    }, [open])

    // Escape closes, and the page behind must not scroll while we're on top.
    useEffect(() => {
        if (!open) return
        const onKey = (e) => { if (e.key === 'Escape') close() }
        const previousOverflow = document.body.style.overflow
        document.body.style.overflow = 'hidden'
        window.addEventListener('keydown', onKey)
        return () => {
            document.body.style.overflow = previousOverflow
            window.removeEventListener('keydown', onKey)
        }
    }, [open])

    const close = async () => {
        setDismissed(true)
        try {
            if (celebration?.id) {
                await notificationService.markRead(celebration.id)
                queryClient.invalidateQueries({ queryKey: ['notifications'] })
            }
        } catch { /* dismissal is cosmetic — never block the UI */ }
    }

    const openLink = async () => {
        const link = celebration?.link
        await close()
        if (link) navigate(link)
    }

    if (typeof document === 'undefined') return null

    const name = celebration?.first_name || 'there'
    const institution = celebration?.tenant_name || tenant?.name || ''
    const age = celebration?.age
    const isPast = celebration?.is_past_student

    return createPortal(
        <AnimatePresence>
            {open && (
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.25 }}
                    className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-surface-950/70 backdrop-blur-sm"
                    role="dialog"
                    aria-modal="true"
                    aria-label="Birthday greeting"
                    onClick={close}
                >
                    {/* Floating balloons drifting up behind the card */}
                    <div className="pointer-events-none absolute inset-0 overflow-hidden">
                        {BALLOONS.map((b, i) => (
                            <motion.div
                                key={i}
                                initial={{ y: '110vh', opacity: 0 }}
                                animate={{ y: '-25vh', opacity: [0, 1, 1, 0] }}
                                transition={{
                                    duration: 9 + i,
                                    delay: b.delay,
                                    repeat: Infinity,
                                    ease: 'linear',
                                }}
                                style={{ left: b.left, width: b.size, height: b.size * 1.2 }}
                                className="absolute"
                            >
                                <div className={`w-full h-full rounded-[50%] bg-gradient-to-br ${b.hue} shadow-lg opacity-80`} />
                                <div className="mx-auto w-px h-16 bg-white/30" />
                            </motion.div>
                        ))}
                    </div>

                    <motion.div
                        initial={{ scale: 0.82, y: 40, opacity: 0 }}
                        animate={{ scale: 1, y: 0, opacity: 1 }}
                        exit={{ scale: 0.9, y: 20, opacity: 0 }}
                        transition={{ type: 'spring', damping: 20, stiffness: 260 }}
                        onClick={(e) => e.stopPropagation()}
                        className="relative w-full max-w-md overflow-hidden rounded-3xl bg-white dark:bg-surface-900 shadow-2xl ring-1 ring-white/20"
                    >
                        {/* Festive header */}
                        <div className="relative overflow-hidden bg-gradient-to-br from-primary-500 via-pink-500 to-violet-600 px-6 pt-8 pb-14 text-center">
                            {/* Slow shimmer sweeping across the header */}
                            <motion.div
                                aria-hidden
                                initial={{ x: '-120%' }}
                                animate={{ x: '120%' }}
                                transition={{ duration: 3.5, repeat: Infinity, ease: 'easeInOut' }}
                                className="absolute inset-y-0 w-1/3 bg-white/20 blur-xl"
                            />

                            <button
                                onClick={close}
                                aria-label="Close"
                                className="absolute right-3 top-3 z-10 rounded-full p-1.5 text-white/80 hover:bg-white/20 hover:text-white transition-colors"
                            >
                                <X className="w-5 h-5" />
                            </button>

                            {/* Institution branding */}
                            <div className="relative flex items-center justify-center gap-2 mb-5">
                                {tenant?.logo && (
                                    <img
                                        src={tenant.logo}
                                        alt={institution}
                                        className="h-7 w-auto max-w-[120px] rounded bg-white/90 p-0.5 object-contain"
                                    />
                                )}
                                {institution && (
                                    <span className="text-xs font-semibold uppercase tracking-widest text-white/90">
                                        {institution}
                                    </span>
                                )}
                            </div>

                            <motion.div
                                animate={{ rotate: [0, -8, 8, -5, 0], y: [0, -6, 0] }}
                                transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }}
                                className="relative mx-auto flex h-24 w-24 items-center justify-center rounded-full bg-white/20 backdrop-blur ring-4 ring-white/30"
                            >
                                <Cake className="h-12 w-12 text-white drop-shadow" />
                            </motion.div>

                            <Sparkles className="absolute left-8 top-16 h-5 w-5 text-white/70 animate-pulse" />
                            <PartyPopper className="absolute right-9 top-20 h-6 w-6 text-white/80" />
                        </div>

                        {/* Message */}
                        <div className="relative -mt-8 rounded-t-3xl bg-white dark:bg-surface-900 px-6 pb-7 pt-7 text-center">
                            {age ? (
                                <span className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-primary-100 dark:bg-primary-900/30 px-3 py-1 text-xs font-bold text-primary-700 dark:text-primary-300">
                                    <Gift className="h-3.5 w-3.5" /> Turning {age} today
                                </span>
                            ) : null}

                            <h2 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-surface-900 dark:text-white">
                                Happy Birthday, {name}! 🎂
                            </h2>

                            <p className="mt-3 text-sm leading-relaxed text-surface-600 dark:text-surface-300">
                                {celebration?.body}
                            </p>

                            <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
                                <button onClick={openLink} className="btn-primary px-6">
                                    {isPast ? 'See what’s new' : 'Let’s go 🎉'}
                                </button>
                                <button
                                    onClick={close}
                                    className="px-6 py-2.5 text-sm font-semibold text-surface-500 hover:text-surface-800 dark:hover:text-surface-200 transition-colors"
                                >
                                    Thanks!
                                </button>
                            </div>
                        </div>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>,
        document.body,
    )
}

export default BirthdayCelebration
