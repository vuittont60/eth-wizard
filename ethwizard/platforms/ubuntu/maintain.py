import subprocess
import httpx
import re

from packaging.version import parse as parse_version, Version

from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import button_dialog

from ethwizard.platforms.ubuntu.common import (
    log,
    save_state,
    quit_app,
    get_systemd_service_details
)

from ethwizard.constants import (
    CTX_SELECTED_EXECUTION_CLIENT,
    CTX_SELECTED_CONSENSUS_CLIENT,
    EXECUTION_CLIENT_GETH,
    CONSENSUS_CLIENT_LIGHTHOUSE,
    WIZARD_COMPLETED_STEP_ID,
    UNKNOWN_VALUE,
    GITHUB_REST_API_URL,
    GETH_LATEST_RELEASE,
    GITHUB_API_VERSION,
    GETH_SYSTEMD_SERVICE_NAME,
    MAINTENANCE_DO_NOTHING,
    MAINTENANCE_RESTART_SERVICE,
    MAINTENANCE_UPGRADE_CLIENT,
    MAINTENANCE_CHECK_AGAIN_SOON,
    MAINTENANCE_START_SERVICE,
    MAINTENANCE_REINSTALL_CLIENT,
    LIGHTHOUSE_BN_SYSTEMD_SERVICE_NAME,
    LIGHTHOUSE_VC_SYSTEMD_SERVICE_NAME,
    LIGHTHOUSE_LATEST_RELEASE,
    LIGHTHOUSE_INSTALLED_PATH,
    BN_VERSION_EP
)

def enter_maintenance(context):
    # Maintenance entry point for Ubuntu.
    # Maintenance is started after the wizard has completed.

    log.info(f'Entering maintenance mode. To be implemented.')

    if context is None:
        log.error('Missing context.')
        return False

    context = use_default_client(context)

    if context is None:
        log.error('Missing context.')
        return False
    
    return show_dashboard(context)

