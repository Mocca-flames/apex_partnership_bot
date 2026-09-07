FROM node:22-slim

WORKDIR /app

COPY package*.json ./

RUN npm install --prefer-offline --no-audit

COPY src ./src

RUN mkdir -p /app/sessions

EXPOSE 3000

CMD ["npm", "start"]
