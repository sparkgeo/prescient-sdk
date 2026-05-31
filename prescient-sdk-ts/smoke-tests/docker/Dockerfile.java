FROM maven:3.9-eclipse-temurin-21
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
