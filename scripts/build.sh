#!/bin/bash
tag=${1:-latest}
if [ "$1" == "" ]; then
  echo "Usage: $0 <tag: v1.0..0>"
  echo "Default tag is 'latest'."
  echo "Remember to update the version in the .env file as well."
fi
docker build -t whatsfordinner:$tag -f docker/Dockerfile .