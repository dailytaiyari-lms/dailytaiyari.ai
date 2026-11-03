import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuthStore } from '../../context/authStore'
import toast from 'react-hot-toast'
import {
  Rocket,
  Sunrise,
  Sun,
  Sunset,
  Moon,
  ChevronRight,
} from 'lucide-react'

const studyTimes = [
  { value: 'morning', label: 'Morning (6AM-12PM)', icon: <Sunrise size={20} /> },
  { value: 'afternoon', label: 'Afternoon (12PM-6PM)', icon: <Sun size={20} /> },
  { value: 'evening', label: 'Evening (6PM-10PM)', icon: <Sunset size={20} /> },
  { value: 'night', label: 'Night (10PM-6AM)', icon: <Moon size={20} /> },
]

const Onboarding = () => {
  const navigate = useNavigate()
  const { isAuthenticated, isOnboarded, completeOnboarding, isLoading } = useAuthStore()

  const [formData, setFormData] = useState({
    daily_study_goal_minutes: 60,
    preferred_study_time: 'evening',
  })

  useEffect(() => {
    if (!isAuthenticated) {
      navigate('/login')
    } else if (isOnboarded) {
      navigate('/dashboard')
    }
  }, [isAuthenticated, isOnboarded, navigate])

  const handleSubmit = async () => {
    const result = await completeOnboarding(formData)
    if (result.success) {
      toast.success('Welcome to DailyTaiyari! 🎉')
      navigate('/dashboard')
    } else {
      toast.error(result.error || 'Something went wrong')
    }
  }

  return (
    <div className="min-h-screen bg-surface-50 dark:bg-surface-950 flex items-center justify-center p-4">
      <div className="w-full max-w-2xl">
        <div className="flex items-center justify-center mb-8">
          <div className="w-12 h-12 rounded-full flex items-center justify-center font-semibold bg-primary-500 text-white">
            <Rocket size={22} />
          </div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="card p-8"
        >
          <h2 className="text-2xl font-display font-bold mb-2 text-center">
            Set Your Goals
          </h2>
          <p className="text-surface-500 text-center mb-8">
            Tell us how you like to study. You can browse and join courses from the
            Courses tab once you're in.
          </p>

          <div className="space-y-6">
            {/* Daily Study Goal */}
            <div>
              <label className="block text-sm font-medium mb-3">
                Daily Study Goal (minutes)
              </label>
              <div className="flex items-center gap-4">
                <input
                  type="range"
                  min="30"
                  max="180"
                  step="15"
                  value={formData.daily_study_goal_minutes}
                  onChange={(e) =>
                    setFormData({ ...formData, daily_study_goal_minutes: parseInt(e.target.value) })
                  }
                  className="flex-1"
                />
                <span className="w-20 text-center font-semibold text-primary-600">
                  {formData.daily_study_goal_minutes} min
                </span>
              </div>
            </div>

            {/* Preferred Study Time */}
            <div>
              <label className="block text-sm font-medium mb-3">
                Preferred Study Time
              </label>
              <div className="grid grid-cols-2 gap-3">
                {studyTimes.map((time) => (
                  <button
                    key={time.value}
                    onClick={() =>
                      setFormData({ ...formData, preferred_study_time: time.value })
                    }
                    className={`p-3 rounded-xl border-2 text-left transition-all flex items-center gap-3 ${formData.preferred_study_time === time.value
                      ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                      : 'border-surface-200 dark:border-surface-700 hover:border-primary-300'
                      }`}
                  >
                    <span className={`${formData.preferred_study_time === time.value ? 'text-primary-500' : 'text-surface-400'}`}>
                      {time.icon}
                    </span>
                    <span className="text-sm font-medium">{time.label}</span>
                  </button>
                ))}
              </div>
            </div>

          </div>

          <div className="flex justify-end mt-8">
            <button
              onClick={handleSubmit}
              disabled={isLoading}
              className="btn-primary flex items-center gap-2"
            >
              {isLoading ? 'Setting up...' : <>{'Start Learning'} <ChevronRight size={18} /></>}
            </button>
          </div>
        </motion.div>
      </div>
    </div>
  )
}

export default Onboarding
