import { create } from 'zustand'
import { persist } from 'zustand/middleware'

const applyDarkMode = (enabled) => {
  document.documentElement.classList.toggle('dark', enabled)
}

export const useAppStore = create(
  persist(
    (set) => ({
      // Theme
      darkMode: false,
      toggleDarkMode: () => set((state) => {
        const darkMode = !state.darkMode
        applyDarkMode(darkMode)
        return { darkMode }
      }),

      // Sidebar
      sidebarOpen: true,
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
      setSidebarOpen: (open) => set({ sidebarOpen: open }),

      // Mobile menu
      mobileMenuOpen: false,
      toggleMobileMenu: () => set((state) => ({ mobileMenuOpen: !state.mobileMenuOpen })),
      closeMobileMenu: () => set({ mobileMenuOpen: false }),

      // Selected exam
      selectedExam: null,
      setSelectedExam: (exam) => set({ selectedExam: exam }),

      // Notifications
      notifications: [],
      addNotification: (notification) =>
        set((state) => ({
          notifications: [
            { id: Date.now(), ...notification },
            ...state.notifications,
          ].slice(0, 50),
        })),
      removeNotification: (id) =>
        set((state) => ({
          notifications: state.notifications.filter((n) => n.id !== id),
        })),
      clearNotifications: () => set({ notifications: [] }),

      // Quiz state
      activeQuiz: null,
      setActiveQuiz: (quiz) => set({ activeQuiz: quiz }),
      clearActiveQuiz: () => set({ activeQuiz: null }),

      // Loading states
      globalLoading: false,
      setGlobalLoading: (loading) => set({ globalLoading: loading }),
    }),
    {
      name: 'app-preferences',
      partialize: (state) => ({ darkMode: state.darkMode }),
      onRehydrateStorage: () => (state) => {
        applyDarkMode(state?.darkMode ?? false)
      },
    }
  )
)
