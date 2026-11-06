import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
    Mail, Save, RotateCcw, Eye, Loader2, Info, AtSign, Send,
    Globe2, Trash2, ShieldCheck, AlertCircle, Copy, RefreshCw,
    CheckCircle2, Clock3,
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

const OutboundEmailDomain = () => {
    const queryClient = useQueryClient()
    const [form, setForm] = useState(EMPTY_DOMAIN)

    const { data, isLoading } = useQuery({
        queryKey: ['tenantEmailDomain'],
        queryFn: () => tenantAdminService.getEmailDomain(),
    })
    const emailDomain = data?.email_domain

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
        onSuccess: (result) => {
            queryClient.setQueryData(['tenantEmailDomain'], result)
            toast.success(emailDomain ? 'Sender settings saved' : 'Domain added')
        },
        onError: (err) => toast.error(mutationError(err, 'Failed to save email domain')),
    })

    const verifyMutation = useMutation({
        mutationFn: () => tenantAdminService.verifyEmailDomain(),
        onSuccess: (result) => {
            queryClient.setQueryData(['tenantEmailDomain'], result)
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
                        <Globe2 className="w-5 h-5 text-primary-500" /> Verified sender domain
                    </h3>
                    <p className="text-sm text-surface-500 mt-1">
                        Send email as your institution without sharing a mailbox password. Add the DNS
                        records below; DailyTaiyari handles delivery through Azure.
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

            {emailDomain && Object.keys(emailDomain.verification_records || {}).length > 0 && (
                <div className="space-y-3">
                    <div>
                        <h4 className="font-bold text-surface-900 dark:text-white">Add these DNS records</h4>
                        <p className="text-sm text-surface-500">
                            Add them at the company where your domain’s DNS is managed. Keep any existing
                            records unless your DNS provider tells you they conflict.
                        </p>
                        <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">
                            A domain must have only one SPF record. If one already exists, merge Azure’s
                            include value into it instead of creating a second SPF record.
                        </p>
                    </div>
                    <div className="space-y-3">
                        {Object.entries(emailDomain.verification_records).map(([key, record]) => {
                            const status = emailDomain.verification_states?.[key]?.status || 'NotStarted'
                            const tone = verificationTone(status)
                            const StatusIcon = tone.icon
                            return (
                                <div key={key} className="rounded-xl border border-surface-200 dark:border-surface-700 p-4">
                                    <div className="flex items-center justify-between gap-3 mb-3">
                                        <div className="flex items-center gap-2">
                                            <span className="font-bold text-sm text-surface-900 dark:text-white">{key}</span>
                                            <span className="text-xs text-surface-400">{record.type}</span>
                                        </div>
                                        <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-full ${tone.className}`}>
                                            <StatusIcon className="w-3.5 h-3.5" /> {tone.label}
                                        </span>
                                    </div>
                                    <div className="grid sm:grid-cols-[1fr_2fr_auto] gap-3 items-end">
                                        <div>
                                            <p className="text-[11px] uppercase tracking-wide text-surface-400 mb-1">Name / host</p>
                                            <code className="block text-xs break-all text-surface-700 dark:text-surface-200">{record.name}</code>
                                        </div>
                                        <div>
                                            <p className="text-[11px] uppercase tracking-wide text-surface-400 mb-1">Value</p>
                                            <code className="block text-xs break-all text-surface-700 dark:text-surface-200">{record.value}</code>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={() => copyText(record.value)}
                                            className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-surface-200 dark:border-surface-700 text-xs font-semibold"
                                        >
                                            <Copy className="w-3.5 h-3.5" /> Copy value
                                        </button>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                </div>
            )}

            {emailDomain && (
                <div className="rounded-xl border border-amber-200 bg-amber-50/70 dark:border-amber-800 dark:bg-amber-900/20 p-4 space-y-3">
                    <div className="flex items-start gap-2">
                        <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
                        <div>
                            <h4 className="font-bold text-sm text-amber-900 dark:text-amber-200">
                                Recommended: configure DMARC
                            </h4>
                            <p className="text-sm text-amber-800/80 dark:text-amber-300/80 mt-1">
                                Azure verifies SPF and DKIM but does not check DMARC. Without DMARC,
                                authenticated messages can still be placed in Spam.
                            </p>
                        </div>
                    </div>
                    <div className="grid sm:grid-cols-[1fr_2fr_auto] gap-3 items-end">
                        <div>
                            <p className="text-[11px] uppercase tracking-wide text-amber-700/70 dark:text-amber-400 mb-1">
                                TXT name / host
                            </p>
                            <code className="block text-xs break-all text-amber-950 dark:text-amber-100">
                                _dmarc.{emailDomain.domain}
                            </code>
                        </div>
                        <div>
                            <p className="text-[11px] uppercase tracking-wide text-amber-700/70 dark:text-amber-400 mb-1">
                                Starter value
                            </p>
                            <code className="block text-xs break-all text-amber-950 dark:text-amber-100">
                                v=DMARC1; p=none; adkim=r; aspf=r; pct=100
                            </code>
                        </div>
                        <button
                            type="button"
                            onClick={() => copyText('v=DMARC1; p=none; adkim=r; aspf=r; pct=100')}
                            className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-amber-300 dark:border-amber-700 text-xs font-semibold text-amber-800 dark:text-amber-300"
                        >
                            <Copy className="w-3.5 h-3.5" /> Copy value
                        </button>
                    </div>
                    <p className="text-xs text-amber-700 dark:text-amber-400">
                        Start with <code>p=none</code> so mail is monitored without being rejected.
                        After DNS propagates, send a test and confirm SPF, DKIM and DMARC all pass in
                        the recipient’s message details.
                    </p>
                </div>
            )}

            {emailDomain?.is_ready && (
                <label className="flex items-start gap-3 rounded-xl border border-surface-200 dark:border-surface-700 p-4 cursor-pointer">
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
                            DailyTaiyari’s verified sender remains the automatic fallback.
                        </span>
                    </span>
                </label>
            )}

            {emailDomain?.is_ready && !emailDomain?.last_error && (
                <div className="flex items-start gap-2 rounded-xl bg-emerald-50 dark:bg-emerald-900/20 p-3 text-sm text-emerald-700 dark:text-emerald-400">
                    <ShieldCheck className="w-4 h-4 mt-0.5 shrink-0" />
                    Azure has verified and linked this domain. It is ready to send.
                </div>
            )}
            {emailDomain?.last_error && (
                <div className="flex items-start gap-2 rounded-xl bg-amber-50 dark:bg-amber-900/20 p-3 text-sm text-amber-700 dark:text-amber-400">
                    <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                    <span><strong>Last Azure error:</strong> {emailDomain.last_error}</span>
                </div>
            )}

            <div className="flex flex-wrap gap-3">
                <button
                    type="button"
                    onClick={() => saveMutation.mutate()}
                    disabled={saveMutation.isPending}
                    className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold disabled:opacity-60 transition-colors"
                >
                    {saveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                    {emailDomain ? 'Save sender' : 'Add domain'}
                </button>
                {emailDomain && !emailDomain.is_ready && (
                    <button
                        type="button"
                        onClick={() => verifyMutation.mutate()}
                        disabled={verifyMutation.isPending}
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 text-surface-700 dark:text-surface-200 text-sm font-semibold disabled:opacity-50 hover:border-primary-400 transition-colors"
                    >
                        {verifyMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
                        Verify DNS
                    </button>
                )}
                {emailDomain && (
                    <button
                        type="button"
                        onClick={() => refreshMutation.mutate()}
                        disabled={refreshMutation.isPending}
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 text-surface-700 dark:text-surface-200 text-sm font-semibold disabled:opacity-50 hover:border-primary-400 transition-colors"
                    >
                        <RefreshCw className={`w-4 h-4 ${refreshMutation.isPending ? 'animate-spin' : ''}`} />
                        Refresh status
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
            <p className="text-xs text-surface-400">
                DNS changes usually take 15–30 minutes, but some providers can take longer. No mailbox
                password is required or stored.
            </p>
        </div>
    )
}

const EmailSettings = ({ settings }) => {
    const queryClient = useQueryClient()
    const [notificationEmail, setNotificationEmail] = useState(settings?.notification_email || '')

    useEffect(() => {
        setNotificationEmail(settings?.notification_email || '')
    }, [settings?.notification_email])

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

    return (
        <div className="space-y-6">
            {settings?.custom_email_domains_enabled && <OutboundEmailDomain />}

            {/* Recipient address */}
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

            {/* Template editors */}
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
        </div>
    )
}

export default EmailSettings