def show_dashboard(context):
    # Show simple dashboard

    selected_execution_client = CTX_SELECTED_EXECUTION_CLIENT
    selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT

    current_execution_client = context[selected_execution_client]
    current_consensus_client = context[selected_consensus_client]

    # Get execution client details

    execution_client_details = get_execution_client_details(current_execution_client)
    if not execution_client_details:
        log.error('Unable to get execution client details.')
        return False

    # Find out if we need to do maintenance for the execution client

    execution_client_details['next_step'] = MAINTENANCE_DO_NOTHING

    installed_version = execution_client_details['versions']['installed']
    if installed_version != UNKNOWN_VALUE:
        installed_version = parse_version(installed_version)
    running_version = execution_client_details['versions']['running']
    if running_version != UNKNOWN_VALUE:
        running_version = parse_version(running_version)
    available_version = execution_client_details['versions']['available']
    if available_version != UNKNOWN_VALUE:
        available_version = parse_version(available_version)
    latest_version = execution_client_details['versions']['latest']
    if latest_version != UNKNOWN_VALUE:
        latest_version = parse_version(latest_version)

    # If the available version is older than the latest one, we need to check again soon
    # It simply means that the updated build is not available yet for installing

    if is_version(latest_version) and is_version(available_version):
        if available_version < latest_version:
            execution_client_details['next_step'] = MAINTENANCE_CHECK_AGAIN_SOON

    # If the service is not running, we need to start it

    if execution_client_details['service']['found'] and not (
        execution_client_details['service']['active'] == 'active' and
        execution_client_details['service']['sub'] == 'running'
        ):
        execution_client_details['next_step'] = MAINTENANCE_START_SERVICE

    # If the running version is older than the installed one, we need to restart the service

    if is_version(installed_version) and is_version(running_version):
        if running_version < installed_version:
            execution_client_details['next_step'] = MAINTENANCE_RESTART_SERVICE

    # If the installed version is older than the available one, we need to upgrade the client

    if is_version(installed_version) and is_version(available_version):
        if installed_version < available_version:
            execution_client_details['next_step'] = MAINTENANCE_UPGRADE_CLIENT

    # If the service is not installed or found, we need to reinstall the client

    if not execution_client_details['service']['found']:
        execution_client_details['next_step'] = MAINTENANCE_REINSTALL_CLIENT

    # Get consensus client details

    consensus_client_details = get_consensus_client_details(current_consensus_client)
    if not consensus_client_details:
        log.error('Unable to get consensus client details.')
        return False
    
    # Find out if we need to do maintenance for the consensus client

    consensus_client_details['next_step'] = MAINTENANCE_DO_NOTHING

    installed_version = consensus_client_details['versions']['installed']
    if installed_version != UNKNOWN_VALUE:
        installed_version = parse_version(installed_version)
    running_version = consensus_client_details['versions']['running']
    if running_version != UNKNOWN_VALUE:
        running_version = parse_version(running_version)
    latest_version = consensus_client_details['versions']['latest']
    if latest_version != UNKNOWN_VALUE:
        latest_version = parse_version(latest_version)
    
    # If the service is not running, we need to start it

    if consensus_client_details['bn_service']['found'] and not (
        consensus_client_details['bn_service']['active'] == 'active' and
        consensus_client_details['bn_service']['sub'] == 'running'
        ):
        consensus_client_details['next_step'] = MAINTENANCE_START_SERVICE

    if consensus_client_details['vc_service']['found'] and not (
        consensus_client_details['vc_service']['active'] == 'active' and
        consensus_client_details['vc_service']['sub'] == 'running'
        ):
        consensus_client_details['next_step'] = MAINTENANCE_START_SERVICE

    # If the running version is older than the installed one, we need to restart the services

    if is_version(installed_version) and is_version(running_version):
        if running_version < installed_version:
            consensus_client_details['next_step'] = MAINTENANCE_RESTART_SERVICE

    # If the installed version is older than the latest one, we need to upgrade the client

    if is_version(installed_version) and is_version(latest_version):
        if installed_version < latest_version:
            consensus_client_details['next_step'] = MAINTENANCE_UPGRADE_CLIENT

    # If the service is not installed or found, we need to reinstall the client

    if (not consensus_client_details['bn_service']['found'] or
        not consensus_client_details['vc_service']['found']):
        consensus_client_details['next_step'] = MAINTENANCE_REINSTALL_CLIENT

    # We only need to do maintenance if either the execution or the consensus client needs
    # maintenance.

    maintenance_needed = (
        execution_client_details['next_step'] != MAINTENANCE_DO_NOTHING or
        consensus_client_details['next_step'] != MAINTENANCE_DO_NOTHING)

    # Build the dashboard with the details we have

    maintenance_tasks_description = {
        MAINTENANCE_DO_NOTHING: 'Nothing to perform here. Everything is good.',
        MAINTENANCE_RESTART_SERVICE: 'Service needs to be restarted.',
        MAINTENANCE_UPGRADE_CLIENT: 'Client needs to be upgraded.',
        MAINTENANCE_CHECK_AGAIN_SOON: 'Check again. Client update should be available soon.',
        MAINTENANCE_START_SERVICE: 'Service needs to be started.',
        MAINTENANCE_REINSTALL_CLIENT: 'Client needs to be reinstalled.',
    }

    buttons = [
        ('Quit', False),
    ]

    maintenance_message = 'Nothing is needed in terms of maintenance.'

    if maintenance_needed:
        buttons = [
            ('Maintain', 1),
            ('Quit', False),
        ]

        maintenance_message = 'Some maintenance tasks are pending. Click maintain to perform them.'

    ec_section = (f'Geth details (I: {execution_client_details["version"]["installed"]}, '
        f'R: {execution_client_details["version"]["running"]}, '
        f'A: {execution_client_details["version"]["available"]}, '
        f'L: {execution_client_details["version"]["latest"]})\n'
        f'Maintenance task: {maintenance_tasks_description.get(execution_client_details["next_step"], UNKNOWN_VALUE)}')

    cc_section = (f'Lighthouse details (I: {consensus_client_details["version"]["installed"]}, '
        f'R: {consensus_client_details["version"]["running"]}, '
        f'L: {consensus_client_details["version"]["latest"]})\n'
        f'Maintenance task: {maintenance_tasks_description.get(consensus_client_details["next_step"], UNKNOWN_VALUE)}')

    result = button_dialog(
        title='Maintenance dashboard',
        text=(HTML(
f'''
Here are some details about your Ethereum clients.

{ec_section}

{cc_section}

{maintenance_message}

Versions legend - I: Installed, R: Running, A: Available, L: Latest
'''             )),
        buttons=buttons
    ).run()

    if not result:
        return False
    
    if result == 1:
        return perform_maintenance(execution_client_details, consensus_client_details)

