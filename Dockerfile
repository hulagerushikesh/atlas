# Atlas API image — Cloud Run and docker-compose share it.
#
# Two things matter for a small always-scaled-to-zero service:
#   1. No dev extras (pytest, ruff, mypy) — smaller image, faster cold start.
#   2. The cross-encoder weights are baked in at build time, so a fresh
#      instance never downloads from Hugging Face on its first request.
# torch (CPU) is still the bulk of the image; RERANKER_ENABLED=false skips
# loading it at runtime if a deploy ever needs to be lighter.
#
# Ownership is set as files are created, never afterwards. A trailing
# `chown -R atlasuser /app /opt/hf` cost 81.9 MB of the 554.6 MB image
# measured on `bda328e`: chown rewrites every inode it touches, so the whole
# baked-weights tree was copied into a second layer and shipped twice. The
# user is therefore created before anything it owns, `COPY --chown` sets the
# owner in the copy itself, and the weights are downloaded as the runtime
# user into a directory already assigned to it.

FROM python:3.11-slim

WORKDIR /app

# Before any layer whose files it needs to own, so nothing has to be
# re-owned later.
RUN adduser --disabled-password --gecos "" atlasuser

RUN pip install --no-cache-dir uv

# Dependency layer first so code edits do not reinstall torch.
COPY pyproject.toml README.md ./
# torch first, from the CPU-only index (the PyPI wheel drags in CUDA, ~2 GB);
# the second install then sees torch satisfied and pulls the rest from PyPI.
RUN uv pip install --system --no-cache \
       --index-url https://download.pytorch.org/whl/cpu "torch>=2.3.0" \
    && mkdir -p src/atlas && touch src/atlas/__init__.py \
    && uv pip install --system --no-cache -e ".[gcp]"

# Bake the reranker weights into the image (~108 MB compressed, measured on
# bda328e — the "~90 MB" this comment used to claim was never checked).
ENV HF_HOME=/opt/hf \
    RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RUN mkdir -p /opt/hf /app/data && chown atlasuser:atlasuser /opt/hf /app /app/data
USER atlasuser
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('${RERANKER_MODEL}')"

COPY --chown=atlasuser:atlasuser src/ src/
# BM25 index for the demo corpus (~3.5 MB per namespace). Baking it in keeps
# the deploy to one artifact; the dense side of the same corpus lives in
# Qdrant Cloud. Re-ingest locally and rebuild to change the corpus.
COPY --chown=atlasuser:atlasuser data/index/ data/index/

# Cloud Run injects PORT; compose leaves it unset and gets 8010.
ENV PORT=8010 \
    HF_HUB_OFFLINE=1
EXPOSE 8010

CMD ["sh", "-c", "uvicorn atlas.api.asgi:app --host 0.0.0.0 --port ${PORT}"]
