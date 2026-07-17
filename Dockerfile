FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy dependency spec first for layer caching
COPY pyproject.toml .
COPY src/ src/

# Install the package (without dev extras for production)
RUN uv pip install --system -e "."

# Non-root user for production safety
RUN adduser --disabled-password --gecos "" atlasuser
USER atlasuser

EXPOSE 8010

CMD ["uvicorn", "atlas.api.asgi:app", "--host", "0.0.0.0", "--port", "8010"]
