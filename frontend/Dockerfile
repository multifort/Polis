ARG NODE_IMAGE=node:22-alpine

FROM ${NODE_IMAGE} AS deps

WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.28.2 --activate

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM deps AS builder

ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}

COPY . .
RUN pnpm build
RUN pnpm prune --prod

FROM ${NODE_IMAGE} AS runtime

ENV NODE_ENV=production \
    PORT=3000

WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.28.2 --activate

COPY --from=builder /app/package.json /app/pnpm-lock.yaml ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.mjs ./next.config.mjs

EXPOSE 3000

CMD ["pnpm", "start"]
