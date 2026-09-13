import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  Check,
  Loader2,
  Maximize,
  Minimize,
  Pause,
  PictureInPicture2,
  Play,
  RotateCcw,
  RotateCw,
  Settings,
  Volume1,
  Volume2,
  VolumeX,
} from 'lucide-react'

const SKIP_SECONDS = 10
const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2]

/**
 * Resolve a pasted video URL into an embeddable form.
 * Supports YouTube (watch / youtu.be / shorts / embed), Vimeo and Google Drive.
 * Returns { kind: 'iframe' | 'file' | 'none', src }.
 */
export const resolveVideo = (url = '', fileUrl = '') => {
  if (fileUrl) return { kind: 'file', src: fileUrl }
  const u = (url || '').trim()
  if (!u) return { kind: 'none', src: '' }

  // YouTube
  const yt =
    u.match(/(?:youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/|live\/)|youtu\.be\/)([\w-]{11})/) ||
    u.match(/[?&]v=([\w-]{11})/)
  if (yt) {
    return { kind: 'iframe', src: `https://www.youtube.com/embed/${yt[1]}` }
  }

  // Vimeo
  const vimeo = u.match(/vimeo\.com\/(?:video\/)?(\d+)/)
  if (vimeo) {
    return { kind: 'iframe', src: `https://player.vimeo.com/video/${vimeo[1]}` }
  }

  // Google Drive
  const gdrive = u.match(/drive\.google\.com\/(?:file\/d\/|open\?id=)([\w-]+)/)
  if (gdrive) {
    return { kind: 'iframe', src: `https://drive.google.com/file/d/${gdrive[1]}/preview` }
  }

  // Fallback: if it already looks like an embeddable/iframe URL, use as-is.
  if (/^https?:\/\//.test(u)) return { kind: 'iframe', src: u }
  return { kind: 'none', src: '' }
}

const formatTime = (seconds) => {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const total = Math.floor(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  return `${m}:${String(s).padStart(2, '0')}`
}

const STORAGE_KEY = 'dt-video-prefs'

const readPrefs = () => {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}
  } catch {
    return {}
  }
}

const writePrefs = (patch) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...readPrefs(), ...patch }))
  } catch {
    /* ignore */
  }
}

/**
 * Custom HTML5 video player with modern controls: play/pause, ±10s skip,
 * scrubbing with buffered range, volume, playback speed, picture-in-picture,
 * fullscreen and keyboard shortcuts.
 */
