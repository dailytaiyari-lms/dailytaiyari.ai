/**
 * Pyodide kernel — runs in a Web Worker.
 *
 * Executes student notebook code with real CPython (compiled to WebAssembly),
 * including the classical-ML stack (numpy, pandas, scipy, scikit-learn,
 * matplotlib). Running in a worker means a long `.fit()` never freezes the UI
 * and the main thread can hard-terminate a runaway cell.
 *
 * Protocol (main thread -> worker):
 *   {type:'init',      packages:[], files:[{filename,bytes}]}
 *   {type:'run',       id, code}                 // execute one cell
 *   {type:'runTests',  id, tests:[{id,name,source,points}]}
 *   {type:'reset'}                               // fresh namespace
 * Worker -> main thread:
 *   {type:'status', phase, detail}
 *   {type:'ready'}
 *   {type:'stream', name:'stdout'|'stderr', text}
 *   {type:'result', id, outputs:[...], error}
 *   {type:'tests',  id, results:[{id,passed,error}]}
 *   {type:'fatal',  id, error}
 */

/* eslint-env worker */
/* global loadPyodide */

const PYODIDE_VERSION = 'v0.28.3'
const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/`

let pyodide = null
let readyPromise = null
const loadedPackages = new Set()
// Names we already tried and could not resolve. Without this a package that
// isn't available in the browser kernel would be re-attempted (network and all)
// on every single cell run, which is what made every run look like a cold start.
const failedPackages = new Set()

const post = (msg) => self.postMessage(msg)

/**
 * Python-side execution harness.
 *
 * Runs a cell the way a notebook does — the final bare expression's value is
 * displayed — and captures stdout/stderr plus any matplotlib figures as
 * structured outputs. Kept in Python (rather than orchestrated from JS) so the
 * user's globals persist across cells exactly like a real kernel.
 */
const HARNESS = `
import ast, base64, io, sys, traceback, json

class _DTKernel:
    def __init__(self):
        self.ns = {'__name__': '__main__'}
        self.count = 0

    def reset(self):
        self.ns = {'__name__': '__main__'}
        self.count = 0

    def _figures(self):
        out = []
        try:
            import matplotlib.pyplot as plt
        except Exception:
            return out
        try:
            for num in plt.get_fignums():
                fig = plt.figure(num)
                buf = io.BytesIO()
                fig.savefig(buf, format='png', bbox_inches='tight', dpi=100)
                out.append({
                    'output_type': 'display_data',
                    'data': {'image/png': base64.b64encode(buf.getvalue()).decode('ascii')},
                })
            plt.close('all')
        except Exception:
            pass
        return out

    def _repr(self, value):
        if value is None:
            return None
        data = {}
        fn = getattr(value, '_repr_html_', None)
        if callable(fn):
            try:
                html = fn()
                if html:
                    data['text/html'] = html
            except Exception:
                pass
        try:
            data['text/plain'] = repr(value)
        except Exception:
            data['text/plain'] = '<unrepresentable object>'
        return {'output_type': 'execute_result', 'data': data}

    def run(self, code):
        self.count += 1
        outputs = []
        error = None
        stdout, stderr = io.StringIO(), io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout, stderr
        try:
            block = ast.parse(code, mode='exec')
            tail = None
            # Notebook semantics: echo the value of a trailing bare expression.
            if block.body and isinstance(block.body[-1], ast.Expr):
                tail = ast.Expression(block.body.pop().value)
            if block.body:
                exec(compile(block, '<cell>', 'exec'), self.ns)
            if tail is not None:
                value = eval(compile(tail, '<cell>', 'eval'), self.ns)
                rendered = self._repr(value)
                if rendered:
                    outputs.append(rendered)
        except SystemExit:
            pass
        except BaseException:
            etype, exc, tb = sys.exc_info()
            frames = traceback.extract_tb(tb)
            frames = [f for f in frames if f.filename == '<cell>'] or frames[1:]
            error = ''.join(
                traceback.format_list(frames) + traceback.format_exception_only(etype, exc)
            )
        finally:
            sys.stdout, sys.stderr = old_out, old_err

        text_out = stdout.getvalue()
        text_err = stderr.getvalue()
        if text_out:
            outputs.insert(0, {'output_type': 'stream', 'name': 'stdout', 'text': text_out})
        if text_err:
            outputs.append({'output_type': 'stream', 'name': 'stderr', 'text': text_err})
        outputs.extend(self._figures())
        if error:
            outputs.append({'output_type': 'error', 'traceback': error})
        return json.dumps({
            'outputs': outputs, 'error': error, 'execution_count': self.count,
        })

    def run_tests(self, tests_json):
        results = []
        for test in json.loads(tests_json):
            entry = {'id': test.get('id'), 'passed': False, 'error': ''}
            source = test.get('source') or ''
            if not source.strip():
                entry['passed'] = True
                results.append(entry)
                continue
            buf = io.StringIO()
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = buf, buf
            try:
                exec(compile(source, '<test>', 'exec'), self.ns)
                entry['passed'] = True
            except AssertionError as exc:
                entry['error'] = str(exc) or 'Assertion failed.'
            except BaseException as exc:
                entry['error'] = '%s: %s' % (type(exc).__name__, exc)
            finally:
                sys.stdout, sys.stderr = old_out, old_err
            results.append(entry)
        return json.dumps(results)

