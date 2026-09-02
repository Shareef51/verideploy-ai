ARG BASE_IMAGE=node:22-alpine
FROM ${BASE_IMAGE}
WORKDIR /app
RUN corepack enable
COPY . .
RUN pnpm install --frozen-lockfile && pnpm --filter @verideploy/gateway build
EXPOSE 4000
CMD ["pnpm","--filter","@verideploy/gateway","start"]
