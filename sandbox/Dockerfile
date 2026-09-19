# Minimal, dependency-light image for the Alpharouter code interpreter sandbox.
# Contains NO application code and NO secrets. Executed with:
#   --network none --read-only --tmpfs /tmp --user 65534:65534
#   --cap-drop ALL --security-opt no-new-privileges --rm -i
FROM python:3.12-slim

# Unicode font used by ReportLab for multilingual PDF artifacts.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Data libraries commonly used by the interpreter. Kept small on purpose;
# every version (transitive ones included) is pinned in requirements.txt.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Runner lives at a fixed path; workspace is a writable tmpfs at runtime.
COPY runner.py /opt/runner.py

# Drop privileges by default (caller also passes --user for defense in depth).
USER 65534:65534

ENTRYPOINT ["python", "-I", "/opt/runner.py"]
