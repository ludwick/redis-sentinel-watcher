#!/usr/bin/env bash

set -e

# This is a very simple script to build and push this container.
# It assumes you have docker installed and your gcloud creds to
# push to the container registry are setup right.

if [ ! -e project.txt ]; then
  echo "need google cloud project name"
  exit 1
fi

if [ ! -e versino.txt ]; then
  echo "need version file"
  exit 1
fi


typeset project=$(cat project.txt)
typeset version=$(cat version.txt)
typeset tag="gcr.io/$project/redis-sentinel-watcher:$version"
docker build --tag="$tag" .
gcloud docker -- push "$tag"
echo "Pushed build $tag."
