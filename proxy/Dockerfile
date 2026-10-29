# Xyberah HTTPS frontend proxy: builds the React app, serves it over TLS via Caddy.
FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM caddy:2.10-alpine
COPY --from=build /app/dist /srv
COPY proxy/Caddyfile /etc/caddy/Caddyfile
COPY proxy/entrypoint.sh /usr/local/bin/proxy-entrypoint
RUN chmod +x /usr/local/bin/proxy-entrypoint && mkdir -p /etc/caddy /certs/custom
ENV BACKEND_UPSTREAM=backend:8000
EXPOSE 443
ENTRYPOINT ["/usr/local/bin/proxy-entrypoint"]
