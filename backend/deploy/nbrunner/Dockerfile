# Sandboxed notebook grading runner.
#
# Executes untrusted student notebook code. Keep this image minimal: no app
# code, no credentials, no database driver, nothing that could be exfiltrated.
# The container is additionally run non-root, network-isolated and resource
# capped by docker-compose.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mpl \
    HOME=/tmp

# The scientific stack students get. Mirror this list with the Pyodide packages
# loaded in the browser kernel so a notebook behaves identically in both.
RUN pip install --no-cache-dir \
    "numpy==2.1.3" \
    "pandas==2.2.3" \
    "scipy==1.14.1" \
    "scikit-learn==1.5.2" \
    "matplotlib==3.9.2" \
    "sympy==1.13.3" \
    "statsmodels==0.14.4" \
    "networkx==3.4.2" \
    "pillow==11.0.0"

# Warm the matplotlib font cache at build time so the first graded submission
# isn't charged for it.
RUN python -c "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot" || true

RUN addgroup --system runner && adduser --system --group --home /tmp runner

COPY runner.py /srv/runner.py

USER runner
WORKDIR /tmp

EXPOSE 2100
CMD ["python", "/srv/runner.py"]
