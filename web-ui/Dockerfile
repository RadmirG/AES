FROM node:22-alpine AS build

WORKDIR /workspace/web-ui
RUN corepack enable
COPY web-ui/package.json web-ui/pnpm-lock.yaml web-ui/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web-ui/ ./
COPY examples/ /workspace/examples/
RUN pnpm run build

FROM nginx:1.27-alpine

COPY web-ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/web-ui/dist /usr/share/nginx/html

EXPOSE 8080
