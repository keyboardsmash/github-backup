# github-backup

Backup Github repos to GCP as bare repos.

## Requirements

- A github account with access rights to all repos
  - An api token for said account stored as a GCP secret.
- A GCP service account
- A GCP bucket to store backups
- A Pub/Sub Topic to publish names of repos
- Slack Webhooks
  - Success_url, will have A LOT of output
  - Failure_url, will only output failures

---

## Configuration

All config is done in the **config.yaml** file found in the get_repos_function subdir. These values are then passed on to the backu repo function.

All secrets used are stored as GCP Secrets.

---

## Bucket

Create one:
<https://console.cloud.google.com/storage/browser?>

---

## Pub/Sub

Get repos function tries to create the topic before publishing a message to it, if the topic exists it will pass and publish the message.

Read below for the needed permissions.

---

## Service account and IAM role

A service account with the following permissions are needed

- storage.buckets.get
- storage.objects.get
- storage.objects.create
- storage.objects.list

If a custom role is needed you can create it by running:

```bash
gcloud iam roles create github-backup-role --project jamestown-208212 --file iam-github-backup-role.yaml


Created role [github_backup_role].
description: Role used to create backups from github
etag: BwWhmYCAoYU=
includedPermissions:
- storage.buckets.get
- storage.objects.create
- storage.objects.get
- storage.objects.list
name: projects/jamestown-208212/roles/github_backup_role
stage: GA
title: GitHub Backup Role
```

If needed limit access to the bucket by adding a condition for the Service Account of type:

Name -> Starts with -> projects/_/buckets/<bucket_name>

The Service Account also needs the **Pub/Sub Editor** in order to create and publish to the Pub/Sub Topic.

IAM page: <https://console.cloud.google.com/iam-admin/iam?>

---

## Secret

We use a secret called "gh_api_token" to hold the Github Access Token needed to both get the repos and to git clone each repository.

First we create it. Then we need to bind it to our service account in order to allow or function to retrieve it.

### Creating the secret

```bash
echo -n "xxxxAPITOKENxxxxxxxxxxxxxxxxx" | \
    gcloud secrets create gh_api_token \
      --data-file=- \
      --replication-policy automatic
```

### Bind the secret to the service account

```bash
gcloud secrets add-iam-policy-binding gh_api_token \
    --role roles/secretmanager.secretAccessor \
    --member serviceAccount:github-backups@jamestown-208212.iam.gserviceaccount.com


Updated IAM policy for secret [my-secret].
bindings:
- members:
  - serviceAccount:github-backups@jamestown-208212.iam.gserviceaccount.com
  role: roles/secretmanager.secretAccessor
etag: BwWhdRiU_ms=
version: 1
```

### Adding a new version of the secret

List versions of the secret

```bash
gcloud secrets versions list gh_api_token

NAME  STATE      CREATED              DESTROYED
1     enabled    2020-03-22T18:08:13  -
```

Add the new version

```bash
echo -n "newAPITOKENxxxxxxxx" | \
    gcloud secrets versions add gh_api_token \
      --data-file=-

Created version [2] of the secret [gh_api_token].
```

ATTENTION: Note the -n for the echo command, without this a newline character may be added that will break our code since it does not check the token for anything that is not supposed to be there.

```ErrorExample
File "/opt/python3.7/lib/python3.7/http/client.py", line 1230, in putheader raise ValueError('Invalid header value %r' % (values[i],)) ValueError: Invalid header value b'token xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n'
```

We now have two versions.

```bash
gcloud secrets versions list gh_api_token

NAME  STATE      CREATED              DESTROYED
2     enabled    2020-04-16T08:50:28  -
1     enabled    2020-03-22T18:08:13  -
```

### Removing a version of the secret

```bash
gcloud secrets versions destroy 1 --secret=gh_api_token

You are about to destroy version [1] of the secret [gh_api_token].
This action cannot be reversed.

Do you want to continue (Y/n)?

Destroyed version [1] of the secret [gh_api_token].
```

