# Frontend Guide

## Tenant Integration Architecture

The frontend identifies itself to a specific tenant via the `VITE_TENANT_ID` environment variable. This value is injected into all API requests as the `X-Tenant-ID` header.

```
.env → VITE_TENANT_ID → Axios interceptor → X-Tenant-ID header → Backend
```

---

## Key Files

| File | Purpose |
|---|---|
| `.env` | Stores `VITE_TENANT_ID` and `VITE_API_URL` |
| `src/services/api.js` | Axios instance with tenant header injection |
| `src/context/tenantStore.js` | Zustand store for tenant branding config |
| `src/App.jsx` | Loads tenant config on mount |
| `src/components/layout/AuthLayout.jsx` | Desktop tenant branding (login/register) |
| `src/pages/auth/Login.jsx` | Mobile tenant branding + login form |
| `src/pages/auth/Register.jsx` | Mobile tenant branding + register form |
| `src/pages/NotebookPage.jsx` | Student lab surface (see [Labs](./notebooks-labs.md)) |
| `src/hooks/usePyodideKernel.js` | In-browser Python kernel state machine |
| `src/workers/pyodideKernel.worker.js` | Pyodide Web Worker |

---

## `.env` Configuration

```bash
# API base URL
VITE_API_URL=http://localhost:8000/api/v1

# Tenant ID (UUID from Django admin)
VITE_TENANT_ID=405223b1-7738-4b01-b405-9cbfecdd63a1
```

> **Note:** Vite bakes environment variables into the bundle at build time. You must rebuild after changing `.env`.

---

## API Service — `src/services/api.js`

Two Axios instances are exported:

### `api` (default export)
The main API client. Includes:
- `X-Tenant-ID` header (from `VITE_TENANT_ID`)
- `Authorization: Bearer <token>` header (from auth store)
- Automatic token refresh on 401

```javascript
import api from '../services/api'

// This automatically includes X-Tenant-ID and auth token
const response = await api.get('/quiz/')
```

### `tenantApi` (named export)
Unauthenticated API client for tenant-config requests. No auth token, no tenant header.

```javascript
import { tenantApi } from '../services/api'

// Fetch tenant branding without authentication
const response = await tenantApi.get(`/tenant/${tenantId}/`)
```

---

## Tenant Store — `src/context/tenantStore.js`

A Zustand store that manages tenant branding state.

### State Shape

```javascript
{
  tenant: {
    id: "405223b1-...",
    name: "Test Academy",
    subdomain: "test",
    logo: "http://localhost:8000/media/tenant_logos/logo.png"  // or null
  },
  isLoading: true,   // true while fetching
  error: null         // error message if fetch failed
}
```

### Usage in Components

```javascript
import { useTenantStore } from '../context/tenantStore'

const MyComponent = () => {
  const { tenant } = useTenantStore()

  return (
    <div>
      <h1>{tenant?.name || 'DailyTaiyari'}</h1>
      {tenant?.logo && <img src={tenant.logo} alt="Logo" />}
    </div>
  )
}
```

### Initialization

The store is initialized in `App.jsx` on mount:

```javascript
function App() {
  const { fetchTenantConfig, isLoading } = useTenantStore()

  useEffect(() => {
    fetchTenantConfig()
  }, [])

  if (isLoading) {
    return <LoadingSpinner />
  }

  return <Routes>...</Routes>
}
```

---

## Branding Components

### Desktop (AuthLayout.jsx)

The left panel on the login/register page shows:
- Tenant logo (or initials fallback)
- Tenant name
- Tagline and stats

### Mobile (Login.jsx, Register.jsx)

The mobile header shows:
- Tenant logo (or gradient initials fallback)
- Tenant name

### Fallback Behavior

If no tenant is configured or the API call fails:
- Name defaults to `"DailyTaiyari"`
- Logo shows initials `"dt"` in a gradient circle
- The app still functions normally

---

## Adding Tenant Branding to a New Component

1. Import the tenant store:
```javascript
import { useTenantStore } from '../context/tenantStore'
```

2. Access the tenant:
```javascript
const { tenant } = useTenantStore()
```

3. Use it in JSX:
```javascript
<h1>{tenant?.name || 'Default Name'}</h1>
{tenant?.logo && (
  <img src={tenant.logo} alt={`${tenant.name} Logo`} />
)}
```

---

## Important Notes

- **Environment variable changes require restart**: Vite caches `.env` values. Restart `npm run dev` after changes.
- **Build-time injection**: `VITE_TENANT_ID` is baked into the bundle. Each tenant deployment needs its own build.
- **The tenant store is loaded before routing**: The app shows a loading spinner until the tenant config is fetched. This prevents a flash of default branding.
