import json, os, requests, sys, logging, google.api_core, yaml
from datetime import datetime
from google.cloud import pubsub_v1, secretmanager

conf = yaml.load(open('config.yaml', 'r'), Loader=yaml.SafeLoader)['config']

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

def alert_failure(message, repository):
    """ 
        Sends a message to slack, logs and quits
    """
    
    msg = 'GitHub Backup Failed. Could not retrieve list of repositories to backup. ' + message
    slack_message(conf['slack_failure_url'], msg)
    logging.error(msg)
    sys.exit(99)

# ------------------------------------------------------------------------

def get_repos(request):
    """
        Gets values from a HTTP request, 
        Get Github API token from secrets manager
        Retrieves list of repositories from Github by access token
        Queues each repository to google pub/sub
    """
    
    # get access token
    access_token = get_secret(secret_name=conf['secret_name'], project_id=conf['project'])
    
    # get repos
    repos = []
    end_cursor = ''
    has_next_page = True
    try:
        while has_next_page:
            req = fetch_repositories_pagination_query(access_token, after=end_cursor)
            res = req.json()['data']['organization']['repositories']['edges']
            total = req.json()['data']['organization']['repositories']['totalCount']
            has_next_page = req.json()['data']['organization']['repositories']['pageInfo']['hasNextPage']
            end_cursor = req.json()['data']['organization']['repositories']['pageInfo']['endCursor']
            
            for repo in res: 
                repos.append(repo['node']['name'])
    except KeyError:
        alert_failure('ERROR: KeyError in data. Most likely this means the authentication token for the github API is not working or is missing.')
    
    # check that our list is complete
    if len(repos) != total:
        alert_failure('ERROR: Total number of repositories does not match number of retrieved repository names.')

    # queue repositories to pubsub
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(conf['project'], conf['topic'])
    
    try: 
        topic = publisher.create_topic(topic_path)
    except google.api_core.exceptions.AlreadyExists:
        pass
    
    for repository in repos:
        conf['repository'] = repository    
        try:
            publisher.publish(topic_path, json.dumps(conf).encode('utf-8'), action='backup')
        except: 
            alert_failure('ERROR: Could not write to Pubsub for repository ' + repository)
    return 'ok'
    
# ------------------------------------------------------------------------  

def fetch_repositories_pagination_query(access_token, after=''):
    """
        Paginate through the Github API list repositories. 
        Get 100 repos per page
        Start next page after last item

    """
    if after != '':
        after = ', after: "' + after + '"'
    query = {'query': 
        """{
        organization(login: "troperty") {
            repositories(orderBy: {field: NAME, direction: ASC}, first: 100 """ + after + """) {
            edges {
                node {
                name 
                }
                cursor
            }
            pageInfo {
                hasNextPage
                endCursor
            }
            totalCount
            }
        }
        }"""
    }
    headers = {'Authorization': 'token %s' % access_token}
    r = requests.post(url='https://api.github.com/graphql', json=query, headers=headers)
    return r
