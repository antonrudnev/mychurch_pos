FROM ghcr.io/acmesh-official/acme.sh:latest

USER root

RUN apk add --no-cache docker-cli

COPY issue-dynu-cert.sh /usr/local/bin/issue-dynu-cert.sh
RUN chmod +x /usr/local/bin/issue-dynu-cert.sh
