# =============================================================================
# ARES AI — Frontend Dockerfile (multi-stage)
# =============================================================================

# ---- Build Stage ----
FROM node:22-alpine AS builder

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@9.12.3 --activate

# Cache bust 2
COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

# NEXT_PUBLIC_* vars are inlined at build time by Next.js — must be declared as ARG + ENV
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

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
