#!/bin/sh
set -eu

REPO_DIR="${REPO_DIR:-/repo}"
BRANCH="${TARGET_BRANCH:-main}"

cd "$REPO_DIR"

git fetch origin "$BRANCH"
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

docker compose up -d --build app
