# Minimal, dependency-light image for the Alpharouter code interpreter sandbox.
# Contains NO application code and NO secrets. Executed with:
#   --network none --read-only --tmpfs /tmp --user 65534:65534
#   --cap-drop ALL --security-opt no-new-privileges --rm -i
FROM python:3.12-slim

# Data libraries commonly used by the interpreter. Kept small on purpose.
RUN pip install --no-cache-dir \
      pandas==2.2.3 \
      numpy==2.1.3

# Runner lives at a fixed path; workspace is a writable tmpfs at runtime.
COPY runner.py /opt/runner.py

# Drop privileges by default (caller also passes --user for defense in depth).
USER 65534:65534

ENTRYPOINT ["python", "-I", "/opt/runner.py"]
