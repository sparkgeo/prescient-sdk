FROM golang:1.25
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
