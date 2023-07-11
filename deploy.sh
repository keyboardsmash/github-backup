#!/bin/bash
# This script will deploy or update our functions

SERVICE_ACCOUNT="github-backups@<account>.iam.gserviceaccount.com"
REGION="europe-west3"
RUNTIME="python37"
MAX_INSTANCES="1"
TOPIC="github-backups"

echo -e "\nDeploying get_repos function\n"
gcloud functions deploy --service-account=$SERVICE_ACCOUNT --region=$REGION --runtime=$RUNTIME --trigger-http --max-instances=$MAX_INSTANCES --timeout=180 --memory=512M --source=get_repos_function get_repos

echo -e "\nDeploying backup_repo function\n"
gcloud functions deploy --service-account=$SERVICE_ACCOUNT --region=$REGION --runtime=$RUNTIME --trigger-topic=$TOPIC --max-instances=$MAX_INSTANCES --timeout=90 --memory=2G --source=backup_repo_function backup_repo