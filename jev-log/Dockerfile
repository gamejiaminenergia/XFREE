FROM node:24-alpine
WORKDIR /app
RUN addgroup -S app && adduser -S app -G app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev || npm install --omit=dev --no-package-lock
COPY server.js ./
USER app
EXPOSE 3000
CMD ["node", "server.js"]
