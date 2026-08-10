"""
Django settings for DailyTaiyari project.
Production-grade course preparation platform.
"""

import os
from pathlib import Path
from datetime import timedelta
from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='django-insecure-dev-key-change-in-production')

# Optional dedicated key (urlsafe base64 Fernet key) for encrypting sensitive
# fields at rest, e.g. tenant payment-gateway secrets. When unset, a key is
# derived from SECRET_KEY (see core.encryption). Set this in production so
# rotating SECRET_KEY does not invalidate previously-stored ciphertext.
FIELD_ENCRYPTION_KEY = config('FIELD_ENCRYPTION_KEY', default='')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=lambda v: [s.strip() for s in v.split(',')])

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Production Security Headers
if not DEBUG:
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party apps
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'django_filters',
    'drf_yasg',
    'storages',
    
    # Local apps
    'core.apps.CoreConfig',
    'users.apps.UsersConfig',
    'exams.apps.ExamsConfig',
    'content.apps.ContentConfig',
    'quiz.apps.QuizConfig',
    'analytics.apps.AnalyticsConfig',
    'gamification.apps.GamificationConfig',
    'chatbot.apps.ChatbotConfig',
    'coursegen.apps.CourseGenConfig',
    'community.apps.CommunityConfig',
    'assignments.apps.AssignmentsConfig',
    'coding.apps.CodingConfig',
    'liveclass.apps.LiveClassConfig',
    'jobs.apps.JobsConfig',
    'certificates.apps.CertificatesConfig',
    'payments.apps.PaymentsConfig',
    'marketing.apps.MarketingConfig',
    'notifications.apps.NotificationsConfig',
    'notebooks.apps.NotebooksConfig',
]

SILENCED_SYSTEM_CHECKS = ["auth.E003"]


MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.TenantMiddleware',
    'core.middleware.BlockSuspendedUsersMiddleware',
]

ROOT_URLCONF = 'dailytaiyari.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'dailytaiyari.wsgi.application'

# Database
if config('DB_HOST', default=''):
    # Azure Database for PostgreSQL (Flexible Server) requires SSL.
    # Set DB_SSLMODE=require (or verify-full) via env for Azure.
    _db_options = {}
    _db_sslmode = config('DB_SSLMODE', default='')
    if _db_sslmode:
        _db_options['sslmode'] = _db_sslmode

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME'),
            'USER': config('DB_USER'),
            'PASSWORD': config('DB_PASSWORD'),
            'HOST': config('DB_HOST'),
            'PORT': config('DB_PORT', default='5432'),
            'OPTIONS': _db_options,
            'CONN_MAX_AGE': config('DB_CONN_MAX_AGE', default=60, cast=int),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# Custom User Model
AUTH_USER_MODEL = 'users.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'


# Storage Configuration
# STORAGE_BACKEND selects where user-uploaded media is stored:
#   - "azure" : Azure Blob Storage (production on Azure)
#   - "s3"    : AWS S3 (legacy/production on AWS)
#   - "local" : local filesystem (development)
# Backward compatible: USE_S3=True still forces the S3 backend.
STORAGE_BACKEND = config('STORAGE_BACKEND', default='').lower()
USE_S3 = config('USE_S3', default=False, cast=bool)

if not STORAGE_BACKEND:
    STORAGE_BACKEND = 's3' if USE_S3 else 'local'

