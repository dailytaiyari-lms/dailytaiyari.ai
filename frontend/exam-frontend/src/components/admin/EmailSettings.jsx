import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
    Mail, Save, RotateCcw, Eye, Loader2, Info, AtSign, Send,
    Globe2, Trash2, ShieldCheck, AlertCircle, Copy, RefreshCw,
    CheckCircle2, Clock3, BellRing, FileText, ChevronRight,
} from 'lucide-react'

import { notificationService } from '../../services/notificationService'
import { tenantAdminService } from '../../services/tenantAdminService'

// Live client-side preview values (mirrors the backend sample context).
const SAMPLE = {
    student_name: 'Jane Doe',
    student_email: 'jane.doe@example.com',
    course_name: 'Sample Course 101',
    reason: 'Reason: Incomplete profile',
    tenant_name: 'Your Institute',
}

const fillPlaceholders = (text, values) =>
    (text || '').replace(/\{(\w+)\}/g, (m, key) => (key in values ? values[key] : ''))

const escapeHtml = (s) =>
    (s || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')

// Mirror backend text_to_html: blank-line paragraphs, single newline → <br>.
const textToHtml = (text) =>
    (text || '')
        .replace(/\r\n/g, '\n')
        .split('\n\n')
        .map((block) => block.split('\n').filter((l) => l.trim()))
        .filter((lines) => lines.length)
        .map((lines) => `<p>${lines.map(escapeHtml).join('<br>')}</p>`)
        .join('')

const TemplateEditor = ({ template, onSaved }) => {
    const queryClient = useQueryClient()
    const [subject, setSubject] = useState(template.subject || '')
    const [heading, setHeading] = useState(template.heading || '')
    const [body, setBody] = useState(template.body || '')
    const [showPreview, setShowPreview] = useState(false)

    useEffect(() => {
        setSubject(template.subject || '')
        setHeading(template.heading || '')
        setBody(template.body || '')
    }, [template])

    const saveMutation = useMutation({
        mutationFn: () => notificationService.updateEmailTemplate(template.type, { subject, heading, body }),
        onSuccess: (data) => {
            queryClient.setQueryData(['emailTemplates'], (old = []) =>
                old.map((t) => (t.type === data.type ? data : t)),
            )
            toast.success('Template saved')
            onSaved?.(data)
        },
        onError: () => toast.error('Failed to save template'),
    })

    const resetMutation = useMutation({
        mutationFn: () => notificationService.resetEmailTemplate(template.type),
        onSuccess: (data) => {
            queryClient.setQueryData(['emailTemplates'], (old = []) =>
                old.map((t) => (t.type === data.type ? data : t)),
            )
            toast.success('Reset to default')
            onSaved?.(data)
        },
        onError: () => toast.error('Failed to reset template'),
    })

    const insertPlaceholder = (ph) => {
        setBody((prev) => `${prev}{${ph}}`)
    }

    const effSubject = subject || template.default_subject
    const effHeading = heading || template.default_heading
    const effBody = body || template.default_body

    const previewSubject = fillPlaceholders(effSubject, { ...SAMPLE, tenant_name: template.tenant_name || SAMPLE.tenant_name })
    const previewHeading = fillPlaceholders(effHeading, SAMPLE)
    const previewBodyHtml = textToHtml(fillPlaceholders(effBody, SAMPLE))

    return (
        <div className="card p-6 space-y-4">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <h4 className="text-base font-bold text-surface-900 dark:text-white flex items-center gap-2">
                        <Mail className="w-4 h-4 text-primary-500" /> {template.label}
                    </h4>
                    {template.description && (
                        <p className="text-sm text-surface-500 mt-1">{template.description}</p>
                    )}
                </div>
                {template.is_custom ? (
                    <span className="shrink-0 text-xs font-semibold px-2 py-1 rounded-full text-primary-600 bg-primary-100 dark:bg-primary-900/30">
                        Customised
                    </span>
                ) : (
                    <span className="shrink-0 text-xs font-semibold px-2 py-1 rounded-full text-surface-500 bg-surface-100 dark:bg-surface-800">
                        Default
                    </span>
                )}
            </div>

            {/* Placeholder chips */}
            {template.placeholders?.length > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-surface-500 inline-flex items-center gap-1">
                        <Info className="w-3.5 h-3.5" /> Insert:
                    </span>
                    {template.placeholders.map((ph) => (
                        <button
                            key={ph}
                            type="button"
                            onClick={() => insertPlaceholder(ph)}
                            className="text-xs font-mono px-2 py-1 rounded-md border border-surface-200 dark:border-surface-700 text-surface-600 dark:text-surface-300 hover:border-primary-400 hover:text-primary-600 transition-colors"
                            title={`Insert {${ph}} into the body`}
                        >
                            {`{${ph}}`}
                        </button>
                    ))}
                </div>
            )}

            <div>
                <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">Subject</label>
                <input
                    type="text"
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    placeholder={template.default_subject}
                    maxLength={500}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
            </div>

            <div>
                <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">Heading</label>
                <input
                    type="text"
                    value={heading}
                    onChange={(e) => setHeading(e.target.value)}
                    placeholder={template.default_heading}
                    maxLength={255}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
            </div>

            <div>
                <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                    Body <span className="text-surface-400 font-normal">(plain text — blank line starts a new paragraph)</span>
                </label>
                <textarea
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                    placeholder={template.default_body}
                    rows={6}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500 resize-y"
                />
                <p className="text-xs text-surface-400 mt-1">
                    Leave a field blank to use the default. The tenant logo, name and action button are added automatically.
                </p>
            </div>

            <div className="flex flex-wrap items-center gap-3 pt-1">
                <button
                    type="button"
                    onClick={() => saveMutation.mutate()}
                    disabled={saveMutation.isPending}
                    className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold disabled:opacity-60 transition-colors"
                >
                    {saveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                    Save
                </button>
                <button
                    type="button"
                    onClick={() => setShowPreview((v) => !v)}
                    className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 text-surface-700 dark:text-surface-200 text-sm font-semibold hover:border-primary-400 transition-colors"
                >
                    <Eye className="w-4 h-4" /> {showPreview ? 'Hide preview' : 'Preview'}
                </button>
                {template.is_custom && (
                    <button
                        type="button"
                        onClick={() => resetMutation.mutate()}
                        disabled={resetMutation.isPending}
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 text-surface-500 text-sm font-semibold hover:text-red-600 hover:border-red-300 disabled:opacity-60 transition-colors"
                    >
                        {resetMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
                        Reset to default
                    </button>
                )}
            </div>

            {showPreview && (
                <div className="rounded-xl border border-surface-200 dark:border-surface-700 overflow-hidden">
                    <div className="px-4 py-2.5 bg-surface-50 dark:bg-surface-800 border-b border-surface-200 dark:border-surface-700">
                        <p className="text-xs text-surface-400">Subject</p>
                        <p className="text-sm font-semibold text-surface-900 dark:text-white">{previewSubject}</p>
                    </div>
                    <div className="p-5 bg-white dark:bg-surface-900">
                        <p className="text-lg font-bold text-surface-900 dark:text-white mb-3">{previewHeading}</p>
                        <div
                            className="prose prose-sm max-w-none text-surface-700 dark:text-surface-300 [&_p]:mb-3"
                            dangerouslySetInnerHTML={{ __html: previewBodyHtml }}
                        />
                    </div>
                </div>
            )}
        </div>
    )
}

const EMPTY_DOMAIN = {
    domain: '',
    sender_username: 'notifications',
    sender_name: '',
    is_active: false,
}

const domainFormFromConfig = (domain) => ({
    domain: domain?.domain || '',
    sender_username: domain?.sender_username || 'notifications',
    sender_name: domain?.sender_name || '',
    is_active: Boolean(domain?.is_active),
})

const mutationError = (err, fallback) => {
    const data = err?.response?.data
    if (data?.detail) return data.detail
    if (data && typeof data === 'object') {
        return Object.values(data).flat().join(' ')
    }
    return fallback
}

const verificationTone = (status) => {
    if (status === 'Verified') {
        return {
            label: 'Verified',
            className: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
            icon: CheckCircle2,
        }
    }
    if (status === 'VerificationFailed') {
        return {
            label: 'Failed',
            className: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400',
            icon: AlertCircle,
        }
    }
    return {
        label: status === 'NotStarted' ? 'Not checked' : 'Checking',
        className: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
        icon: Clock3,
    }
}

const copyText = async (value) => {
    await navigator.clipboard.writeText(value)
    toast.success('Copied')
}

const dnsRecordHost = (name, domain) => {
    const cleanName = (name || '').trim().replace(/\.$/, '')
    const cleanDomain = (domain || '').trim().toLowerCase().replace(/\.$/, '')
    if (!cleanName || cleanName === '@') return cleanDomain
    if (
        cleanName.toLowerCase() === cleanDomain
        || cleanName.toLowerCase().endsWith(`.${cleanDomain}`)
    ) {
        return cleanName
    }
    return `${cleanName}.${cleanDomain}`
}

const CopyableDnsField = ({ label, value, tone = 'default' }) => {
    const isAmber = tone === 'amber'
    return (
        <div className="min-w-0">
            <p className={`text-[11px] uppercase tracking-wide mb-1 ${
                isAmber
                    ? 'text-amber-700/70 dark:text-amber-400'
                    : 'text-surface-400'
            }`}>
                {label}
            </p>
            <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 ${
                isAmber
                    ? 'border-amber-200 bg-white/70 dark:border-amber-800 dark:bg-surface-900/30'
                    : 'border-surface-200 bg-surface-50 dark:border-surface-700 dark:bg-surface-900'
            }`}>
                <code className={`min-w-0 flex-1 text-xs break-all ${
                    isAmber
                        ? 'text-amber-950 dark:text-amber-100'
                        : 'text-surface-700 dark:text-surface-200'
                }`}>
                    {value}
                </code>
                <button
                    type="button"
                    onClick={() => copyText(value)}
                    className="shrink-0 p-1.5 rounded-md text-surface-400 hover:text-primary-600 hover:bg-primary-50 dark:hover:bg-primary-900/20 transition-colors"
                    title={`Copy ${label.toLowerCase()}`}
                    aria-label={`Copy ${label.toLowerCase()}`}
                >
                    <Copy className="w-3.5 h-3.5" />
                </button>
            </div>
        </div>
    )
}

const SetupProgress = ({ currentStep }) => {
    const steps = [
        ['Sender', 'Choose the address'],
        ['DNS', 'Publish records'],
        ['Verify', 'Confirm ownership'],
        ['Activate', 'Send a test'],
    ]

    return (
        <ol className="grid gap-2 sm:grid-cols-4">
            {steps.map(([label, description], index) => {
                const step = index + 1
                const complete = step < currentStep
                const active = step === currentStep
                return (
                    <li
                        key={label}
                        className={`rounded-xl border p-3 ${
                            active
                                ? 'border-primary-400 bg-primary-50 dark:border-primary-700 dark:bg-primary-900/20'
                                : complete
                                    ? 'border-emerald-200 bg-emerald-50/60 dark:border-emerald-800 dark:bg-emerald-900/10'
                                    : 'border-surface-200 bg-surface-50/60 dark:border-surface-800 dark:bg-surface-900/40'
                        }`}
                    >
                        <div className="flex items-center gap-2">
                            <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${
                                active
                                    ? 'bg-primary-500 text-white'
                                    : complete
                                        ? 'bg-emerald-500 text-white'
                                        : 'bg-surface-200 text-surface-500 dark:bg-surface-700'
                            }`}>
                                {complete ? <CheckCircle2 className="w-3.5 h-3.5" /> : step}
                            </span>
                            <span className="text-sm font-bold text-surface-800 dark:text-surface-100">{label}</span>
                        </div>
                        <p className="mt-1 pl-8 text-xs text-surface-500">{description}</p>
                    </li>
                )
            })}
        </ol>
    )
}

