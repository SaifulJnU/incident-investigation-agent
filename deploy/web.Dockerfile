FROM node:22-alpine AS build

WORKDIR /src
COPY web/package.json ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM nginx:1.27-alpine

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
