import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { useAuthStore } from '../context/authStore'
import { useAppStore } from '../context/appStore'
import { analyticsService } from '../services/analyticsService'
import toast from 'react-hot-toast'
import ImageCropper from '../components/common/ImageCropper'

import {
  Camera,
  User,
  BookOpen,
  MapPin,
  Clock,
  Timer,
  Flame,
  Zap,
  Settings,
  Lock,
  Sunrise,
  Sun,
  Sunset,
  Moon,
  ChevronRight,
  LogOut,
  Eye,
  EyeOff,
  X
} from 'lucide-react'

const Profile = () => {
  const { user, profile, updateProfile, logout } = useAuthStore()
  const changePassword = useAuthStore((s) => s.changePassword)
  const { darkMode, toggleDarkMode } = useAppStore()

  const [isEditing, setIsEditing] = useState(false)
  const [activeSection, setActiveSection] = useState(null)
  const [avatarFile, setAvatarFile] = useState(null)
  const [avatarPreview, setAvatarPreview] = useState(null)
  const [showCropper, setShowCropper] = useState(false)
  const [tempImage, setTempImage] = useState(null)

  const [showPasswordModal, setShowPasswordModal] = useState(false)
  const [passwordForm, setPasswordForm] = useState({
    old_password: '',
    new_password: '',
    confirm_password: '',
  })
  const [showPasswords, setShowPasswords] = useState(false)
  const [changingPassword, setChangingPassword] = useState(false)

  const [formData, setFormData] = useState({

    // Account info (User model)
    first_name: user?.first_name || '',
    last_name: user?.last_name || '',
    phone: user?.phone || '',
    // Personal info
    date_of_birth: profile?.date_of_birth || '',
    bio: profile?.bio || '',
    instagram_handle: profile?.instagram_handle || '',
    parent_phone: profile?.parent_phone || '',
    // Academic info
    school: profile?.school || '',
    coaching: profile?.coaching || '',
    target_year: profile?.target_year || '',
    // Location
    city: profile?.city || '',
    state: profile?.state || '',
    // Study preferences
    daily_study_goal_minutes: profile?.daily_study_goal_minutes || 60,
    preferred_study_time: profile?.preferred_study_time || 'evening',
  })

  // Sync form data when profile updates
  useEffect(() => {
    if (profile) {
      setFormData({
        first_name: user?.first_name || '',
        last_name: user?.last_name || '',
        phone: user?.phone || '',
        date_of_birth: profile.date_of_birth || '',
        bio: profile.bio || '',
        instagram_handle: profile.instagram_handle || '',
        parent_phone: profile.parent_phone || '',
        school: profile.school || '',
        coaching: profile.coaching || '',
        target_year: profile.target_year || '',
        city: profile.city || '',
        state: profile.state || '',
        daily_study_goal_minutes: profile.daily_study_goal_minutes || 60,
        preferred_study_time: profile.preferred_study_time || 'evening',
      })
    }
  }, [profile, user])

  const handleSave = async () => {
    const submitData = new FormData()

    // Add avatar if changed
    if (avatarFile) {
      submitData.append('user.avatar', avatarFile)
    }

    // User (account) fields are nested under `user.` and compared against `user`
    const userFields = ['first_name', 'last_name', 'phone']

    // Add other fields
    Object.keys(formData).forEach(key => {
      if (userFields.includes(key)) {
        if (formData[key] !== (user?.[key] || '')) {
          submitData.append(`user.${key}`, formData[key])
        }
      } else if (formData[key] !== profile?.[key]) {
        submitData.append(key, formData[key])
      }
    })

    const result = await updateProfile(submitData)
    if (result.success) {
      toast.success('Profile updated!')
      setIsEditing(false)
      setActiveSection(null)
      setAvatarFile(null)
      setAvatarPreview(null)
    } else {
      toast.error('Failed to update profile')
    }
  }


  const handleCancel = () => {
    // Reset form data to current profile
    setFormData({
      first_name: user?.first_name || '',
      last_name: user?.last_name || '',
      phone: user?.phone || '',
      date_of_birth: profile?.date_of_birth || '',
      bio: profile?.bio || '',
      instagram_handle: profile?.instagram_handle || '',
      parent_phone: profile?.parent_phone || '',
      school: profile?.school || '',
      coaching: profile?.coaching || '',
      target_year: profile?.target_year || '',
      city: profile?.city || '',
      state: profile?.state || '',
      daily_study_goal_minutes: profile?.daily_study_goal_minutes || 60,
      preferred_study_time: profile?.preferred_study_time || 'evening',
    })
    setIsEditing(false)
    setActiveSection(null)
    setAvatarFile(null)
    setAvatarPreview(null)
  }

  const handleAvatarChange = (e) => {
    const file = e.target.files[0]
    if (file) {
      if (file.size > 5 * 1024 * 1024) {
        toast.error('Image size should be less than 5MB')
        return
      }
      const reader = new FileReader()
      reader.onload = () => {
        setTempImage(reader.result)
        setShowCropper(true)
      }
      reader.readAsDataURL(file)
    }
  }

  const handleCropComplete = (croppedBlob) => {
    const file = new File([croppedBlob], 'avatar.jpg', { type: 'image/jpeg' })
    setAvatarFile(file)
    setAvatarPreview(URL.createObjectURL(croppedBlob))
    setShowCropper(false)
    setTempImage(null)
    setIsEditing(true)
    setActiveSection('personal')
  }



  const closePasswordModal = () => {
    setShowPasswordModal(false)
    setPasswordForm({ old_password: '', new_password: '', confirm_password: '' })
    setShowPasswords(false)
  }

  const handleChangePassword = async (e) => {
    e.preventDefault()
    const { old_password, new_password, confirm_password } = passwordForm

    if (!old_password || !new_password) {
      toast.error('Please fill in all fields')
      return
    }
    if (new_password.length < 8) {
      toast.error('New password must be at least 8 characters')
      return
    }
    if (new_password !== confirm_password) {
      toast.error('New passwords do not match')
      return
    }

    setChangingPassword(true)
    const result = await changePassword(old_password, new_password)
    setChangingPassword(false)

    if (result.success) {
      toast.success('Password changed successfully!')
      closePasswordModal()
    } else {
      toast.error(result.error || 'Failed to change password')
    }
  }

  const startEditing = (section) => {
    setIsEditing(true)
    setActiveSection(section)
  }

  const studyTimes = [
    { value: 'morning', label: 'Morning', icon: <Sunrise size={24} />, desc: '6AM-12PM' },
    { value: 'afternoon', label: 'Afternoon', icon: <Sun size={24} />, desc: '12PM-6PM' },
    { value: 'evening', label: 'Evening', icon: <Sunset size={24} />, desc: '6PM-10PM' },
    { value: 'night', label: 'Night', icon: <Moon size={24} />, desc: '10PM-6AM' },
  ]



  const indianStates = [
    'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh',
    'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jharkhand', 'Karnataka',
    'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya', 'Mizoram',
    'Nagaland', 'Odisha', 'Punjab', 'Rajasthan', 'Sikkim', 'Tamil Nadu',
    'Telangana', 'Tripura', 'Uttar Pradesh', 'Uttarakhand', 'West Bengal',
    'Delhi', 'Chandigarh', 'Puducherry'
  ]

  // Section edit button component
  const EditButton = ({ section }) => (
    <button
      onClick={() => isEditing && activeSection === section ? handleSave() : startEditing(section)}
      className={`text-sm px-3 py-1.5 rounded-lg transition-all ${isEditing && activeSection === section
        ? 'bg-primary-500 text-white'
        : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
        }`}
    >
      {isEditing && activeSection === section ? 'Save' : 'Edit'}
    </button>
  )

  return (
    <div className="max-w-3xl mx-auto space-y-6 pb-8">
      {/* Header Card with Avatar */}
      <div className="card p-6">
        <div className="flex items-start gap-5">
          {/* Avatar */}
          <div className="relative">
            <input
              type="file"
              id="avatar-upload"
              className="hidden"
              accept="image/*"
              onChange={handleAvatarChange}
            />
            <div className="w-24 h-24 rounded-2xl bg-gradient-to-br from-primary-400 via-accent-400 to-primary-600 flex items-center justify-center text-white text-4xl font-bold shadow-lg shadow-primary-500/25 overflow-hidden">
              {avatarPreview ? (
                <img src={avatarPreview} alt="Preview" className="w-full h-full object-cover" />
              ) : user?.avatar ? (
                <img src={user.avatar} alt={user.full_name} className="w-full h-full object-cover" />
              ) : (
                user?.first_name?.charAt(0) || 'U'
              )}
            </div>
            <label
              htmlFor="avatar-upload"
              className="absolute -bottom-2 -right-2 w-8 h-8 bg-surface-100 dark:bg-surface-800 border-2 border-white dark:border-surface-900 rounded-full flex items-center justify-center hover:bg-surface-200 transition-colors cursor-pointer"
            >
              <Camera size={14} className="text-surface-600" />
            </label>
          </div>


          {/* User Info */}
          <div className="flex-1">
            <h1 className="text-2xl font-display font-bold">{user?.full_name || 'Student'}</h1>
            <p className="text-surface-500">{user?.email}</p>
            <div className="flex flex-wrap items-center gap-2 mt-3">
              <span className="badge-primary">Level {profile?.current_level || 1}</span>
              <span className="badge-success">{profile?.total_xp?.toLocaleString() || 0} XP</span>
              {(profile?.enrolled_courses || []).filter((c) => c.name).map((c) => (
                <span key={c.id || c.name} className="px-2 py-1 text-xs rounded-lg bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300">
                  {c.name}
                </span>
              ))}
            </div>
            {formData.bio && (
              <p className="text-sm text-surface-600 dark:text-surface-400 mt-3 italic">"{formData.bio}"</p>
            )}
          </div>
        </div>

        {/* Stats Row */}
        <div className="grid grid-cols-3 gap-4 mt-6 pt-6 border-t border-surface-200 dark:border-surface-700">
          <div className="text-center">
            <p className="text-2xl font-bold">{profile?.total_questions_attempted || 0}</p>
            <p className="text-sm text-surface-500">Questions</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold">{Math.round(profile?.overall_accuracy || 0)}%</p>
            <p className="text-sm text-surface-500">Accuracy</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold">{Math.round((profile?.total_study_time_minutes || 0) / 60)}h</p>
            <p className="text-sm text-surface-500">Study Time</p>
          </div>
        </div>
      </div>

      {/* Personal Information */}
      <div className="card p-6">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2">
            <User size={20} className="text-primary-500" />
            <h2 className="text-lg font-semibold">Personal Information</h2>
          </div>
          <div className="flex gap-2">
            {isEditing && activeSection === 'personal' && (
              <button onClick={handleCancel} className="text-sm px-3 py-1.5 rounded-lg bg-surface-100 dark:bg-surface-800">
                Cancel
              </button>
            )}
            <EditButton section="personal" />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* First Name */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-1">First Name</label>
            {isEditing && activeSection === 'personal' ? (
              <input
                type="text"
                value={formData.first_name}
                onChange={(e) => setFormData({ ...formData, first_name: e.target.value })}
                className="input"
                placeholder="Enter your first name"
              />
            ) : (
              <p className="text-base py-2">{formData.first_name || '—'}</p>
            )}
          </div>

          {/* Last Name */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-1">Last Name</label>
            {isEditing && activeSection === 'personal' ? (
              <input
                type="text"
                value={formData.last_name}
                onChange={(e) => setFormData({ ...formData, last_name: e.target.value })}
                className="input"
                placeholder="Enter your last name"
              />
            ) : (
              <p className="text-base py-2">{formData.last_name || '—'}</p>
            )}
          </div>

          {/* Phone */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-1">Phone Number</label>
            {isEditing && activeSection === 'personal' ? (
              <input
                type="tel"
                value={formData.phone}
                onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                className="input"
                placeholder="Enter your phone number"
              />
            ) : (
              <p className="text-base py-2">{formData.phone || '—'}</p>
            )}
          </div>

          {/* Parent Phone */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-1">Parent's Phone</label>
            {isEditing && activeSection === 'personal' ? (
              <input
                type="tel"
                value={formData.parent_phone}
                onChange={(e) => setFormData({ ...formData, parent_phone: e.target.value })}
                className="input"
                placeholder="Enter parent's phone"
              />
            ) : (
              <p className="text-base py-2">{formData.parent_phone || '—'}</p>
            )}
          </div>

          {/* Date of Birth */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-1">Date of Birth</label>
            {isEditing && activeSection === 'personal' ? (
              <>
                <input
                  type="date"
                  value={formData.date_of_birth}
                  onChange={(e) => setFormData({ ...formData, date_of_birth: e.target.value })}
                  className="input"
                />
                <p className="mt-1.5 text-xs text-surface-500">🎂 Add it and we'll have a surprise waiting for you on the day.</p>
              </>
            ) : (
              <p className="text-base py-2">
                {formData.date_of_birth
                  ? new Date(formData.date_of_birth).toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' })
                  : '—'
                }
              </p>
            )}
          </div>

          {/* Instagram */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-1">Instagram Handle</label>
            {isEditing && activeSection === 'personal' ? (
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-400">@</span>
                <input
                  type="text"
                  value={formData.instagram_handle}
                  onChange={(e) => setFormData({ ...formData, instagram_handle: e.target.value.replace('@', '') })}
                  className="input pl-8"
                  placeholder="username"
                />
              </div>
            ) : (
              <p className="text-base py-2">
                {formData.instagram_handle ? `@${formData.instagram_handle}` : '—'}
              </p>
            )}
          </div>

          {/* Bio */}
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-surface-500 mb-1">Bio</label>
            {isEditing && activeSection === 'personal' ? (
              <textarea
                value={formData.bio}
                onChange={(e) => setFormData({ ...formData, bio: e.target.value })}
                className="input resize-none"
                rows={2}
                maxLength={500}
                placeholder="Tell us about yourself..."
              />
            ) : (
              <p className="text-base py-2 text-surface-600 dark:text-surface-400">
                {formData.bio || '—'}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Academic Information */}
      <div className="card p-6">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2">
            <BookOpen size={20} className="text-primary-500" />
            <h2 className="text-lg font-semibold">Academic Information</h2>
          </div>
          <div className="flex gap-2">
            {isEditing && activeSection === 'academic' && (
              <button onClick={handleCancel} className="text-sm px-3 py-1.5 rounded-lg bg-surface-100 dark:bg-surface-800">
                Cancel
              </button>
            )}
            <EditButton section="academic" />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Target Year */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-1">Target Exam Year</label>
            {isEditing && activeSection === 'academic' ? (
              <input
                type="number"
                value={formData.target_year}
                onChange={(e) => setFormData({ ...formData, target_year: e.target.value })}
                className="input"
                placeholder="e.g. 2027"
                min={new Date().getFullYear()}
                max={new Date().getFullYear() + 5}
              />
            ) : (
              <p className="text-base py-2">{formData.target_year || '—'}</p>
            )}
          </div>

          {/* Courses */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-1">Enrolled Courses</label>
            <p className="text-base py-2 flex flex-wrap gap-2">
              {(profile?.enrolled_courses || []).filter((c) => c.name).length ? (
                profile.enrolled_courses.filter((c) => c.name).map((c) => (
                  <span key={c.id || c.name} className="px-2 py-1 text-xs rounded-lg bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300">
                    {c.name}
                  </span>
                ))
              ) : (
                <span className="text-surface-400">—</span>
              )}
            </p>
          </div>

          {/* School */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-1">School Name</label>
            {isEditing && activeSection === 'academic' ? (
              <input
                type="text"
                value={formData.school}
                onChange={(e) => setFormData({ ...formData, school: e.target.value })}
                className="input"
                placeholder="Enter your school name"
              />
            ) : (
              <p className="text-base py-2">{formData.school || '—'}</p>
            )}
          </div>

          {/* Coaching */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-1">Coaching Institute</label>
            {isEditing && activeSection === 'academic' ? (
              <input
                type="text"
                value={formData.coaching}
                onChange={(e) => setFormData({ ...formData, coaching: e.target.value })}
                className="input"
                placeholder="e.g. Allen, FIITJEE, Aakash..."
              />
            ) : (
              <p className="text-base py-2">{formData.coaching || '—'}</p>
            )}
          </div>
        </div>
      </div>

      {/* Location */}
      <div className="card p-6">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2">
            <MapPin size={20} className="text-primary-500" />
            <h2 className="text-lg font-semibold">Location</h2>
          </div>
          <div className="flex gap-2">
            {isEditing && activeSection === 'location' && (
              <button onClick={handleCancel} className="text-sm px-3 py-1.5 rounded-lg bg-surface-100 dark:bg-surface-800">
                Cancel
              </button>
            )}
            <EditButton section="location" />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* City */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-1">City</label>
            {isEditing && activeSection === 'location' ? (
              <input
                type="text"
                value={formData.city}
                onChange={(e) => setFormData({ ...formData, city: e.target.value })}
                className="input"
                placeholder="Enter your city"
              />
            ) : (
              <p className="text-base py-2">{formData.city || '—'}</p>
            )}
          </div>

          {/* State */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-1">State</label>
            {isEditing && activeSection === 'location' ? (
              <select
                value={formData.state}
                onChange={(e) => setFormData({ ...formData, state: e.target.value })}
                className="input"
              >
                <option value="">Select state</option>
                {indianStates.map(state => (
                  <option key={state} value={state}>{state}</option>
                ))}
              </select>
            ) : (
              <p className="text-base py-2">{formData.state || '—'}</p>
            )}
          </div>
        </div>
      </div>

      {/* Study Preferences */}
      <div className="card p-6">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2">
            <Clock size={20} className="text-primary-500" />
            <h2 className="text-lg font-semibold">Study Preferences</h2>
          </div>
          <div className="flex gap-2">
            {isEditing && activeSection === 'study' && (
              <button onClick={handleCancel} className="text-sm px-3 py-1.5 rounded-lg bg-surface-100 dark:bg-surface-800">
                Cancel
              </button>
            )}
            <EditButton section="study" />
          </div>
        </div>

        <div className="space-y-6">
          {/* Daily Study Goal */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-3">Daily Study Goal</label>
            <div className="p-4 rounded-xl bg-surface-50 dark:bg-surface-800">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <Timer size={32} className="text-primary-500" />
                  <div>
                    <p className="text-2xl font-bold">{formData.daily_study_goal_minutes} min</p>
                    <p className="text-sm text-surface-500">
                      {Math.floor(formData.daily_study_goal_minutes / 60)}h {formData.daily_study_goal_minutes % 60}m per day
                    </p>
                  </div>
                </div>
                <span className={`badge flex items-center gap-1 ${formData.daily_study_goal_minutes >= 120 ? 'badge-success' :
                  formData.daily_study_goal_minutes >= 60 ? 'badge-primary' : 'badge-warning'
                  }`}>
                  {formData.daily_study_goal_minutes >= 120 ? <><Flame size={12} /> Intense</> :
                    formData.daily_study_goal_minutes >= 60 ? <><Zap size={12} /> Committed</> : <><BookOpen size={12} /> Beginner</>}
                </span>
              </div>

              {isEditing && activeSection === 'study' ? (
                <div className="space-y-3">
                  <input
                    type="range"
                    min="15"
                    max="240"
                    step="15"
                    value={formData.daily_study_goal_minutes}
                    onChange={(e) => setFormData({ ...formData, daily_study_goal_minutes: parseInt(e.target.value) })}
                    className="w-full accent-primary-500 h-3 rounded-lg cursor-pointer"
                  />
                  <div className="flex justify-between text-xs text-surface-500">
                    <span>15 min</span>
                    <span>1 hour</span>
                    <span>2 hours</span>
                    <span>3 hours</span>
                    <span>4 hours</span>
                  </div>
                  <div className="grid grid-cols-4 gap-2 mt-3">
                    {[30, 60, 90, 120].map((mins) => (
                      <button
                        key={mins}
                        onClick={() => setFormData({ ...formData, daily_study_goal_minutes: mins })}
                        className={`py-2 px-3 rounded-lg text-sm font-medium transition-all ${formData.daily_study_goal_minutes === mins
                          ? 'bg-primary-500 text-white'
                          : 'bg-surface-200 dark:bg-surface-700 hover:bg-primary-100 dark:hover:bg-primary-900/30'
                          }`}
                      >
                        {mins} min
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="h-3 bg-surface-200 dark:bg-surface-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-primary-500 to-accent-500 rounded-full"
                    style={{ width: `${(formData.daily_study_goal_minutes / 240) * 100}%` }}
                  />
                </div>
              )}
            </div>
          </div>

          {/* Preferred Study Time */}
          <div>
            <label className="block text-sm font-medium text-surface-500 mb-3">Preferred Study Time</label>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {studyTimes.map((time) => (
                <button
                  key={time.value}
                  onClick={() => isEditing && activeSection === 'study' && setFormData({ ...formData, preferred_study_time: time.value })}
                  disabled={!isEditing || activeSection !== 'study'}
                  className={`p-3 rounded-xl border-2 transition-all text-center ${formData.preferred_study_time === time.value
                    ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                    : 'border-surface-200 dark:border-surface-700'
                    } ${isEditing && activeSection === 'study' ? 'cursor-pointer hover:border-primary-300' : 'cursor-default'}`}
                >
                  <div className="flex justify-center mb-1 text-primary-500">
                    {time.icon}
                  </div>
                  <span className="font-medium block">{time.label}</span>
                  <span className="text-xs text-surface-500">{time.desc}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* App Settings */}
      <div className="card p-6">
        <div className="flex items-center gap-2 mb-5">
          <Settings size={20} className="text-primary-500" />
          <h2 className="text-lg font-semibold">App Settings</h2>
        </div>

        <div className="space-y-4">
          <div className="flex items-center justify-between p-3 rounded-xl bg-surface-50 dark:bg-surface-800">
            <div>
              <p className="font-medium">Dark Mode</p>
              <p className="text-sm text-surface-500">Toggle dark theme</p>
            </div>
            <button
              onClick={toggleDarkMode}
              className={`w-14 h-8 rounded-full transition-colors ${darkMode ? 'bg-primary-500' : 'bg-surface-300'
                }`}
            >
              <motion.div
                className="w-6 h-6 bg-white rounded-full shadow"
                animate={{ x: darkMode ? 28 : 4 }}
              />
            </button>
          </div>

          <div className="flex items-center justify-between p-3 rounded-xl bg-surface-50 dark:bg-surface-800">
            <div>
              <p className="font-medium">Notifications</p>
              <p className="text-sm text-surface-500">Study reminders & updates</p>
            </div>
            <button className="w-14 h-8 rounded-full bg-primary-500">
              <motion.div className="w-6 h-6 bg-white rounded-full shadow ml-7" />
            </button>
          </div>
        </div>
      </div>

      {/* Account Actions */}
      <div className="card p-6">
        <div className="flex items-center gap-2 mb-5">
          <Lock size={20} className="text-primary-500" />
          <h2 className="text-lg font-semibold">Account</h2>
        </div>

        <div className="space-y-3">
          <button
            onClick={() => setShowPasswordModal(true)}
            className="w-full text-left p-4 rounded-xl border border-surface-200 dark:border-surface-700 hover:bg-surface-50 dark:hover:bg-surface-800 transition-colors flex items-center justify-between group"
          >
            <div>
              <p className="font-medium">Change Password</p>
              <p className="text-sm text-surface-500">Update your password</p>
            </div>
            <ChevronRight size={20} className="text-surface-400 group-hover:text-surface-600 transition-colors" />
          </button>

          <button className="w-full text-left p-4 rounded-xl border border-surface-200 dark:border-surface-700 hover:bg-surface-50 dark:hover:bg-surface-800 transition-colors">
            <p className="font-medium">Manage Subscription</p>
            <p className="text-sm text-surface-500">View plan details</p>
          </button>

          <button
            onClick={() => {
              logout()
              window.location.href = '/login'
            }}
            className="w-full text-left p-4 rounded-xl border border-error-200 dark:border-error-800 hover:bg-error-50 dark:hover:bg-error-900/20 text-error-600 transition-colors flex items-center justify-between group"
          >
            <div>
              <p className="font-medium">Sign Out</p>
              <p className="text-sm text-error-400">Log out of your account</p>
            </div>
            <LogOut size={20} className="text-error-400 group-hover:text-error-600 transition-colors" />
          </button>
        </div>
      </div>

      {showCropper && (
        <ImageCropper
          image={tempImage}
          onCropComplete={handleCropComplete}
          onCancel={() => {
            setShowCropper(false)
            setTempImage(null)
          }}
        />
      )}

      {showPasswordModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={closePasswordModal}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="w-full max-w-md rounded-2xl bg-white dark:bg-surface-900 p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-2">
                <Lock size={20} className="text-primary-500" />
                <h2 className="text-lg font-semibold">Change Password</h2>
              </div>
              <button
                onClick={closePasswordModal}
                className="p-1 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800 transition-colors"
              >
                <X size={20} className="text-surface-500" />
              </button>
            </div>

            <form onSubmit={handleChangePassword} className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1.5">Current Password</label>
                <input
                  type={showPasswords ? 'text' : 'password'}
                  value={passwordForm.old_password}
                  onChange={(e) => setPasswordForm({ ...passwordForm, old_password: e.target.value })}
                  className="w-full px-3 py-2.5 rounded-lg border border-surface-200 dark:border-surface-700 bg-surface-50 dark:bg-surface-800 focus:outline-none focus:ring-2 focus:ring-primary-500"
                  autoComplete="current-password"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1.5">New Password</label>
                <input
                  type={showPasswords ? 'text' : 'password'}
                  value={passwordForm.new_password}
                  onChange={(e) => setPasswordForm({ ...passwordForm, new_password: e.target.value })}
                  className="w-full px-3 py-2.5 rounded-lg border border-surface-200 dark:border-surface-700 bg-surface-50 dark:bg-surface-800 focus:outline-none focus:ring-2 focus:ring-primary-500"
                  autoComplete="new-password"
                />
                <p className="text-xs text-surface-400 mt-1">At least 8 characters</p>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1.5">Confirm New Password</label>
                <input
                  type={showPasswords ? 'text' : 'password'}
                  value={passwordForm.confirm_password}
                  onChange={(e) => setPasswordForm({ ...passwordForm, confirm_password: e.target.value })}
                  className="w-full px-3 py-2.5 rounded-lg border border-surface-200 dark:border-surface-700 bg-surface-50 dark:bg-surface-800 focus:outline-none focus:ring-2 focus:ring-primary-500"
                  autoComplete="new-password"
                />
              </div>

              <button
                type="button"
                onClick={() => setShowPasswords(!showPasswords)}
                className="flex items-center gap-1.5 text-sm text-surface-500 hover:text-surface-700 dark:hover:text-surface-300 transition-colors"
              >
                {showPasswords ? <EyeOff size={16} /> : <Eye size={16} />}
                {showPasswords ? 'Hide passwords' : 'Show passwords'}
              </button>

              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={closePasswordModal}
                  className="flex-1 px-4 py-2.5 rounded-lg bg-surface-100 dark:bg-surface-800 font-medium hover:bg-surface-200 dark:hover:bg-surface-700 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={changingPassword}
                  className="flex-1 px-4 py-2.5 rounded-lg bg-primary-500 text-white font-medium hover:bg-primary-600 transition-colors disabled:opacity-60"
                >
                  {changingPassword ? 'Updating...' : 'Update Password'}
                </button>
              </div>
            </form>
          </motion.div>
        </div>
      )}
    </div>

  )
}

export default Profile
