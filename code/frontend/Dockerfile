# syntax=docker/dockerfile:1

# Two targets from one file:
#
#   dev  -> Vite's dev server on :3000, source bind-mounted by docker-compose
#   prod -> `vite build` output served by nginx on :8080   (what CD pushes)
#
# The prod image carries no node_modules and no Node runtime -- just static files and
# nginx, which is why it's ~50 MB instead of ~400 MB.

FROM node:22-alpine AS deps

WORKDIR /app

# Copy the lockfile too, and install from it, so every machine and this image all run
# byte-identical dependency versions.
COPY package.json package-lock.json ./

RUN npm ci


FROM deps AS dev

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]


FROM deps AS build

COPY . .

RUN npm run build


FROM nginx:1.27-alpine AS prod

# The official image runs envsubst over everything in templates/ at startup. The filter
# restricts that to API_ORIGIN, so nginx's own $host / $remote_addr survive untouched.
ENV NGINX_ENVSUBST_FILTER="^(API_ORIGIN|PORT)$" \
    API_ORIGIN="http://backend:5000" \
    PORT=8080

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

# 8080, not 80: an unprivileged port, so the container can drop root if a host asks it to.
EXPOSE 8080
