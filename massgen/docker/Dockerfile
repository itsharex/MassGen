# MassGen MCP Runtime Environment
# Provides isolated execution environment for command execution with Docker isolation
# Base image: Python 3.11 slim for balance of features and size

FROM python:3.11-slim

# Metadata
LABEL maintainer="MassGen Team"
LABEL description="Isolated runtime environment for MassGen command execution"
LABEL version="1.0.0"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies
# - git: Version control operations
# - curl: HTTP operations and downloads
# - build-essential: Compiling Python packages with C extensions
# - ripgrep: Fast text search (REQUIRED for filesystem-first mode)
# - unzip: For extracting ast-grep binary
# - ffmpeg: Video encoding (for VHS terminal recording)
# - golang-go: Go runtime (for VHS installation)
# - wget: For downloading ttyd binary
# - jq: JSON processing in shell scripts
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    build-essential \
    ripgrep \
    unzip \
    ffmpeg \
    golang-go \
    wget \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install document processing tools for skills (DOCX, PPTX, XLSX, PDF)
# - libreoffice: Convert documents to PDF (soffice --headless --convert-to pdf)
# - poppler-utils: PDF to images (pdftoppm), text extraction (pdftotext)
# - pandoc: Document format conversions (optional, for markdown)
# - qpdf: PDF manipulation and optimization
# Note: LibreOffice is large (~500MB) but essential for accurate document rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    poppler-utils \
    pandoc \
    qpdf \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20.x (LTS) for JavaScript execution
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install ast-grep for structural code search (filesystem-first mode)
# Using pip (avoids conflict with system 'sg' command that npm version creates)
RUN pip install --no-cache-dir ast-grep-cli

# Install openskills CLI for skills management
# Anthropic skills are installed manually beforehand and added as a volume at runtime
# Also install any agent CLI tools
RUN npm install -g openskills @openai/codex @google/gemini-cli agent-browser

# Fix MCP filesystem server schema issue
# The latest @modelcontextprotocol/server-filesystem (2025.8.21) has a Zod version conflict:
# - @modelcontextprotocol/sdk uses Zod 3.25.76
# - zod-to-json-schema@3.25.0 expects Zod 4.x
# This causes schemas to return only {"$schema": " "http://json-schema.org/draft-07/schema#"}
# instead of full parameter definitions, so the agents cannot generate correct tool calls.
# Fix: Downgrade zod-to-json-schema to 3.23.0 which works with Zod 3.
# When in Docker, the filesystem npm is used instead of through npx.
RUN npm install -g @modelcontextprotocol/server-filesystem && \
    cd $(npm root -g)/@modelcontextprotocol/server-filesystem && \
    npm uninstall zod-to-json-schema && \
    npm install zod-to-json-schema@3.23.0

# Install semtools for semantic search (optional semtools skills)
RUN npm install -g @llamaindex/semtools

# Install GitHub CLI for authenticated git operations
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Create application directory
WORKDIR /app

# Install Python dependencies
# Core requirements: pytest for testing, python-dotenv for .env file support
# Common tools: requests, pandas, numpy for typical data science tasks
# Custom tool dependencies (massgen/tool/):
# - openai, anthropic, google-genai: AI SDK packages for multimodal/computer use tools
# - Pillow: Image processing for _multimodal_tools
# - opencv-python-headless: Video processing for _video_tools (headless = no GUI deps)
# - playwright, crawl4ai: Browser automation and web scraping for _browser_automation/_web_tools
# Skills dependencies:
# - pypdf, pdfplumber, reportlab: PDF skill (parsing, extraction, creation)
# - defusedxml: Secure XML parsing for DOCX/PPTX skills
# - imageio: GIF creation for slack-gif-creator skill
# Note: fastmcp will be installed later with MassGen package
RUN pip install --no-cache-dir \
    'pytest>=7.0.0' \
    'python-dotenv>=1.0.0' \
    'requests>=2.31.0' \
    'numpy>=1.24.0' \
    'pandas>=2.0.0' \
    'openai>=1.0.0' \
    'anthropic>=0.18.0' \
    'google-genai>=0.2.0' \
    'Pillow>=10.0.0' \
    'opencv-python-headless>=4.8.0' \
    'playwright>=1.40.0' \
    'crawl4ai>=0.2.0' \
    'pypdf>=3.0.0' \
    'pdfplumber>=0.10.0' \
    'reportlab>=4.0.0' \
    'defusedxml>=0.7.0' \
    'imageio>=2.30.0'

# Install Playwright system dependencies (requires root)
# This installs fonts, libraries needed by browsers
RUN python -m playwright install-deps

# Create workspace and context directories
# These will be mounted as volumes at runtime
RUN mkdir -p /workspace /context /temp_workspaces

# Set workspace as default working directory
WORKDIR /workspace

# Setup non-root user for security
# Commands run as this user to prevent privilege escalation
RUN useradd -m -u 1000 -s /bin/bash massgen && \
    chown -R massgen:massgen /workspace /context /temp_workspaces /app

# Switch to non-root user
USER massgen

# Keep Playwright browser binaries in the image-owned cache directory.
ENV PLAYWRIGHT_BROWSERS_PATH="/home/massgen/.cache/ms-playwright"

# Install Playwright browser binaries as massgen user
# This puts browsers in /home/massgen/.cache/ms-playwright/ where the user can access them
RUN python -m playwright install

# Install Agent Browser browser bundle and default skill.
RUN agent-browser install && \
    cd /home/massgen && \
    openskills install vercel-labs/agent-browser --universal -y

# Install uv (modern Python package installer for optional serena skill)
# Enables uvx for running tools like serena on-demand without permanent installation
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/home/massgen/.local/bin:${PATH}"

# Install VHS terminal recorder (for terminal evaluation/recording)
# https://github.com/charmbracelet/vhs
RUN go install github.com/charmbracelet/vhs@latest
ENV PATH="/home/massgen/go/bin:${PATH}"

# Install ttyd for VHS SSH mode (VHS's preferred recording mode)
# https://github.com/tsl0922/ttyd/releases/tag/1.7.7
# ttyd is lightweight (~1.3MB) and more reliable than browser mode for VHS
USER root
RUN ARCH=$(uname -m) && \
    TTYD_VERSION="1.7.7" && \
    if [ "$ARCH" = "x86_64" ]; then \
        TTYD_ARCH="x86_64"; \
    elif [ "$ARCH" = "aarch64" ]; then \
        TTYD_ARCH="aarch64"; \
    elif [ "$ARCH" = "armv7l" ]; then \
        TTYD_ARCH="armhf"; \
    elif [ "$ARCH" = "i686" ]; then \
        TTYD_ARCH="i686"; \
    else \
        echo "Unsupported architecture: $ARCH" && exit 1; \
    fi && \
    wget -q "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${TTYD_ARCH}" -O /usr/local/bin/ttyd && \
    chmod +x /usr/local/bin/ttyd
USER massgen
# Install MassGen package from source
# This provides MCP server modules and fastmcp CLI needed for agent operation
# Installs from the git repository being built (not PyPI) to ensure version sync
USER root
COPY --chown=massgen:massgen . /tmp/massgen-build
WORKDIR /tmp/massgen-build
RUN pip install --no-cache-dir . && \
    cd /workspace && \
    rm -rf /tmp/massgen-build
WORKDIR /workspace
USER massgen

# Default command: Keep container running (overridden at runtime)
CMD ["tail", "-f", "/dev/null"]
