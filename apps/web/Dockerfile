FROM node:22-alpine AS build
WORKDIR /app
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web ./
ARG NEXT_PUBLIC_API_URL=/robincop-api
ARG NEXT_PUBLIC_SITE_URL=https://robincop.com
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL}
RUN npm run build
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
CMD ["npm", "run", "start"]