def is_version(value):
    # Return true if this is a packaging version
    return isinstance(value, Version)

def get_execution_client_details(execution_client):
    # Get the details for the current execution client

    if execution_client == EXECUTION_CLIENT_GETH:

        details = {
            'service': {
                'found': False,
                'load': UNKNOWN_VALUE,
                'active': UNKNOWN_VALUE,
                'sub': UNKNOWN_VALUE
            },
            'versions': {
                'installed': UNKNOWN_VALUE,
                'running': UNKNOWN_VALUE,
                'available': UNKNOWN_VALUE,
                'latest': UNKNOWN_VALUE
            }
        }
        
        # Check for existing systemd service
        geth_service_exists = False
        geth_service_name = GETH_SYSTEMD_SERVICE_NAME

        service_details = get_systemd_service_details(geth_service_name)

        if service_details['LoadState'] == 'loaded':
            geth_service_exists = True
        
        if not geth_service_exists:
            return details
        
        details['service']['found'] = True
        details['service']['load'] = service_details['LoadState']
        details['service']['active'] = service_details['ActiveState']
        details['service']['sub'] = service_details['SubState']

        details['versions']['installed'] = get_geth_installed_version()
        details['versions']['running'] = get_geth_running_version()
        details['versions']['available'] = get_geth_available_version()
        details['versions']['latest'] = get_geth_latest_version()

        return details

    else:
        log.error(f'Unknown execution client {execution_client}.')
        return False

def get_geth_installed_version():
    # Get the installed version for Geth

    log.info('Getting Geth installed version...')

    process_result = subprocess.run(['geth', 'version'], capture_output=True,
        text=True)
    
    if process_result.returncode != 0:
        log.error(f'Unexpected return code from geth. Return code: '
            f'{process_result.returncode}')
        return UNKNOWN_VALUE
    
    process_output = process_result.stdout
    result = re.search(r'Version: (?P<version>[^-]+)', process_output)
    if not result:
        log.error(f'Cannot parse {process_output} for Geth installed version.')
        return UNKNOWN_VALUE
    
    installed_version = result.group('version')

    log.info(f'Geth installed version is {installed_version}')

    return installed_version

def get_geth_running_version():
    # Get the running version for Geth

    log.info('Getting Geth running version...')

    local_geth_jsonrpc_url = 'http://127.0.0.1:8545'
    request_json = {
        'jsonrpc': '2.0',
        'method': 'web3_clientVersion',
        'id': 67
    }
    headers = {
        'Content-Type': 'application/json'
    }
    try:
        response = httpx.post(local_geth_jsonrpc_url, json=request_json, headers=headers)
    except httpx.RequestError as exception:
        log.error(f'Cannot connect to Geth. Exception: {exception}')
        return UNKNOWN_VALUE

    if response.status_code != 200:
        log.error(f'Unexpected status code from {local_geth_jsonrpc_url}. Status code: '
            f'{response.status_code}')
        return UNKNOWN_VALUE
    
    response_json = response.json()

    if 'result' not in response_json:
        log.error(f'Unexpected JSON response from {local_geth_jsonrpc_url}. result not found.')
        return UNKNOWN_VALUE
    
    version_agent = response_json['result']

    # Version agent should look like: Geth/v1.10.12-stable-6c4dc6c3/linux-amd64/go1.17.2
    result = re.search(r'Geth/v(?P<version>[^-/]+)(-(?P<stable>[^-/]+))?(-(?P<commit>[^-/]+))?',
        version_agent)
    if not result:
        log.error(f'Cannot parse {version_agent} for Geth version.')
        return UNKNOWN_VALUE

    running_version = result.group('version')

    log.info(f'Geth running version is {running_version}')

    return running_version

