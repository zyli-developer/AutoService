FROM node:20-slim AS build

ARG APP_NAME

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
COPY frontend/apps/${APP_NAME}/package.json apps/${APP_NAME}/package.json
COPY frontend/packages/ packages/

RUN pnpm install --frozen-lockfile

COPY frontend/tsconfig.base.json ./
COPY frontend/apps/${APP_NAME}/ apps/${APP_NAME}/
COPY frontend/packages/ packages/

RUN pnpm --filter @autoservice/${APP_NAME} build

FROM nginx:alpine

ARG APP_NAME

COPY --from=build /app/apps/${APP_NAME}/dist /usr/share/nginx/html
COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
