FROM node:22.14.0-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
COPY docker/nginx.conf ./nginx.conf
ARG API_UPSTREAM=api:8000
RUN sed -i "s|http://api:8000|http://${API_UPSTREAM}|g" nginx.conf
FROM nginxinc/nginx-unprivileged:1.28-alpine
COPY --from=build /app/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
USER 101