if STORAGE_BACKEND == 'azure':
    # Azure Blob Storage settings
    AZURE_ACCOUNT_NAME = config('AZURE_ACCOUNT_NAME')
    AZURE_ACCOUNT_KEY = config('AZURE_ACCOUNT_KEY', default=None) or None
    AZURE_CONTAINER = config('AZURE_CONTAINER', default='media')
    # Custom domain / endpoint (defaults to the standard blob endpoint)
    AZURE_CUSTOM_DOMAIN = config(
        'AZURE_CUSTOM_DOMAIN',
        default=f'{AZURE_ACCOUNT_NAME}.blob.core.windows.net',
    )
    # Serve permanent (non-expiring) URLs for public containers.
    AZURE_URL_EXPIRATION_SECS = config(
        'AZURE_URL_EXPIRATION_SECS', default=None,
        cast=lambda v: int(v) if v else None,
    )
    AZURE_OVERWRITE_FILES = False

    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.azure_storage.AzureStorage",
            "OPTIONS": {
                "account_name": AZURE_ACCOUNT_NAME,
                "account_key": AZURE_ACCOUNT_KEY,
                "azure_container": AZURE_CONTAINER,
                "expiration_secs": AZURE_URL_EXPIRATION_SECS,
                "overwrite_files": False,
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

    MEDIA_URL = f'https://{AZURE_CUSTOM_DOMAIN}/{AZURE_CONTAINER}/'

elif STORAGE_BACKEND == 's3':
    USE_S3 = True
    # AWS Settings - Keys can be None to use EC2 IAM Roles
    AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID', default=None) or None
    AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY', default=None) or None
    AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME', default='ap-south-1')

    AWS_QUERYSTRING_AUTH = False  # Permanent URLs
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    
    # S3 Custom Domain
    AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com'
    
    # Media Location
    AWS_LOCATION = 'media'
    
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "location": AWS_LOCATION,
                "default_acl": None,
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    
    MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/{AWS_LOCATION}/'
else:
    MEDIA_URL = 'media/'
    MEDIA_ROOT = BASE_DIR / 'media'



# Ensure MEDIA_ROOT is defined (used for local dev/testing or fallback)
if 'MEDIA_ROOT' not in locals():
    MEDIA_ROOT = BASE_DIR / 'media'



# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        'quiz_submit': '60/hour',  # Rate limit quiz submissions
        'code_run': '120/hour',  # Rate limit "run sample" code executions
        'code_submit': '120/hour',  # Rate limit graded code submissions
        'notebook_submit': '60/hour',  # Rate limit graded notebook submissions
        'platform_lead': '20/hour',  # Public demo/contact form submissions
    }
}

# JWT Configuration
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=365),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=730),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
}

# CORS Configuration
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000,http://127.0.0.1:3000',
    cast=lambda v: [s.strip() for s in v.split(',')]
)
CORS_ALLOW_CREDENTIALS = True
# Per-tenant frontends hosted outside the dailytaiyari domains (e.g. Netlify
# deploys) that must be allowed to call the public platform endpoints.
CORS_ALLOWED_ORIGINS += [
    'https://testlaevacademy.netlify.app',
    # JoinLoop tenant frontend (client-owned domain + Netlify default URL).
    'https://classroom.joinloop.co.in',
    'https://dailytaiyari-joinloop.netlify.app',
]
# Allow the marketing site + demo portal (any *.dailytaiyari.in / *.dailytaiyari.ai
# subdomain, plus the apex) to call the public platform endpoints cross-origin.
CORS_ALLOWED_ORIGIN_REGEXES = [
    r'^https://([a-z0-9-]+\.)?dailytaiyari\.in$',
    r'^https://([a-z0-9-]+\.)?dailytaiyari\.ai$',
]
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-tenant-id',
]

# OpenAI Configuration (for AI Chatbot)
OPENAI_API_KEY = config('OPENAI_API_KEY', default='')

# ---------------------------------------------------------------------------
# Email / OTP verification
# ---------------------------------------------------------------------------
# Production uses Azure Communication Services (ACS) Email. In DEBUG we fall
# back to the console backend so verification codes are printed to the logs
# instead of dispatched to a real mailbox.
#
# EMAIL_PROVIDER options:
#   'azure'   -> ACS Email (requires django-azure-communication-email)
#   'smtp'    -> any SMTP host (Hostinger mailbox, SendGrid SMTP, etc.)
#   'console' -> print emails to stdout (local dev default)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='DoNotReply@dailytaiyari.in')
# Where inbound marketing-site leads (demo bookings, contact messages) are sent.
PLATFORM_NOTIFICATION_EMAIL = config('PLATFORM_NOTIFICATION_EMAIL', default='balbir.ms24@gmail.com')
EMAIL_PROVIDER = config('EMAIL_PROVIDER', default='console' if DEBUG else 'azure').lower()

if EMAIL_PROVIDER == 'azure':
    # pip install django-azure-communication-email
    EMAIL_BACKEND = 'django_azure_communication_email.EmailBackend'
    AZURE_COMMUNICATION_CONNECTION_STRING = config(
        'AZURE_COMMUNICATION_CONNECTION_STRING', default=''
    )
