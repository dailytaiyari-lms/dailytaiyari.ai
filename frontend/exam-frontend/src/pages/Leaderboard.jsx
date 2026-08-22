import { useState } from 'react'
import { motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { gamificationService } from '../services/gamificationService'
import { useFeatureLabel } from '../context/tenantStore'
import { useAuthStore } from '../context/authStore'
import LeaderboardRow from '../components/common/LeaderboardRow'
import Loading from '../components/common/Loading'
import {
  Trophy,
  Award,
  Medal,
  ChevronUp,
  ChevronDown
} from 'lucide-react'

const PodiumAvatar = ({ entry, className }) => (
  <div className={`rounded-full overflow-hidden flex items-center justify-center text-white font-bold mb-2 mx-auto ${className}`}>
    {entry.student_avatar ? (
      <img
        src={entry.student_avatar}
        alt={entry.student_name || 'Avatar'}
        className="w-full h-full object-cover"
        onError={(e) => { e.currentTarget.style.display = 'none' }}
      />
    ) : (
      entry.student_name?.charAt(0)
    )}
  </div>
)

const Leaderboard = () => {
  const [period, setPeriod] = useState('daily')
  const leaderboardLabel = useFeatureLabel('leaderboard', 'Leaderboard')
  const { profile } = useAuthStore()

  const { data: leaderboardData, isLoading } = useQuery({
    queryKey: ['leaderboard', period],
    queryFn: () => gamificationService.getLeaderboard(period),
  })

  const { data: badges } = useQuery({
    queryKey: ['myBadges'],
    queryFn: () => gamificationService.getMyBadges(),
  })

  const periods = [
    { value: 'daily', label: 'Today' },
    { value: 'weekly', label: 'This Week' },
    { value: 'monthly', label: 'This Month' },
    { value: 'all_time', label: 'All Time' },
  ]

  const entries = leaderboardData?.entries || []
  const userRank = leaderboardData?.user_rank

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            {leaderboardLabel} <Trophy className="text-warning-500" />
          </h1>
          <p className="text-surface-500 mt-1">Compete with other students</p>
        </div>
      </div>

      {/* Your Rank Card */}
      {userRank && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="card p-6 bg-gradient-to-r from-primary-500 to-accent-500 text-white"
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="text-white/80">Your Current Rank</p>
              <div className="flex items-baseline gap-2 mt-1">
                <span className="text-4xl font-bold">#{userRank.rank}</span>
                {userRank.rank_change !== 0 && (
                  <span className={`text-sm px-2 py-0.5 rounded-full flex items-center gap-1 ${userRank.rank_change > 0
                      ? 'bg-success-500/30 text-white'
                      : 'bg-error-500/30 text-white'
                    }`}>
                    {userRank.rank_change > 0 ? <ChevronUp size={14} /> : <ChevronDown size={14} />} {Math.abs(userRank.rank_change)}
                  </span>
                )}
              </div>
            </div>
            <div className="text-right">
              <p className="text-white/80">XP Earned</p>
              <p className="text-3xl font-bold">{userRank.xp?.toLocaleString()}</p>
            </div>
          </div>
        </motion.div>
      )}

      {/* Period Tabs */}
      <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-hide">
        {periods.map((p) => (
          <button
            key={p.value}
            onClick={() => setPeriod(p.value)}
            className={`px-4 py-2 rounded-full whitespace-nowrap transition-colors ${period === p.value
                ? 'bg-primary-500 text-white'
                : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200'
              }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Leaderboard List */}
        <div className="lg:col-span-2">
          <div className="card p-4">
            {isLoading ? (
              <Loading />
            ) : entries.length > 0 ? (
              <div className="space-y-2">
                {entries.map((entry, index) => (
                  <LeaderboardRow
                    key={entry.id || index}
                    entry={entry}
                    rank={index + 1}
                    isCurrentUser={String(entry.id) === String(profile?.id)}
                  />
                ))}
              </div>
            ) : (
              <div className="text-center py-12 text-surface-500">
                <div className="flex justify-center mb-4 text-surface-300">
                  <Trophy size={64} />
                </div>
                <p>No rankings yet for this period</p>
                <p className="text-sm mt-1">Start studying to get on the board!</p>
              </div>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Top 3 Podium */}
          <div className="card p-5">
            <h3 className="font-semibold mb-4">Top 3</h3>
            <div className="flex items-end justify-center gap-4">
              {/* 2nd Place */}
              {entries[1] && (
                <div className="text-center">
                  <PodiumAvatar
                    entry={entries[1]}
                    className="w-16 h-16 bg-gradient-to-br from-gray-300 to-gray-400 text-xl"
                  />
                  <p className="text-xs font-medium truncate w-16">{entries[1].student_name?.split(' ')[0]}</p>
                  <div className="h-16 w-16 bg-gray-200 dark:bg-surface-700 rounded-t-lg mt-2 flex items-center justify-center text-surface-400">
                    <Award size={32} />
                  </div>
                </div>
              )}

              {/* 1st Place */}
              {entries[0] && (
                <div className="text-center -mb-4">
                  <PodiumAvatar
                    entry={entries[0]}
                    className="w-20 h-20 bg-gradient-to-br from-yellow-400 to-yellow-500 text-2xl ring-4 ring-yellow-200"
                  />
                  <p className="text-sm font-medium truncate w-20">{entries[0].student_name?.split(' ')[0]}</p>
                  <div className="h-24 w-16 bg-yellow-100 dark:bg-yellow-900/30 rounded-t-lg mt-2 flex items-center justify-center mx-auto text-warning-500">
                    <Award size={40} />
                  </div>
                </div>
              )}

              {/* 3rd Place */}
              {entries[2] && (
                <div className="text-center">
                  <PodiumAvatar
                    entry={entries[2]}
                    className="w-16 h-16 bg-gradient-to-br from-amber-600 to-amber-700 text-xl"
                  />
                  <p className="text-xs font-medium truncate w-16">{entries[2].student_name?.split(' ')[0]}</p>
                  <div className="h-12 w-16 bg-amber-100 dark:bg-amber-900/30 rounded-t-lg mt-2 flex items-center justify-center text-orange-400">
                    <Award size={28} />
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Your Badges */}
          <div className="card p-5">
            <h3 className="font-semibold mb-4">Your Badges</h3>
            {badges?.length > 0 ? (
              <div className="grid grid-cols-4 gap-2">
                {badges.slice(0, 8).map((badge) => (
                  <div
                    key={badge.id}
                    className="aspect-square rounded-xl bg-surface-100 dark:bg-surface-800 flex items-center justify-center text-primary-500"
                    title={badge.badge?.name}
                  >
                    <Award size={24} />
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-center text-surface-500 py-4">
                Complete challenges to earn badges!
              </p>
            )}
          </div>

          {/* Stats */}
          <div className="card p-5">
            <h3 className="font-semibold mb-4">Your Stats</h3>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-surface-500">Total XP</span>
                <span className="font-semibold">{profile?.total_xp?.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-surface-500">Level</span>
                <span className="font-semibold">{profile?.current_level}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-surface-500">Questions</span>
                <span className="font-semibold">{profile?.total_questions_attempted}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-surface-500">Accuracy</span>
                <span className="font-semibold">{Math.round(profile?.overall_accuracy || 0)}%</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Leaderboard

