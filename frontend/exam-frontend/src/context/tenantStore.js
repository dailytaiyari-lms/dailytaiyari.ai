import { create } from 'zustand';
import { tenantApi } from '../services/api';
import { applyTheme, DEFAULT_THEME } from '../config/themes';

// Keep in sync with backend core/models.py Tenant.FEATURE_CHOICES.
// Features default to enabled so nothing is hidden before config loads or when
// a key is missing from the tenant response.
export const FEATURE_KEYS = [
    'courses',
    'study',
    'quiz',
    'mock_tests',
    'pyq',
    'community',
    'analytics',
    'leaderboard',
    'ai',
    'jobs',
];

// Platform default display names. A tenant admin may override any of these from
// Settings → Features; the override lands in `tenant.feature_labels` and is what
// students see. Keep in sync with backend Tenant.FEATURE_CHOICES.
export const DEFAULT_FEATURE_LABELS = {
    courses: 'Courses',
    study: 'Study Material',
    quiz: 'Practice Quiz',
    mock_tests: 'Mock Tests',
    pyq: 'Previous Year Papers (PYQ)',
    community: 'Community',
    analytics: 'Analytics',
    leaderboard: 'Leaderboard',
    ai: 'AI Learning & Doubt Solver',
    jobs: 'Job Portal',
};

// Swap the document <link rel="icon"> to the tenant's favicon at runtime so the
// browser tab reflects the institution's branding.
const applyFavicon = (url) => {
    if (typeof document === 'undefined' || !url) return;
    let link = document.querySelector("link[rel~='icon']");
    if (!link) {
        link = document.createElement('link');
        link.rel = 'icon';
        document.head.appendChild(link);
    }
    link.href = url;
};

export const useTenantStore = create((set, get) => ({
    tenant: null,
    isLoading: true,
    error: null,

    fetchTenantConfig: async () => {
        const tenantId = import.meta.env.VITE_TENANT_ID;
        if (!tenantId) {
            set({ error: 'Tenant ID not configured', isLoading: false });
            return;
        }

        try {
            // Only show the full-screen loader on the very first load. Later
            // refreshes (e.g. after an admin saves a setting) run silently so the
            // app's route tree isn't unmounted/remounted — which would otherwise
            // flash a spinner and reset the scroll position to the top.
            if (!get().tenant) {
                set({ isLoading: true, error: null });
            } else {
                set({ error: null });
            }
            const response = await tenantApi.get(`/tenant/${tenantId}/`);
            set({ tenant: response.data, isLoading: false });

            // Apply branding to the document: title (name + tagline), favicon
            // and the tenant's selected colour theme.
            const { name, tagline, favicon, theme } = response.data;
            if (name) {
                document.title = tagline ? `${name} - ${tagline}` : name;
            }
            if (favicon) {
                applyFavicon(favicon);
            }
            applyTheme(theme || DEFAULT_THEME);
        } catch (error) {
            console.error('Failed to fetch tenant configuration', error);
            set({ error: 'Failed to load tenant configuration', isLoading: false });
        }
    },

    // A feature is enabled unless the tenant config explicitly disables it.
    isFeatureEnabled: (key) => {
        const features = get().tenant?.features;
        if (!features || !(key in features)) return true;
        return Boolean(features[key]);
    },

    // Display name for a feature: the tenant's custom rename when set,
    // otherwise `fallback` (a screen-specific default such as a short nav
    // label) or the platform default name.
    featureLabel: (key, fallback) => {
        const custom = get().tenant?.feature_labels?.[key];
        if (typeof custom === 'string' && custom.trim()) return custom.trim();
        return fallback || DEFAULT_FEATURE_LABELS[key] || key;
    },
}));

// Convenience hook for screens that need one feature's display name.
// `fallback` lets a screen keep its own shorter wording (e.g. "Study" instead
// of "Study Material") when the tenant hasn't renamed the feature.
export const useFeatureLabel = (key, fallback) =>
    useTenantStore((s) => s.featureLabel(key, fallback));
