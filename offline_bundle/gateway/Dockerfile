FROM nginx:alpine

RUN apk add --no-cache curl openssl

COPY gateway/nginx.conf /etc/nginx/conf.d/default.conf
COPY gateway/static/ /usr/share/nginx/html/
COPY gateway/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD curl -fsS http://localhost:80/nginx-health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
