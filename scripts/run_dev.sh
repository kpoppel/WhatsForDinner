#!/bin/bash
set -e
npm ci
npm run build:client
uvicorn app.main:app --reload --host 0.0.0.0