const OutboundEmailDomain = () => {
    const queryClient = useQueryClient()
    const [form, setForm] = useState(EMPTY_DOMAIN)
    const [verificationRequested, setVerificationRequested] = useState(false)

    const { data, isLoading } = useQuery({
        queryKey: ['tenantEmailDomain'],
        queryFn: () => tenantAdminService.getEmailDomain(),
    })
    const emailDomain = data?.email_domain
    const records = Object.entries(emailDomain?.verification_records || {})
    const verificationStarted = Object.values(emailDomain?.verification_states || {})
        .some((state) => state?.status && state.status !== 'NotStarted')
    const currentStep = !emailDomain
        ? 1
        : emailDomain.is_ready
            ? 4
            : verificationRequested || verificationStarted
                ? 3
                : 2

    useEffect(() => {
        setForm(domainFormFromConfig(emailDomain))
    }, [emailDomain])

    const set = (key) => (event) => {
        const value = event.target.type === 'checkbox'
            ? event.target.checked
            : event.target.value
        setForm((current) => ({ ...current, [key]: value }))
    }

    const saveMutation = useMutation({
        mutationFn: () => tenantAdminService.saveEmailDomain({
            domain: form.domain.trim(),
            sender_username: form.sender_username.trim(),
            sender_name: form.sender_name.trim(),
            is_active: form.is_active,
        }),
        onSuccess: async (result) => {
            queryClient.setQueryData(['tenantEmailDomain'], result)
            await queryClient.invalidateQueries({ queryKey: ['tenantEmailDomain'] })
            toast.success(emailDomain ? 'Sender settings saved' : 'Domain added')
        },
        onError: (err) => toast.error(mutationError(err, 'Failed to save email domain')),
    })

    const verifyMutation = useMutation({
        mutationFn: () => tenantAdminService.verifyEmailDomain(),
        onSuccess: (result) => {
            queryClient.setQueryData(['tenantEmailDomain'], result)
            setVerificationRequested(true)
            toast.success(result.detail || 'Verification started')
        },
        onError: (err) => {
            const response = err?.response?.data
            if (response?.email_domain) {
                queryClient.setQueryData(['tenantEmailDomain'], response)
            }
            toast.error(mutationError(err, 'Could not start verification'))
        },
    })

    const refreshMutation = useMutation({
        mutationFn: () => tenantAdminService.refreshEmailDomain(),
        onSuccess: (result) => {
            queryClient.setQueryData(['tenantEmailDomain'], result)
            toast.success('Verification status refreshed')
        },
        onError: (err) => toast.error(mutationError(err, 'Could not refresh verification')),
    })

    const testMutation = useMutation({
        mutationFn: () => tenantAdminService.testEmailDomain(),
        onSuccess: (result) => toast.success(result.detail || 'Test email sent'),
        onError: (err) => toast.error(mutationError(err, 'Test email failed')),
    })

    const deleteMutation = useMutation({
        mutationFn: () => tenantAdminService.deleteEmailDomain(),
        onSuccess: (result) => {
            queryClient.setQueryData(['tenantEmailDomain'], result)
            setForm(EMPTY_DOMAIN)
            toast.success('Sender domain removed from DailyTaiyari')
        },
        onError: (err) => toast.error(mutationError(err, 'Failed to remove email domain')),
    })

    if (isLoading) {
        return (
            <div className="card p-6 flex items-center justify-center min-h-[180px]">
                <Loader2 className="w-7 h-7 animate-spin text-primary-500" />
            </div>
        )
    }

    return (
        <div className="card p-6 space-y-5">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white flex items-center gap-2">
                        <Globe2 className="w-5 h-5 text-primary-500" /> Sender domain setup
                    </h3>
                    <p className="text-sm text-surface-500 mt-1">
                        Follow the four steps below. DailyTaiyari handles delivery through Azure;
                        you only need access to your domain’s DNS.
                    </p>
                </div>
                {emailDomain && (
                    <span className={`shrink-0 text-xs font-semibold px-2.5 py-1 rounded-full ${
                        emailDomain.is_ready
                            ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
                            : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
                    }`}>
                        {emailDomain.is_ready ? 'Ready to send' : 'DNS verification required'}
                    </span>
                )}
            </div>

            <SetupProgress currentStep={currentStep} />

            {currentStep === 1 && (
            <div className="rounded-xl border border-surface-200 dark:border-surface-700 p-5 space-y-4">
                <div>
                    <h4 className="font-bold text-surface-900 dark:text-white">Step 1: Choose your sender</h4>
                    <p className="text-sm text-surface-500 mt-1">
                        Use a domain or subdomain that you control. No mailbox password is required.
                    </p>
                </div>
                <div className="grid sm:grid-cols-3 gap-4">
                <div>
                    <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                        Domain
                    </label>
                    <input
                        type="text"
                        value={form.domain}
                        onChange={set('domain')}
                        disabled={Boolean(emailDomain)}
                        placeholder="academy.com"
                        className="input w-full"
                    />
                    <p className="text-xs text-surface-400 mt-1">
                        You must control this domain’s DNS.
                    </p>
                </div>
                <div>
                    <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                        Sender address
                    </label>
                    <div className="flex">
                        <input
                            type="text"
                            value={form.sender_username}
                            onChange={set('sender_username')}
                            placeholder="notifications"
                            className="input w-full rounded-r-none"
                        />
                        <span className="inline-flex items-center px-3 rounded-r-xl border border-l-0 border-surface-200 dark:border-surface-700 bg-surface-50 dark:bg-surface-800 text-sm text-surface-500">
                            @{form.domain || 'domain.com'}
                        </span>
                    </div>
                </div>
                <div>
                    <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                        Sender name
                    </label>
                    <input
                        type="text"
                        value={form.sender_name}
                        onChange={set('sender_name')}
                        placeholder="Your Institute"
                        className="input w-full"
                    />
                </div>
                </div>
                <button
                    type="button"
                    onClick={() => saveMutation.mutate()}
                    disabled={saveMutation.isPending}
                    className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold disabled:opacity-60 transition-colors"
                >
                    {saveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <ChevronRight className="w-4 h-4" />}
                    Create domain and continue
                </button>
            </div>
            )}

            {emailDomain && (
                <div className="flex flex-col gap-3 rounded-xl border border-surface-200 bg-surface-50/60 p-4 dark:border-surface-800 dark:bg-surface-900/40 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                        <p className="text-xs font-semibold uppercase tracking-wide text-surface-400">Configured sender</p>
                        <p className="mt-1 break-all font-semibold text-surface-900 dark:text-white">
                            {emailDomain.sender_name || emailDomain.tenant_name || 'Tenant email'}
                            <span className="font-normal text-surface-500"> &lt;{emailDomain.from_email}&gt;</span>
                        </p>
                    </div>
                    <span className="shrink-0 rounded-full bg-white px-3 py-1 text-xs font-medium text-surface-500 shadow-sm dark:bg-surface-800">
                        {emailDomain.domain}
                    </span>
                </div>
            )}

            {emailDomain && records.length === 0 && !emailDomain.is_ready && (
                <div className="rounded-xl border border-primary-200 bg-primary-50/60 p-5 dark:border-primary-800 dark:bg-primary-900/20">
                    <div className="flex items-start gap-3">
                        <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-primary-500" />
                        <div>
                            <h4 className="font-bold text-surface-900 dark:text-white">
                                Preparing your DNS records
                            </h4>
                            <p className="mt-1 text-sm text-surface-500">
                                Azure is creating the domain. This normally takes a few seconds; refresh
                                once to load the records you need to publish.
                            </p>
                            <button
                                type="button"
                                onClick={() => refreshMutation.mutate()}
                                disabled={refreshMutation.isPending}
                                className="mt-3 inline-flex items-center gap-2 rounded-xl border border-primary-300 bg-white px-4 py-2 text-sm font-semibold text-primary-600 disabled:opacity-50 dark:border-primary-700 dark:bg-surface-900"
                            >
                                <RefreshCw className={`h-4 w-4 ${refreshMutation.isPending ? 'animate-spin' : ''}`} />
                                Load DNS records
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {emailDomain && records.length > 0 && !emailDomain.is_ready && (
                <div className="rounded-xl border border-surface-200 dark:border-surface-700 p-5 space-y-4">
                    <div>
                        <h4 className="font-bold text-surface-900 dark:text-white">
                            Step {currentStep}: {currentStep === 2 ? 'Publish these DNS records' : 'Verification in progress'}
                        </h4>
                        <p className="text-sm text-surface-500">
                            {currentStep === 2
                                ? 'Copy each host and value into your DNS provider. The DKIM hosts below already include your full subdomain.'
                                : 'Azure is checking the records. Keep this page open and refresh the status after DNS has propagated.'}
                        </p>
                        <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">
                            A domain must have only one SPF record. If one already exists, merge Azure’s
                            include value into it instead of creating a second SPF record.
                        </p>
                    </div>
                    <div className="space-y-3">
                        {records.map(([key, record]) => {
                            const status = emailDomain.verification_states?.[key]?.status || 'NotStarted'
                            const tone = verificationTone(status)
                            const StatusIcon = tone.icon
                            const host = dnsRecordHost(record.name, emailDomain.domain)
                            return (
                                <div key={key} className="rounded-xl border border-surface-200 bg-white p-4 dark:border-surface-700 dark:bg-surface-900">
                                    <div className="flex items-center justify-between gap-3 mb-3">
                                        <div className="flex items-center gap-2">
                                            <span className="font-bold text-sm text-surface-900 dark:text-white">{key}</span>
                                            <span className="text-xs text-surface-400">{record.type}</span>
                                        </div>
                                        <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-full ${tone.className}`}>
                                            <StatusIcon className="w-3.5 h-3.5" /> {tone.label}
                                        </span>
                                    </div>
                                    <div className="grid gap-3 lg:grid-cols-2">
                                        <CopyableDnsField label="Name / host" value={host} />
                                        <CopyableDnsField label="Value" value={record.value} />
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                    <div className="rounded-xl border border-amber-200 bg-amber-50/70 dark:border-amber-800 dark:bg-amber-900/20 p-4 space-y-3">
                    <div className="flex items-start gap-2">
                        <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
                        <div>
                            <h4 className="font-bold text-sm text-amber-900 dark:text-amber-200">
                                Recommended DNS record: DMARC
                            </h4>
                            <p className="text-sm text-amber-800/80 dark:text-amber-300/80 mt-1">
                                Azure verifies SPF and DKIM but does not check DMARC. Without DMARC,
                                authenticated messages can still be placed in Spam.
                            </p>
                        </div>
                    </div>
                    <div className="grid gap-3 lg:grid-cols-2">
                        <CopyableDnsField
                            label="TXT name / host"
                            value={`_dmarc.${emailDomain.domain}`}
                            tone="amber"
                        />
                        <CopyableDnsField
                            label="Starter value"
                            value="v=DMARC1; p=none; adkim=r; aspf=r; pct=100"
                            tone="amber"
                        />
                    </div>
                    <p className="text-xs text-amber-700 dark:text-amber-400">
                        Start with <code>p=none</code> so mail is monitored without being rejected.
                        After DNS propagates, send a test and confirm SPF, DKIM and DMARC all pass in
                        the recipient’s message details.
                    </p>
                </div>
                </div>
            )}

            {emailDomain?.is_ready && (
                <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-5 space-y-4 dark:border-emerald-800 dark:bg-emerald-900/10">
                    <div className="flex items-start gap-3">
                        <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600 dark:text-emerald-400" />
                        <div>
                            <h4 className="font-bold text-surface-900 dark:text-white">
                                Step 4: Activate and test
                            </h4>
                            <p className="mt-1 text-sm text-surface-500">
                                Azure has verified and linked this sender. Turn it on, save, then send
                                a test email before relying on it for student communication.
                            </p>
                        </div>
                    </div>
                    <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-emerald-200 bg-white p-4 dark:border-emerald-800 dark:bg-surface-900">
                        <input
                            type="checkbox"
                            checked={form.is_active}
                            onChange={set('is_active')}
                            className="mt-1 h-4 w-4 rounded border-surface-300 text-primary-500 focus:ring-primary-500"
                        />
                        <span>
                            <span className="block text-sm font-semibold text-surface-800 dark:text-surface-100">
                                Use {emailDomain.from_email} for tenant emails
                            </span>
                            <span className="block text-xs text-surface-500 mt-0.5">
                                DailyTaiyari’s verified platform sender remains the automatic fallback.
                            </span>
                        </span>
                    </label>
                </div>
            )}
            {emailDomain?.last_error && (
                <div className="flex items-start gap-2 rounded-xl bg-amber-50 dark:bg-amber-900/20 p-3 text-sm text-amber-700 dark:text-amber-400">
                    <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                    <span><strong>Last Azure error:</strong> {emailDomain.last_error}</span>
                </div>
            )}

            <div className="flex flex-wrap gap-3">
                {currentStep === 2 && records.length > 0 && (
                    <button
                        type="button"
                        onClick={() => verifyMutation.mutate()}
                        disabled={verifyMutation.isPending}
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold disabled:opacity-50 transition-colors"
                    >
                        {verifyMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
                        I’ve added the DNS records — verify
                    </button>
                )}
                {currentStep === 3 && (
                    <button
                        type="button"
                        onClick={() => refreshMutation.mutate()}
                        disabled={refreshMutation.isPending}
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold disabled:opacity-50 transition-colors"
                    >
                        <RefreshCw className={`w-4 h-4 ${refreshMutation.isPending ? 'animate-spin' : ''}`} />
                        Check verification status
                    </button>
                )}
                {emailDomain?.is_ready && (
                    <button
                        type="button"
                        onClick={() => saveMutation.mutate()}
                        disabled={saveMutation.isPending}
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold disabled:opacity-60 transition-colors"
                    >
                        {saveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                        Save activation
                    </button>
                )}
                {emailDomain?.is_ready && (
                    <button
                        type="button"
                        onClick={() => testMutation.mutate()}
                        disabled={testMutation.isPending}
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 text-surface-700 dark:text-surface-200 text-sm font-semibold disabled:opacity-50 hover:border-primary-400 transition-colors"
                    >
                        {testMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                        Send test email
                    </button>
                )}
                {emailDomain && (
                    <button
                        type="button"
                        onClick={() => {
                            if (window.confirm(
                                'Unlink this sender domain and remove it from DailyTaiyari? '
                                + 'The Azure domain resource will be retained for platform-admin cleanup.',
                            )) {
                                deleteMutation.mutate()
                            }
                        }}
                        disabled={deleteMutation.isPending}
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-rose-200 text-rose-600 text-sm font-semibold disabled:opacity-50 hover:bg-rose-50 dark:hover:bg-rose-900/20 transition-colors"
                    >
                        <Trash2 className="w-4 h-4" /> Remove
                    </button>
                )}
            </div>
            {emailDomain && !emailDomain.is_ready && (
                <p className="text-xs text-surface-400">
                    DNS changes usually take 15–30 minutes, but some providers can take longer.
                </p>
            )}
        </div>
    )
}

const EmailSettings = ({ settings }) => {
    const queryClient = useQueryClient()
    const [notificationEmail, setNotificationEmail] = useState(settings?.notification_email || '')
    const [section, setSection] = useState(
        settings?.custom_email_domains_enabled ? 'sender' : 'notifications',
    )

    useEffect(() => {
        setNotificationEmail(settings?.notification_email || '')
    }, [settings?.notification_email])

    useEffect(() => {
        if (!settings?.custom_email_domains_enabled && section === 'sender') {
            setSection('notifications')
        }
    }, [section, settings?.custom_email_domains_enabled])

    const { data: templates = [], isLoading } = useQuery({
        queryKey: ['emailTemplates'],
        queryFn: () => notificationService.getEmailTemplates(),
    })

    const emailMutation = useMutation({
        mutationFn: (val) => tenantAdminService.updateNotificationEmail(val),
        onSuccess: (data) => {
            queryClient.setQueryData(['tenantSettings'], data)
            toast.success('Notification email updated')
        },
        onError: (err) => {
            const msg = err?.response?.data?.notification_email?.[0] || 'Failed to update notification email'
            toast.error(msg)
        },
    })

    const sections = [
        ...(settings?.custom_email_domains_enabled
            ? [{
                id: 'sender',
                label: 'Sender setup',
                description: 'Verify your sending domain',
                icon: Globe2,
            }]
            : []),
        {
            id: 'notifications',
            label: 'Notification recipients',
            description: 'Choose who receives admin alerts',
            icon: BellRing,
        },
        {
            id: 'templates',
            label: 'Email templates',
            description: 'Customise automated messages',
            icon: FileText,
        },
    ]

    return (
        <div className="space-y-6">
            <div className="grid gap-3 md:grid-cols-3">
                {sections.map((item) => {
                    const active = section === item.id
                    const Icon = item.icon
                    return (
                        <button
                            key={item.id}
                            type="button"
                            onClick={() => setSection(item.id)}
                            className={`flex items-center gap-3 rounded-xl border p-4 text-left transition-colors ${
                                active
                                    ? 'border-primary-400 bg-primary-50 dark:border-primary-700 dark:bg-primary-900/20'
                                    : 'border-surface-200 bg-white hover:border-primary-300 dark:border-surface-800 dark:bg-surface-900'
                            }`}
                        >
                            <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                                active
                                    ? 'bg-primary-500 text-white'
                                    : 'bg-surface-100 text-surface-500 dark:bg-surface-800'
                            }`}>
                                <Icon className="h-5 w-5" />
                            </span>
                            <span className="min-w-0">
                                <span className="block text-sm font-bold text-surface-900 dark:text-white">
                                    {item.label}
                                </span>
                                <span className="mt-0.5 block text-xs text-surface-500">
                                    {item.description}
                                </span>
                            </span>
                        </button>
                    )
                })}
            </div>

            {section === 'sender' && settings?.custom_email_domains_enabled && <OutboundEmailDomain />}

            {/* Recipient address */}
            {section === 'notifications' && (
            <div className="card p-6 space-y-4">
                <div className="flex items-center gap-2">
                    <AtSign className="w-5 h-5 text-primary-500" />
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">Notification recipient</h3>
                </div>
                <p className="text-sm text-surface-500">
                    Where should admin notification emails (like new enrollment requests) be sent? Separate multiple
                    addresses with commas. Leave blank to send to all admin accounts.
                </p>
                <div className="flex flex-col sm:flex-row gap-3 sm:items-end">
                    <div className="flex-1">
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                            Notification email(s)
                        </label>
                        <input
                            type="text"
                            value={notificationEmail}
                            onChange={(e) => setNotificationEmail(e.target.value)}
                            placeholder="admissions@institute.com, office@institute.com"
                            className="w-full px-3.5 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                        />
                    </div>
                    <button
                        type="button"
                        onClick={() => emailMutation.mutate(notificationEmail)}
                        disabled={emailMutation.isPending}
                        className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold disabled:opacity-60 transition-colors"
                    >
                        {emailMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                        Save
                    </button>
                </div>
            </div>
            )}

            {/* Template editors */}
            {section === 'templates' && (
            <div>
                <h3 className="text-lg font-bold text-surface-900 dark:text-white mb-1">Email templates</h3>
                <p className="text-sm text-surface-500 mb-4">
                    Customise the wording of the automated enrollment emails. Every email keeps your institution's logo,
                    name and branding.
                </p>
                {isLoading ? (
                    <div className="flex items-center justify-center min-h-[160px]">
                        <Loader2 className="w-7 h-7 animate-spin text-primary-500" />
                    </div>
                ) : (
                    <div className="space-y-5">
                        {templates.map((t) => (
                            <TemplateEditor key={t.type} template={t} />
                        ))}
                    </div>
                )}
            </div>
            )}
        </div>
    )
}

export default EmailSettings
