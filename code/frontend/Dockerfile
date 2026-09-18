FROM node:22-alpine

WORKDIR /app

# Copy the lockfile too, and install from it, so every machine and this image all run
# byte-identical dependency versions.
COPY package.json package-lock.json ./

RUN npm ci

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
