# syntax=docker/dockerfile:1

# Vite's dev server on :3000, with the source bind-mounted by docker-compose. Production is
# the Cloudflare Worker in wrangler.jsonc, so there's no prod image.

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
