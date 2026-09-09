import multiprocessing

bind = "0.0.0.0:8000"
workers = multiprocessing.cpu_count() * 2 + 1
# Threaded workers: coding submissions block on Piston HTTP calls (I/O-bound),
# so letting each worker serve several requests via threads keeps the site
# responsive under submission bursts instead of pinning one whole worker per
# in-flight submission. threads>1 requires the gthread worker class.
worker_class = "gthread"
threads = 4
loglevel = "info"
accesslog = "-"
errorlog = "-"
# Must stay ABOVE settings.AI_READ_TIMEOUT (default 90s), so a slow AI provider
# hits its own timeout and returns a readable error rather than having the
# worker killed out from under the request.
timeout = 120
keepalive = 5
capture_output = True
enable_stdio_inheritance = True
