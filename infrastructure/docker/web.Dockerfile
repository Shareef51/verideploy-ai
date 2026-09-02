ARG BASE_IMAGE=node:22-alpine
FROM ${BASE_IMAGE}
WORKDIR /app
RUN corepack enable
COPY . .
RUN pnpm install --frozen-lockfile && pnpm --filter @verideploy/web build
EXPOSE 3000
CMD ["pnpm","--filter","@verideploy/web","start"]
