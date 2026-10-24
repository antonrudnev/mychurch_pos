FROM alpine:3.20

RUN apk add --no-cache openssl

COPY generate-default-cert.sh /usr/local/bin/generate-default-cert
RUN chmod +x /usr/local/bin/generate-default-cert

ENTRYPOINT ["/usr/local/bin/generate-default-cert"]
