FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install uv

# Copy dependency spec first for layer caching
COPY pyproject.toml .
COPY src/ src/

# Install the package and all dependencies into the system Python
RUN uv pip install --system -e ".[dev]"

EXPOSE 8000

CMD ["uvicorn", "atlas.api.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
