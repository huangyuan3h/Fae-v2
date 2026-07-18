# Placeholder UI until Phase 1.4 ships the real Next.js app.
FROM nginx:1.27-alpine

COPY deploy/docker/ui-placeholder/index.html /usr/share/nginx/html/index.html
COPY deploy/docker/ui-placeholder/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:3000/healthz || exit 1
