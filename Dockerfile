FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install Node.js 20 for the WhatsApp bridge + system libs for headless Chromium (patchright)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg git \
        libgbm1 libxkbcommon0 libxshmfence1 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libxcomposite1 libxdamage1 libxrandr2 libpango-1.0-0 \
        libasound2 libnspr4 libnss3 libx11-xcb1 && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get purge -y gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p velo bridge && touch velo/__init__.py && \
    uv pip install --system --no-cache . && \
    rm -rf velo bridge

# Copy the full source and install
COPY velo/ velo/
COPY bridge/ bridge/
RUN uv pip install --system --no-cache .

# Build the WhatsApp bridge
WORKDIR /app/bridge
RUN npm install && npm run build
WORKDIR /app

# Velo source for Volos agent exploration
COPY . /opt/velo-src

# Create config directory
RUN mkdir -p /root/.velo

# Gateway default port
EXPOSE 18790

# Entrypoint: inject Swarm secrets into config, then exec velo
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gateway"]