const FileVideoPlayer = ({ src, title }) => {
  const videoRef = useRef(null)
  const shellRef = useRef(null)
  const hideTimer = useRef(null)
  // Target of an in-flight seek. Some hosts drop the connection when we jump
  // past the buffered range, which makes the element reload and restart at 0 —
  // we re-apply this target once the media is ready again.
  const pendingSeekRef = useRef(null)
  const seekAttemptsRef = useRef(0)
  const resumeAfterSeekRef = useRef(false)

  const [playing, setPlaying] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [ended, setEnded] = useState(false)
  const [duration, setDuration] = useState(0)
  const [current, setCurrent] = useState(0)
  const [buffered, setBuffered] = useState(0)
  const [volume, setVolume] = useState(() => {
    const v = readPrefs().volume
    return typeof v === 'number' ? v : 1
  })
  const [muted, setMuted] = useState(() => !!readPrefs().muted)
  const [speed, setSpeed] = useState(() => {
    const s = readPrefs().speed
    return SPEEDS.includes(s) ? s : 1
  })
  const [fullscreen, setFullscreen] = useState(false)
  const [controlsVisible, setControlsVisible] = useState(true)
  const [showSpeedMenu, setShowSpeedMenu] = useState(false)
  const [scrubbing, setScrubbing] = useState(false)
  const [feedback, setFeedback] = useState(null)

  useEffect(() => {
    if (!feedback) return undefined
    const t = setTimeout(() => setFeedback(null), 650)
    return () => clearTimeout(t)
  }, [feedback])

  const revealControls = useCallback(() => {
    setControlsVisible(true)
    if (hideTimer.current) clearTimeout(hideTimer.current)
    hideTimer.current = setTimeout(() => {
      const video = videoRef.current
      if (video && !video.paused && !video.ended) setControlsVisible(false)
    }, 2600)
  }, [])

  useEffect(() => () => hideTimer.current && clearTimeout(hideTimer.current), [])

  const togglePlay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (video.paused || video.ended) video.play().catch(() => {})
    else video.pause()
    revealControls()
  }, [revealControls])

  const applySeek = useCallback((target) => {
    const video = videoRef.current
    if (!video) return
    pendingSeekRef.current = target
    seekAttemptsRef.current = 0
    resumeAfterSeekRef.current = !video.paused && !video.ended
    try {
      video.currentTime = target
    } catch {
      /* seek may throw while the media is not ready yet */
    }
    setCurrent(target)
  }, [])

  const clearPendingSeek = useCallback(() => {
    const video = videoRef.current
    pendingSeekRef.current = null
    seekAttemptsRef.current = 0
    if (video && resumeAfterSeekRef.current && video.paused && !video.ended) {
      video.play().catch(() => {})
    }
    resumeAfterSeekRef.current = false
    if (video) setCurrent(video.currentTime)
  }, [])

  // Re-apply a pending seek once the element is ready again. Covers hosts that
  // restart the stream (and reset currentTime to 0) on a forward jump.
  const settlePendingSeek = useCallback(() => {
    const video = videoRef.current
    const target = pendingSeekRef.current
    if (!video || target == null) return
    if (!Number.isFinite(video.duration) || video.duration <= 0) return
    if (Math.abs(video.currentTime - target) < 0.75) {
      clearPendingSeek()
      return
    }
    if (seekAttemptsRef.current >= 3) {
      // Source refuses to seek there — stop fighting it and follow the media.
      clearPendingSeek()
      return
    }
    seekAttemptsRef.current += 1
    try {
      video.currentTime = Math.min(target, Math.max(video.duration - 0.25, 0))
    } catch {
      clearPendingSeek()
    }
  }, [clearPendingSeek])

  const seekToTime = useCallback(
    (value) => {
      const video = videoRef.current
      if (!video) return
      const dur = Number.isFinite(video.duration) ? video.duration : 0
      if (dur <= 0) return
      // Stop just short of the very end so a forward jump never fires `ended`.
      applySeek(Math.min(Math.max(value, 0), Math.max(dur - 0.25, 0)))
    },
    [applySeek],
  )

  const seekBy = useCallback(
    (delta) => {
      const video = videoRef.current
      if (!video) return
      const from = pendingSeekRef.current ?? video.currentTime
      seekToTime(from + delta)
      setFeedback({ dir: delta > 0 ? 'forward' : 'back', value: Math.abs(delta), id: Date.now() })
      revealControls()
    },
    [seekToTime, revealControls],
  )

  const seekTo = seekToTime

  // Safety net: never let a stuck pending seek block time updates forever.
  useEffect(() => {
    const t = setInterval(() => {
      const video = videoRef.current
      if (!video || pendingSeekRef.current == null) return
      if (video.readyState >= 1) settlePendingSeek()
    }, 500)
    return () => clearInterval(t)
  }, [settlePendingSeek])

  const changeVolume = useCallback((value) => {
    const video = videoRef.current
    const next = Math.round(Math.min(Math.max(value, 0), 1) * 100) / 100
    setVolume(next)
    setMuted(next === 0)
    if (video) {
      video.volume = next
      video.muted = next === 0
    }
    writePrefs({ volume: next, muted: next === 0 })
  }, [])

  const toggleMute = useCallback(() => {
    const video = videoRef.current
    const next = !muted
    setMuted(next)
    if (video) video.muted = next
    if (!next && volume === 0) changeVolume(0.5)
    writePrefs({ muted: next })
  }, [muted, volume, changeVolume])

  const applySpeed = useCallback((value) => {
    const video = videoRef.current
    setSpeed(value)
    if (video) video.playbackRate = value
    writePrefs({ speed: value })
    setShowSpeedMenu(false)
  }, [])

  const toggleFullscreen = useCallback(() => {
    const shell = shellRef.current
    if (!shell) return
    if (document.fullscreenElement) {
      document.exitFullscreen?.()
    } else if (shell.requestFullscreen) {
      shell.requestFullscreen().catch(() => {})
    } else if (videoRef.current?.webkitEnterFullscreen) {
      // iOS Safari only allows fullscreen on the video element itself.
      videoRef.current.webkitEnterFullscreen()
    }
  }, [])

  const togglePip = useCallback(async () => {
    const video = videoRef.current
    if (!video || !document.pictureInPictureEnabled) return
    try {
      if (document.pictureInPictureElement) await document.exitPictureInPicture()
      else await video.requestPictureInPicture()
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    const onFsChange = () => setFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onFsChange)
    return () => document.removeEventListener('fullscreenchange', onFsChange)
  }, [])

  const handleLoadedMetadata = (e) => {
    const video = e.currentTarget
    setDuration(video.duration || 0)
    video.volume = volume
    video.muted = muted
    video.playbackRate = speed
    settlePendingSeek()
  }

  const handleProgress = (e) => {
    const video = e.currentTarget
    if (!video.buffered?.length) return
    setBuffered(video.buffered.end(video.buffered.length - 1))
  }

  const onKeyDown = useCallback(
    (e) => {
      const key = e.key === ' ' ? ' ' : e.key.toLowerCase()
      const handled = [' ', 'k', 'arrowleft', 'arrowright', 'arrowup', 'arrowdown', 'j', 'l', 'm', 'f', '0']
      if (!handled.includes(key)) return
      e.preventDefault()
      switch (key) {
        case ' ':
        case 'k':
          togglePlay()
          break
        case 'arrowleft':
          seekBy(-5)
          break
        case 'arrowright':
          seekBy(5)
          break
        case 'j':
          seekBy(-SKIP_SECONDS)
          break
        case 'l':
          seekBy(SKIP_SECONDS)
          break
        case 'arrowup':
          changeVolume(volume + 0.1)
          revealControls()
          break
        case 'arrowdown':
          changeVolume(volume - 0.1)
          revealControls()
          break
        case 'm':
          toggleMute()
          break
        case 'f':
          toggleFullscreen()
          break
        case '0':
          seekTo(0)
          break
        default:
          break
      }
    },
    [togglePlay, seekBy, changeVolume, volume, revealControls, toggleMute, toggleFullscreen, seekTo],
  )

  const progressPct = duration ? (current / duration) * 100 : 0
  const bufferedPct = duration ? Math.min((buffered / duration) * 100, 100) : 0
  const VolumeIcon = muted || volume === 0 ? VolumeX : volume < 0.5 ? Volume1 : Volume2

  return (
    <div
      ref={shellRef}
      tabIndex={0}
      role="region"
      aria-label={title || 'Video player'}
      onKeyDown={onKeyDown}
      onMouseMove={revealControls}
      onMouseLeave={() => playing && setControlsVisible(false)}
      className={`group relative w-full bg-black outline-none select-none ${
        fullscreen ? 'h-screen' : 'aspect-video'
      }`}
    >
      <video
        ref={videoRef}
        src={src}
        title={title}
        playsInline
        preload="metadata"
        controlsList="nodownload"
        onContextMenu={(e) => e.preventDefault()}
        onClick={togglePlay}
        onDoubleClick={toggleFullscreen}
        onLoadedMetadata={handleLoadedMetadata}
        onTimeUpdate={(e) => {
          if (scrubbing) return
          // While a seek is in flight, ignore stale positions from a stream
          // that restarted at 0 — settlePendingSeek will restore the target.
          if (pendingSeekRef.current != null) return
          setCurrent(e.currentTarget.currentTime)
        }}
        onSeeked={settlePendingSeek}
        onCanPlayThrough={settlePendingSeek}
        onLoadedData={settlePendingSeek}
        onDurationChange={(e) => setDuration(e.currentTarget.duration || 0)}
        onProgress={handleProgress}
        onPlay={() => {
          setPlaying(true)
          setEnded(false)
          revealControls()
        }}
        onPause={() => {
          setPlaying(false)
          setControlsVisible(true)
        }}
        onWaiting={() => setWaiting(true)}
        onPlaying={() => {
          setWaiting(false)
          settlePendingSeek()
        }}
        onCanPlay={() => {
          setWaiting(false)
          settlePendingSeek()
        }}
        onEnded={() => {
          setPlaying(false)
          setEnded(true)
          setControlsVisible(true)
        }}
        onVolumeChange={(e) => {
          setVolume(e.currentTarget.volume)
          setMuted(e.currentTarget.muted)
        }}
        className="w-full h-full object-contain"
      />

      {/* Double-tap zones for quick skip on touch devices */}
      <button
        type="button"
        aria-label={`Rewind ${SKIP_SECONDS} seconds`}
        onDoubleClick={() => seekBy(-SKIP_SECONDS)}
        onClick={togglePlay}
        className="absolute left-0 top-0 h-[72%] w-1/4 md:hidden"
      />
      <button
        type="button"
        aria-label={`Forward ${SKIP_SECONDS} seconds`}
        onDoubleClick={() => seekBy(SKIP_SECONDS)}
        onClick={togglePlay}
        className="absolute right-0 top-0 h-[72%] w-1/4 md:hidden"
      />

      {waiting && (
        <div className="absolute inset-0 grid place-items-center pointer-events-none">
          <Loader2 className="w-10 h-10 text-white/90 animate-spin" />
        </div>
      )}

      {!playing && !waiting && (
        <button
          type="button"
          onClick={togglePlay}
          aria-label={ended ? 'Replay' : 'Play'}
          className="absolute inset-0 grid place-items-center"
        >
          <span className="grid place-items-center w-16 h-16 md:w-20 md:h-20 rounded-full bg-black/55 backdrop-blur-sm ring-1 ring-white/25 transition-transform hover:scale-105">
            {ended ? (
              <RotateCcw className="w-8 h-8 text-white" />
            ) : (
              <Play className="w-8 h-8 text-white translate-x-0.5" fill="currentColor" />
            )}
          </span>
        </button>
      )}

      {feedback && (
        <div
          className={`absolute top-1/2 -translate-y-1/2 pointer-events-none ${
            feedback.dir === 'forward' ? 'right-[12%]' : 'left-[12%]'
          }`}
        >
          <div className="flex flex-col items-center gap-1 px-4 py-3 rounded-full bg-black/60 backdrop-blur-sm">
            {feedback.dir === 'forward' ? (
              <RotateCw className="w-6 h-6 text-white" />
            ) : (
              <RotateCcw className="w-6 h-6 text-white" />
            )}
            <span className="text-xs font-semibold text-white">{feedback.value}s</span>
          </div>
        </div>
      )}

      <div
        className={`absolute inset-x-0 bottom-0 transition-opacity duration-200 bg-gradient-to-t from-black/85 via-black/45 to-transparent pt-12 ${
          controlsVisible ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-3 md:px-4">
          <div className="relative h-4 flex items-center group/seek">
            <div className="absolute inset-x-0 h-1 rounded-full bg-white/25 overflow-hidden transition-all group-hover/seek:h-1.5">
              <div className="absolute inset-y-0 left-0 bg-white/40" style={{ width: `${bufferedPct}%` }} />
              <div className="absolute inset-y-0 left-0 bg-primary-500" style={{ width: `${progressPct}%` }} />
            </div>
            <span
              className="absolute w-3 h-3 rounded-full bg-primary-500 shadow -translate-x-1/2 scale-0 group-hover/seek:scale-100 transition-transform"
              style={{ left: `${progressPct}%` }}
            />
            <input
              type="range"
              min={0}
              max={duration || 0}
              step={0.1}
              value={current}
              aria-label="Seek"
              onMouseDown={() => setScrubbing(true)}
              onTouchStart={() => setScrubbing(true)}
              onChange={(e) => seekTo(Number(e.target.value))}
              onMouseUp={() => setScrubbing(false)}
              onTouchEnd={() => setScrubbing(false)}
              className="relative w-full h-4 appearance-none bg-transparent cursor-pointer opacity-0"
            />
          </div>
        </div>

        <div className="flex items-center gap-0.5 md:gap-1.5 px-2 md:px-4 pb-2 md:pb-3 text-white">
          <button
            type="button"
            onClick={togglePlay}
            aria-label={playing ? 'Pause' : 'Play'}
            title={playing ? 'Pause (k)' : 'Play (k)'}
            className="p-2 rounded-full hover:bg-white/15 transition"
          >
            {playing ? (
              <Pause className="w-5 h-5" fill="currentColor" />
            ) : (
              <Play className="w-5 h-5" fill="currentColor" />
            )}
          </button>

          <button
            type="button"
            onClick={() => seekBy(-SKIP_SECONDS)}
            aria-label={`Rewind ${SKIP_SECONDS} seconds`}
            title={`Rewind ${SKIP_SECONDS}s (j)`}
            className="relative p-2 rounded-full hover:bg-white/15 transition"
          >
            <RotateCcw className="w-5 h-5" />
            <span className="absolute inset-0 grid place-items-center text-[8px] font-bold pt-[1px]">
              {SKIP_SECONDS}
            </span>
          </button>

          <button
            type="button"
            onClick={() => seekBy(SKIP_SECONDS)}
            aria-label={`Forward ${SKIP_SECONDS} seconds`}
            title={`Forward ${SKIP_SECONDS}s (l)`}
            className="relative p-2 rounded-full hover:bg-white/15 transition"
          >
            <RotateCw className="w-5 h-5" />
            <span className="absolute inset-0 grid place-items-center text-[8px] font-bold pt-[1px]">
              {SKIP_SECONDS}
            </span>
          </button>

          <div className="flex items-center group/vol">
            <button
              type="button"
              onClick={toggleMute}
              aria-label={muted ? 'Unmute' : 'Mute'}
              title="Mute (m)"
              className="p-2 rounded-full hover:bg-white/15 transition"
            >
              <VolumeIcon className="w-5 h-5" />
            </button>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={muted ? 0 : volume}
              aria-label="Volume"
              onChange={(e) => changeVolume(Number(e.target.value))}
              className="dt-video-range w-0 group-hover/vol:w-16 md:group-hover/vol:w-20 focus:w-20 transition-all duration-200 cursor-pointer"
            />
          </div>

          <span className="ml-1 text-xs md:text-sm font-medium tabular-nums text-white/90 whitespace-nowrap">
            {formatTime(current)} <span className="text-white/50">/ {formatTime(duration)}</span>
          </span>

          <div className="ml-auto flex items-center gap-0.5 md:gap-1">
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowSpeedMenu((v) => !v)}
                aria-label="Playback speed"
                title="Playback speed"
                className="flex items-center gap-1 p-2 rounded-full hover:bg-white/15 transition"
              >
                <Settings className="w-5 h-5" />
                {speed !== 1 && <span className="text-[11px] font-semibold">{speed}x</span>}
              </button>
              {showSpeedMenu && (
                <div className="absolute bottom-full right-0 mb-2 w-28 rounded-lg bg-black/90 backdrop-blur border border-white/10 py-1 shadow-xl">
                  <p className="px-3 py-1 text-[10px] uppercase tracking-wide text-white/50">Speed</p>
                  {SPEEDS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => applySpeed(s)}
                      className="flex items-center justify-between w-full px-3 py-1.5 text-xs hover:bg-white/10"
                    >
                      <span>{s === 1 ? 'Normal' : `${s}x`}</span>
                      {speed === s && <Check className="w-3.5 h-3.5" />}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {typeof document !== 'undefined' && document.pictureInPictureEnabled && (
              <button
                type="button"
                onClick={togglePip}
                aria-label="Picture in picture"
                title="Picture in picture"
                className="hidden md:inline-flex p-2 rounded-full hover:bg-white/15 transition"
              >
                <PictureInPicture2 className="w-5 h-5" />
              </button>
            )}

            <button
              type="button"
              onClick={toggleFullscreen}
              aria-label={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
              title="Fullscreen (f)"
              className="p-2 rounded-full hover:bg-white/15 transition"
            >
              {fullscreen ? <Minimize className="w-5 h-5" /> : <Maximize className="w-5 h-5" />}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * Unified video player for reading material videos.
 * - External providers (YouTube/Vimeo/Drive) render in a responsive iframe.
 * - Videos uploaded to our blob render in a custom player with skip controls,
 *   speed control and the download control hidden.
 */
const VideoPlayer = ({ url, fileUrl, title }) => {
  const { kind, src } = useMemo(() => resolveVideo(url, fileUrl), [url, fileUrl])

  if (kind === 'none') {
    return (
      <div className="card p-8 flex flex-col items-center justify-center text-center gap-2 text-surface-500">
        <AlertCircle className="w-8 h-8 text-amber-500" />
        <p>This video link could not be recognised.</p>
      </div>
    )
  }

  if (kind === 'file') {
    return (
      <div className="card overflow-hidden mb-6">
        <FileVideoPlayer src={src} title={title} />
      </div>
    )
  }

  return (
    <div className="card overflow-hidden mb-6">
      <div className="aspect-video bg-black">
        <iframe
          src={src}
          title={title}
          className="w-full h-full"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
        />
      </div>
    </div>
  )
}

export default VideoPlayer
