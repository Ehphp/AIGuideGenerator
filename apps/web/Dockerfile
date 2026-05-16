FROM node:20-alpine

WORKDIR /app

# Install deps first for layer caching.
COPY package.json ./
RUN npm install --no-audit --no-fund

# Source is bind-mounted in dev, copied here for image self-sufficiency.
COPY . /app

EXPOSE 3000

CMD ["npm", "run", "dev"]
