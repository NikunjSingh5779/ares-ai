# =============================================================================
# ARES AI — Frontend Dockerfile (multi-stage)
# =============================================================================

# ---- Build Stage ----
FROM node:22-alpine AS builder

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

# ---- Runtime Stage ----
FROM node:22-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production

# Copy built output
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./package.json

# Copy standalone server (Next.js outputFileTracing)
COPY --from=builder /app/.next/standalone ./

EXPOSE 3000

CMD ["node", "server.js"]