def get_geth_available_version():
    # Get the available version for Geth, potentially for update

    log.info('Getting Geth available version...')

    subprocess.run(['apt', '-y', 'update'])
    process_result = subprocess.run(['apt-cache', 'policy', 'geth'], capture_output=True,
        text=True)
    
    if process_result.returncode != 0:
        log.error(f'Unexpected return code from apt-cache. Return code: '
            f'{process_result.returncode}')
        return UNKNOWN_VALUE
    
    process_output = process_result.stdout
    result = re.search(r'Candidate: (?P<version>[^\+]+)', process_output)
    if not result:
        log.error(f'Cannot parse {process_output} for Geth candidate version.')
        return UNKNOWN_VALUE
    
    available_version = result.group('version')

    log.info(f'Geth available version is {available_version}')

    return available_version

def get_geth_latest_version():
    # Get the latest stable version for Geth, potentially not available yet for update

    log.info('Getting Geth latest version...')

    geth_gh_release_url = GITHUB_REST_API_URL + GETH_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    try:
        response = httpx.get(geth_gh_release_url, headers=headers,
            follow_redirects=True)
    except httpx.RequestError as exception:
        log.error(f'Exception while getting the latest stable version for Geth. {exception}')
        return UNKNOWN_VALUE

    if response.status_code != 200:
        log.error(f'HTTP error while getting the latest stable version for Geth. '
            f'Status code {response.status_code}')
        return UNKNOWN_VALUE
    
    release_json = response.json()

    if 'tag_name' not in release_json or not isinstance(release_json['tag_name'], str):
        log.error(f'Unable to find tag name in Github response while getting the latest stable '
            f'version for Geth.')
        return UNKNOWN_VALUE
    
    tag_name = release_json['tag_name']
    result = re.search(r'v?(?P<version>.+)', tag_name)
    if not result:
        log.error(f'Cannot parse tag name {tag_name} for Geth version.')
        return UNKNOWN_VALUE
    
    latest_version = result.group('version')

    log.info(f'Geth latest version is {latest_version}')

    return latest_version

def get_consensus_client_details(consensus_client):
    # Get the details for the current consensus client

    if consensus_client == CONSENSUS_CLIENT_LIGHTHOUSE:

        details = {
            'bn_service': {
                'found': False,
                'load': UNKNOWN_VALUE,
                'active': UNKNOWN_VALUE,
                'sub': UNKNOWN_VALUE
            },
            'vc_service': {
                'found': False,
                'load': UNKNOWN_VALUE,
                'active': UNKNOWN_VALUE,
                'sub': UNKNOWN_VALUE
            },
            'versions': {
                'installed': UNKNOWN_VALUE,
                'running': UNKNOWN_VALUE,
                'latest': UNKNOWN_VALUE
            }
        }
        
        # Check for existing systemd services
        lighthouse_bn_service_exists = False
        lighthouse_bn_service_name = LIGHTHOUSE_BN_SYSTEMD_SERVICE_NAME

        service_details = get_systemd_service_details(lighthouse_bn_service_name)

        if service_details['LoadState'] == 'loaded':
            lighthouse_bn_service_exists = True

            details['bn_service']['found'] = True
            details['bn_service']['load'] = service_details['LoadState']
            details['bn_service']['active'] = service_details['ActiveState']
            details['bn_service']['sub'] = service_details['SubState']

        lighthouse_vc_service_exists = False
        lighthouse_vc_service_name = LIGHTHOUSE_VC_SYSTEMD_SERVICE_NAME

        service_details = get_systemd_service_details(lighthouse_vc_service_name)

        if service_details['LoadState'] == 'loaded':
            lighthouse_vc_service_exists = True
        
            details['vc_service']['found'] = True
            details['vc_service']['load'] = service_details['LoadState']
            details['vc_service']['active'] = service_details['ActiveState']
            details['vc_service']['sub'] = service_details['SubState']

        details['versions']['installed'] = get_lighthouse_installed_version()
        details['versions']['running'] = get_lighthouse_running_version()
        details['versions']['latest'] = get_lighthouse_latest_version()

        return details

    else:
        log.error(f'Unknown consensus client {consensus_client}.')
        return False

