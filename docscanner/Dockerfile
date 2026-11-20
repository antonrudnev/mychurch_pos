FROM golang:1.27-alpine AS builder

WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY main.go ./
COPY internal ./internal
RUN mkdir -p /out \
    && CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/docscanner .

FROM alpine:3.22

RUN apk add --no-cache ca-certificates tzdata \
    && mkdir -p /app/downloads

WORKDIR /app
COPY --from=builder /out/docscanner /usr/local/bin/docscanner

ENV PORT=8080 \
    DB_PATH=/app/db_volume/db.sqlite3 \
    DOWNLOAD_DIR=/app/downloads

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/docscanner"]
