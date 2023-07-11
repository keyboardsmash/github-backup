import json, os, requests, sys, shutil, getopt, logging, base64
from git import Repo, Git
from google.cloud import storage
from google.cloud import secretmanager
from datetime import datetime

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(message)s - %(levelname)s')

# ------------------------------------------------------------------------

def get_secret(secret_name, project_id):
    """
        Returns the value of a secret from google secrets manager. 
    """
    client = secretmanager.SecretManagerServiceClient()
    resource_name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(resource_name)
    secret_string = response.payload.data.decode('UTF-8')
    return secret_string

# ------------------------------------------------------------------------

def slack_message(endpoint, message):
    """
        Sends message to a slack channel using a webhook.
    """
    slack_data = {'text': message}

    response = requests.post(
        endpoint, data=json.dumps(slack_data),
        headers={'Content-Type': 'application/json'}
    )
    if response.status_code != 200:
        raise ValueError(
            'Request to slack returned an error %s, the response is:\n%s'
            % (response.status_code, response.text)
        )

# ------------------------------------------------------------------------

def alert_failure(message, repository, endpoint):
    """ 
        Sends a message to slack, logs and quits
    """
    msg = 'BACKUP FAILED for repository ' + repository + '. ERROR: ' + message
    slack_message(endpoint, msg)
    logging.error(msg)
    sys.exit(99)

# ------------------------------------------------------------------------

def alert_success(repository, endpoint):
    """
        sends a successmessage
    """
    message = 'Backup of repository ' + repository + ' completed.'
    logging.info(message)
    slack_message(endpoint, message)
    
# ------------------------------------------------------------------------

def backup_repo(event, context):
    conf = json.loads(base64.b64decode(event['data']))
    required = ['bucket_name', 'organization', 'project', 'repository', 'secret_name', 'slack_failure_url', 'slack_success_url']

    # Check that we get all required variables
    for value in required:
        if value not in conf:
            logging.error('Missing variable ' + value)
            sys.exit(98)
    
    bucket_name         = conf['bucket_name']
    organization        = conf['organization']
    project             = conf['project']
    repository          = conf['repository']
    secret_name         = conf['secret_name']
    slack_failure_url   = conf['slack_failure_url']
    slack_success_url   = conf['slack_success_url']
    temporary_root      = '/tmp/gh_backup/'
    temporary_folder    = temporary_root + repository + '/'

    # output the repositoryname to make it easier to spot error in GCP logs
    logging.info(repository)

    # get access token
    access_token = get_secret(secret_name=secret_name, project_id=project)

    HTTPS_REMOTE_URL    = 'https://' + access_token + ':x-oauth-basic@github.com/' + organization + '/' + repository
    timestamp           = datetime.now().strftime('%Y%m%d_%H.%M.%S')
    today               = datetime.now().strftime('%Y%m%d')
    backup_archive_name = repository + '.' + timestamp

    # make sure our temp is empty
    try:
        shutil.rmtree(temporary_folder)
    except:
        pass

    # ------------------------------------------------------
    logging.debug('Cloning repository: ' + repository)
    try:
        Repo.clone_from(HTTPS_REMOTE_URL, os.path.join(temporary_folder, repository), bare=True)
    except: 
        alert_failure('Could not clone repository', repository, slack_failure_url)

    # check that the repo is not to large to handle. We only have 2GB of memory of which the tmpfs counts, 
    # we need to reserve at least 200 mb for our function to run. A limit of 900MB is imposed. 
    
    limit = 900
    folder_size = 0
    for (path, dirs, files) in os.walk(os.path.join(temporary_folder, repository)):
        for file in files:
            folder_size += os.path.getsize(os.path.join(path, file))

    totsize = int(folder_size/(1024*1024.0))

    if totsize > limit:
        alert_failure('The size of the bare repository is too large: ' + str(totsize) + 'MB, function cannot handle directory sizes over ' + str(limit) + ' MB.', repository, slack_failure_url)

    # ------------------------------------------------------
    logging.debug('Creating archive: ' + backup_archive_name) 
    try:
        shutil.make_archive(os.path.join(temporary_folder, backup_archive_name), 'zip', os.path.join(temporary_folder, repository))
    except FileNotFoundError:
        alert_failure('Creating archive' + repository, slack_failure_url)

    # ------------------------------------------------------
    storage_client = storage.Client()
    bucket         = storage_client.get_bucket(bucket_name) 
    upload_file    = backup_archive_name + '.zip'
    blob_path      = today + '/' + upload_file
    logging.debug('Uploading archive:' + upload_file + ' --> ' + bucket_name + '/' + blob_path)
    
    blob = bucket.blob(blob_path)
    try:
        blob.upload_from_filename(os.path.join(temporary_folder, upload_file))
    except:
        alert_failure('Uploading archive ' + upload_file, repository, slack_failure_url)

    alert_success(repository, slack_success_url)