def get_lighthouse_installed_version():
    # Get the installed version for Lighthouse

    log.info('Getting Lighthouse installed version...')

    process_result = subprocess.run([LIGHTHOUSE_INSTALLED_PATH, '--version'], capture_output=True,
        text=True)
    
    if process_result.returncode != 0:
        log.error(f'Unexpected return code from Lighthouse. Return code: '
            f'{process_result.returncode}')
        return UNKNOWN_VALUE
    
    process_output = process_result.stdout
    result = re.search(r'Lighthouse v?(?P<version>[^-]+)', process_output)
    if not result:
        log.error(f'Cannot parse {process_output} for Lighthouse installed version.')
        return UNKNOWN_VALUE
    
    installed_version = result.group('version')

    log.info(f'Lighthouse installed version is {installed_version}')

    return installed_version

def get_lighthouse_running_version():
    # Get the running version for Lighthouse

    log.info('Getting Lighthouse running version...')

    local_lighthouse_bn_version_url = 'http://127.0.0.1:5052' + BN_VERSION_EP

    try:
        response = httpx.get(local_lighthouse_bn_version_url)
    except httpx.RequestError as exception:
        log.error(f'Cannot connect to Lighthouse. Exception: {exception}')
        return UNKNOWN_VALUE

    if response.status_code != 200:
        log.error(f'Unexpected status code from {local_lighthouse_bn_version_url}. Status code: '
            f'{response.status_code}')
        return UNKNOWN_VALUE
    
    response_json = response.json()

    if 'data' not in response_json or 'version' not in response_json['data']:
        log.error(f'Unexpected JSON response from {local_lighthouse_bn_version_url}. result not found.')
        return UNKNOWN_VALUE
    
    version_agent = response_json['data']['version']

    # Version agent should look like: Lighthouse/v2.0.1-aaa5344/x86_64-linux
    result = re.search(r'Lighthouse/v(?P<version>[^-/]+)(-(?P<commit>[^-/]+))?',
        version_agent)
    if not result:
        log.error(f'Cannot parse {version_agent} for Lighthouse version.')
        return UNKNOWN_VALUE

    running_version = result.group('version')

    log.info(f'Lighthouse running version is {running_version}')

    return running_version

def get_lighthouse_latest_version():
    # Get the latest version for Lighthouse

    log.info('Getting Lighthouse latest version...')

    lighthouse_gh_release_url = GITHUB_REST_API_URL + LIGHTHOUSE_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    try:
        response = httpx.get(lighthouse_gh_release_url, headers=headers,
            follow_redirects=True)
    except httpx.RequestError as exception:
        log.error(f'Exception while getting the latest stable version for Lighthouse. {exception}')
        return UNKNOWN_VALUE

    if response.status_code != 200:
        log.error(f'HTTP error while getting the latest stable version for Lighthouse. '
            f'Status code {response.status_code}')
        return UNKNOWN_VALUE
    
    release_json = response.json()

    if 'tag_name' not in release_json or not isinstance(release_json['tag_name'], str):
        log.error(f'Unable to find tag name in Github response while getting the latest stable '
            f'version for Lighthouse.')
        return UNKNOWN_VALUE
    
    tag_name = release_json['tag_name']
    result = re.search(r'v?(?P<version>.+)', tag_name)
    if not result:
        log.error(f'Cannot parse tag name {tag_name} for Lighthouse version.')
        return UNKNOWN_VALUE
    
    latest_version = result.group('version')

    log.info(f'Lighthouse latest version is {latest_version}')

    return latest_version

def perform_maintenance(execution_client_details, consensus_client_details):
    # TODO: Perform all the maintenance tasks
    return False

def use_default_client(context):
    # Set the default clients in context if they are not provided

    selected_execution_client = CTX_SELECTED_EXECUTION_CLIENT
    selected_consensus_client = CTX_SELECTED_CONSENSUS_CLIENT

    updated_context = False

    if selected_execution_client not in context:
        context[selected_execution_client] = EXECUTION_CLIENT_GETH
        updated_context = True
    
    if selected_consensus_client not in context:
        context[selected_consensus_client] = CONSENSUS_CLIENT_LIGHTHOUSE
        updated_context = True

    if updated_context:
        if not save_state(WIZARD_COMPLETED_STEP_ID, context):
            return None

    return context