_dt_kernel = _DTKernel()
`

async function loadRequestedPackages(wanted) {
  const pending = wanted.filter((p) => p && !loadedPackages.has(p) && !failedPackages.has(p))
  if (!pending.length) return

  post({ type: 'status', phase: 'packages', detail: `Loading ${pending.join(', ')}…` })

  // The happy path: one batched download of everything that ships as a wheel.
  try {
    await pyodide.loadPackage(pending, { messageCallback: () => {}, errorCallback: () => {} })
    pending.forEach((p) => loadedPackages.add(p))
    return
  } catch {
    // One unresolvable name fails the whole batch, so fall back to per-package
    // loading — but only for the ones still genuinely missing.
  }

  let micropip = null
  try {
    await pyodide.loadPackage('micropip', { messageCallback: () => {} })
    micropip = pyodide.pyimport('micropip')
  } catch {
    micropip = null
  }

  for (const pkg of pending) {
    if (loadedPackages.has(pkg)) continue
    try {
      await pyodide.loadPackage(pkg, { messageCallback: () => {} })
      loadedPackages.add(pkg)
      continue
    } catch {
      // Not a bundled wheel — try PyPI.
    }
    try {
      if (!micropip) throw new Error('micropip unavailable')
      await micropip.install(pkg)
      loadedPackages.add(pkg)
    } catch {
      // Remember the miss so we never pay for this lookup again this session.
      failedPackages.add(pkg)
      post({
        type: 'status',
        phase: 'warning',
        detail: `Could not load "${pkg}" — it may not be available in the browser kernel.`,
      })
    }
  }
}

/**
 * Load whatever a cell's imports need, once.
 *
 * Students write `import pandas` whether or not an author declared it, so the
 * kernel resolves imports itself. It is skipped entirely once a cell's imports
 * are already satisfied, which is the common case after the first run.
 */
async function loadImportsFor(code) {
  if (!code || !/^\s*(import|from)\s/m.test(code)) return
  try {
    await pyodide.loadPackagesFromImports(code, { messageCallback: () => {} })
  } catch {
    // A missing third-party import surfaces as a normal Python ImportError,
    // which is far more useful to a student than a kernel-level failure.
  }
}

async function ensurePyodide(packages) {
  if (readyPromise) {
    await readyPromise
    await loadRequestedPackages(packages || [])
    return pyodide
  }
  readyPromise = (async () => {
    post({ type: 'status', phase: 'loading', detail: 'Starting Python…' })
    self.importScripts(`${PYODIDE_CDN}pyodide.js`)
    pyodide = await loadPyodide({ indexURL: PYODIDE_CDN })

    // Route Python's own stdout/stderr to the UI as a live stream.
    pyodide.setStdout({ batched: (text) => post({ type: 'stream', name: 'stdout', text }) })
    pyodide.setStderr({ batched: (text) => post({ type: 'stream', name: 'stderr', text }) })

    await loadRequestedPackages((packages || []).filter(Boolean))
    await pyodide.runPythonAsync(HARNESS)
    post({ type: 'status', phase: 'ready', detail: '' })
    return pyodide
  })()
  return readyPromise
}

function writeFiles(files) {
  if (!pyodide || !files?.length) return
  for (const file of files) {
    try {
      const name = String(file.filename || '').split('/').pop()
      if (!name) continue
      pyodide.FS.writeFile(name, new Uint8Array(file.bytes))
    } catch (err) {
      post({
        type: 'status',
        phase: 'warning',
        detail: `Could not load "${file.filename}": ${err?.message || err}`,
      })
    }
  }
}

self.onmessage = async (event) => {
  const msg = event.data || {}
  try {
    switch (msg.type) {
      case 'init': {
        await ensurePyodide(msg.packages)
        writeFiles(msg.files)
        // The id matters: the main thread resolves the caller's promise on it.
        // Without it `boot`/`restart` would wait forever.
        post({ type: 'ready', id: msg.id })
        break
      }
      case 'run': {
        await ensurePyodide(msg.packages)
        const code = msg.code || ''
        await loadImportsFor(code)
        post({ type: 'status', phase: 'ready', detail: '' })
        const raw = pyodide.runPython(`_dt_kernel.run(${JSON.stringify(code)})`)
        post({ type: 'result', id: msg.id, ...JSON.parse(raw) })
        break
      }
      case 'runTests': {
        await ensurePyodide(msg.packages)
        const raw = pyodide.runPython(
          `_dt_kernel.run_tests(${JSON.stringify(JSON.stringify(msg.tests || []))})`,
        )
        post({ type: 'tests', id: msg.id, results: JSON.parse(raw) })
        break
      }
      case 'reset': {
        if (pyodide) pyodide.runPython('_dt_kernel.reset()')
        post({ type: 'ready', id: msg.id })
        break
      }
      default:
        break
    }
  } catch (err) {
    post({ type: 'fatal', id: msg.id, error: String(err?.message || err) })
  }
}