Previous version is now destroyed and a marker is set for when it was destroyed.

```bash
gcloud secrets versions list gh_api_token
NAME  STATE      CREATED              DESTROYED
2     enabled    2020-04-16T08:50:28  -
1     destroyed  2020-03-22T18:08:13  2020-04-16T08:55:06
```

---

## Deploying the functions to GCP

Either run the **deploy.sh** script or run the commands manually:

### Get Repos Function

```bash
gcloud functions deploy \
    --service-account=github-backups@jamestown-208212.iam.gserviceaccount.com \
    --region=europe-west3 \
    --runtime=python37 \
    --trigger-http \
    --max-instances=1 \
    --memory=512M \
    --source get_repos_function \
    get_repos
```

### Backup Repo Function

```bash
gcloud functions deploy \
    --service-account=github-backups@jamestown-208212.iam.gserviceaccount.com \
    --region=europe-west3 \
    --runtime=python37 \
    --trigger-topic=github-backups \
    --max-instances=1 \
    --memory=1G \
    --source backup_repo_function \
    backup_repo

```

Take a look at the webconsole: <https://console.cloud.google.com/functions/list>

---

## Scheduler

This scheduler runs a cronjob at 3:00 AM ETC, every night.

```bash
gcloud scheduler jobs create http github-backup-job --schedule "0 3 * * *" --uri "https://<account>.cloudfunctions.net/get_repos" --http-method POST
```

More info here: <https://console.cloud.google.com/cloudscheduler>

---

## Slack Notifications

The script is setup to use two slack webhooks, one for success the other in case of failure. These are configured in the config.yaml
file as:

- slack_success_url
- slack_failure_url

You can set these up towards different channels since the scripts "should" not fail (in a perfect world) but will return message of success all the time, one for each repo which may be tiresome quite fast if it's sent to your normal monitoring channel. Failure should point to the normal/frequently used monitoring channel.

---

## Local Development

In order to develop locally you will need to install python3 with pip, and then install the functions-framework

```bash
pip3 install functions-framework
```

and then run:

```bash
functions-framework --target <function_name_in_main.py> --debug --port <8080 or whatever port not used>
```
---

## Restoring a backup

Using HSS as example.

Create a folder on your disk:

```bash
mkdir somefolder/
```

Save the zip to the folder and extract it:

```bash
unzip hss.<datecode>.zip
```

You should now have a file structure should look something like this:

```bash
➜  HSS_bare git:(master) ls -lash
total 32
-rw-r--r--   1 user  9999999111    23B  1 Apr 14:00 HEAD
-rw-r--r--   1 user  9999999111   223B  1 Apr 14:00 config
-rw-r--r--   1 user  9999999111    73B  1 Apr 13:59 description
drwxr-xr-x  13 user  9999999111   416B  1 Apr 13:59 hooks
drwxr-xr-x   3 user  9999999111    96B  1 Apr 13:59 info
drwxr-xr-x   4 user  9999999111   128B  1 Apr 13:59 objects
-rw-r--r--   1 user  9999999111   105B  1 Apr 14:00 packed-refs
drwxr-xr-x   4 user  9999999111   128B  1 Apr 13:59 refs
➜  HSS_bare git:(master)
```

### Remote restore to github (or other place)

from within the bare repo run:

```bash
git push --mirror https://github.org/troperty/<name_of_repo>.git
```

Done. You should now see it as normal with all branches tags etc.

### Local restore to working copy

```bash
git clone <path_to_HSS_bare_repository_from_zip> HSS
```

we now have access to a working copy of the repo:

```bash
➜  HSS git:(master) ll
total 8
-rw-r--r--   1 user  9999999111    25B  1 Apr 14:01 README.md
drwxr-xr-x  28 user  9999999111   896B  1 Apr 14:02 Sport
➜  HSS git:(master)
```

---

## Misc

Using Pub/sub Topics to trigger the job we are guaranteed that each backup repo job will run at least once, however this does not mean it will not run more than once. Leading to multiple copies made of the same archive, a minute or so apart. 