elif EMAIL_PROVIDER == 'smtp':
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = config('EMAIL_HOST', default='')
    EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
    EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
    EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'


# ---------------------------------------------------------------------------
# Notifications & branded email
# ---------------------------------------------------------------------------
# When True, in-app notification emails and announcement fan-out are enqueued to
# Celery instead of running in the web request. Flip on only once redis + a
# celery worker are running (same infra as CODE_JUDGE_ASYNC). The service layer
# falls back to inline delivery if the broker is unreachable.
NOTIFICATIONS_ASYNC = config('NOTIFICATIONS_ASYNC', default=False, cast=bool)

# Absolute base URL of THIS backend, used to make relative media URLs (e.g. a
# tenant logo stored on local disk) absolute inside emails. In production media
# is served from Azure/S3 so URLs are already absolute and this is unused.
BACKEND_PUBLIC_URL = config('BACKEND_PUBLIC_URL', default='')

# Global fallback frontend origin for email deep links when a tenant has no
# ``allowed_origins`` configured. Tenant-specific origins take precedence.
FRONTEND_URL = config('FRONTEND_URL', default='')


# Code-execution engine (Piston) for coding problems.
PISTON_URL = config('PISTON_URL', default='http://piston:2000')
CODING_ENABLED = config('CODING_ENABLED', default=True, cast=bool)
# How many test cases to execute in parallel per submission. Each case is an
# independent HTTP call to Piston. Concurrency only helps when Piston has at
# least this many DEDICATED CPU cores: Piston's run_timeout is measured in
# WALL-CLOCK time, so if concurrent runs contend for a shared/single core their
# wall time balloons past the limit and every run wrongly fails as TIME_LIMIT.
# Default is 1 (sequential, correct on any host). Raise it only when Piston runs
# on a multi-core host with cores >= this value (e.g. a dedicated judge box).
CODE_JUDGE_PARALLELISM = config('CODE_JUDGE_PARALLELISM', default=1, cast=int)

# --- Async code judging (Phase A) --------------------------------------------
# When True, graded submissions are enqueued to Celery and graded off the web
# request thread; the client receives a "queued" submission and polls for the
# result. When False (default), grading runs synchronously in-request exactly as
# before. Flip to True only once the redis + celery-worker services are running.
CODE_JUDGE_ASYNC = config('CODE_JUDGE_ASYNC', default=False, cast=bool)

# --- Python notebooks ---------------------------------------------------------
# Notebooks execute client-side in Pyodide (CPython -> WebAssembly), so the
# interactive path costs no server compute. NOTEBOOKS_SERVER_GRADING controls
# the authoritative re-grade: when True a submitted notebook is re-executed in
# the sandboxed `nbrunner` container and that score is the real grade. When
# False the browser's provisional score is recorded instead (useful for local
# dev, or a deployment that hasn't started the runner yet).
NOTEBOOKS_ENABLED = config('NOTEBOOKS_ENABLED', default=True, cast=bool)
NOTEBOOKS_SERVER_GRADING = config('NOTEBOOKS_SERVER_GRADING', default=False, cast=bool)
NBRUNNER_URL = config('NBRUNNER_URL', default='http://nbrunner:2100')
# Grade notebooks off the web request thread (recommended: a submission can
# train a model). Falls back to inline grading if the broker is unreachable.
NOTEBOOKS_JUDGE_ASYNC = config('NOTEBOOKS_JUDGE_ASYNC', default=True, cast=bool)

# Celery (broker + result backend on Redis). Result backend stores the task
# state so the poll endpoint can distinguish queued/running/done.
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://redis:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://redis:6379/1')
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 180
CELERY_TASK_SOFT_TIME_LIMIT = 150
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Caching. Prefer a shared Redis cache when REDIS_URL is configured (needed once
# there are multiple web workers/hosts); otherwise fall back to per-process
# LocMem so the app still runs without Redis.
_REDIS_URL = config('REDIS_URL', default='')
if _REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': f'{_REDIS_URL}/2',
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            },
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'unique-snowflake',
        }
    }

# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

