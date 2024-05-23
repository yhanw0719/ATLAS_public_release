import pickle
import warnings

import cloudpickle

pickle.ForkingPickler = cloudpickle.Pickler

# from pilates.activitysim.preprocessor import copy_beam_geoms

warnings.simplefilter(action='ignore', category=FutureWarning)
# from workflow_state import WorkflowState

import shutil
import subprocess
import multiprocessing
import psutil

try:
    import docker
except ImportError:
    print('Warning: Unable to import Docker Module')

import os
import logging
import sys
import glob
from pathlib import Path

# from pilates.activitysim import preprocessor as asim_pre
# from pilates.activitysim import postprocessor as asim_post
# from pilates.urbansim import preprocessor as usim_pre
# from pilates.urbansim import postprocessor as usim_post
# from pilates.beam import preprocessor as beam_pre
# from pilates.beam import postprocessor as beam_post
# from pilates.atlas import preprocessor as atlas_pre  ##
# from pilates.atlas import postprocessor as atlas_post  ##
# from pilates.utils.io import parse_args_and_settings
# from pilates.postprocessing.postprocessor import process_event_file, copy_outputs_to_mep

import yaml
from spython.main import Client
import os
import argparse



def formatted_print(string, width=50, fill_char='#'):
    print('\n')
    if len(string) + 2 > width:
        width = len(string) + 4
    string = string.upper()
    print(fill_char * width)
    print('{:#^{width}}'.format(' ' + string + ' ', width=width))
    print(fill_char * width, '\n')


def initialize_docker_client(settings):
    vehicle_ownership_model = settings.get('vehicle_ownership_model', False)  ## ATLAS
    models = [vehicle_ownership_model]
    image_names = settings['docker_images']
    pull_latest = settings.get('pull_latest', False)

    client = docker.from_env()
    if pull_latest:
        logger.info("Pulling from docker...")
        for model in models:
            if model:
                image = image_names[model]
                if image is not None:
                    print('Pulling latest image for {0}'.format(image))
                    client.images.pull(image)
    return client


def to_singularity_volumes(volumes):
    bindings = [f"{local_folder}:{binding['bind']}:{binding['mode']}" for local_folder, binding in volumes.items()]
    result_str = ','.join(bindings)
    return result_str


def to_singularity_env(env):
    bindings = [f"{env_var}={value}" for env_var, value in env.items()]
    result_str = ','.join(bindings)
    return '"' + result_str + '"'


def run_container(client, settings: dict, image: str, volumes: dict, command: str,
                  working_dir=None, environment=None):
    """
    Executes container using docker or singularity
    :param client: the docker client. If it's provided then docker is used, otherwise singularity is used
    :param settings: settings to get docker configuration
    :param image: the image to run
    :param volumes: a dictionary describing volume binding
    :param command: the command to run
    :param working_dir: the working directory inside the container. It's not necessary for docker because
    docker file may have an instruction WORKDIR. In this case that directory is used. Singularity don't take this
    instruction into account and the container working dir is the host working dir. Because of that most of the time
     singularity requires working dir. One can get the work dir from a docker image by looking at the Dockerfile
     (or image layers at the docker hub) and find the last WORKDIR instruction or by issuing a command:
      docker run -it --entrypoint /bin/bash ghcr.io/lbnl-science-it/atlas:v1.0.7 -c "env | grep PWD"
    :param environment: a dictionary that contains environment variables that needs to be set to the container
    """
    if client:
        docker_stdout = settings.get('docker_stdout', False)
        logger.info("Running docker container: %s, command: %s", image, command)
        run_kwargs = {
            'volumes': volumes,
            'command': command,
            'stdout': docker_stdout,
            'stderr': True,
            'detach': True
        }
        if working_dir:
            run_kwargs['working_dir'] = working_dir
        if environment:
            run_kwargs['environment'] = environment
        container = client.containers.run(image, **run_kwargs)
        for log in container.logs(
                stream=True, stderr=True, stdout=docker_stdout):
            print(log)
        container.remove()
        logger.info("Finished docker container: %s, command: %s", image, command)
    else:
        for local_folder in volumes:
            os.makedirs(local_folder, exist_ok=True)
        singularity_volumes = to_singularity_volumes(volumes)
        proc = ["singularity", "run", "--cleanenv"] \
            + (["--env", to_singularity_env(environment)] if environment else []) \
            + (["--pwd", working_dir] if working_dir else []) \
            + ["-B", singularity_volumes, image] \
            + command.split()
        logger.info("Running command: %s", " ".join(proc))
        subprocess.run(proc)
        logger.info("Finished command: %s", " ".join(proc))


def get_model_and_image(settings: dict, model_type: str):
    manager = settings['container_manager']
    if manager == "docker":
        image_names = settings['docker_images']
    elif manager == "singularity":
        image_names = settings['singularity_images']
    else:
        raise ValueError("Container Manager not specified (container_manager param in settings.yaml)")
    model_name = settings.get(model_type)
    if not model_name:
        raise ValueError(f"No model {model_type} specified")
    image_name = image_names[model_name]
    if not model_name:
        raise ValueError(f"No {manager} image specified for model {model_name}")
    return model_name, image_name


def run_atlas(settings, output_year, client, warm_start_atlas, atlas_run_count=1):
    # warm_start: warm_start_atlas = True, output_year = year = start_year
    # asim_no_usim: warm_start_atlas = True, output_year = year (should  = start_year)
    # normal: warm_start_atlas = False, output_year = forecast_year

    # 1. PARSE SETTINGS
    vehicle_ownership_model, atlas_image = get_model_and_image(settings, "vehicle_ownership_model")
    freq = settings.get('vehicle_ownership_freq', False)
    npe = settings.get('atlas_num_processes', False)
    nsample = settings.get('atlas_sample_size', False)
    beamac = settings.get('atlas_beamac', 0)
    mod = settings.get('atlas_mod', 1)
    adscen = settings.get('atlas_adscen', False)
    rebfactor = settings.get('atlas_rebfactor', 0)
    taxfactor = settings.get('atlas_taxfactor', 0)
    discIncent = settings.get('atlas_discIncent', 0)
    atlas_docker_vols = get_atlas_docker_vols(settings)
    atlas_cmd = get_atlas_cmd(settings, freq, output_year, npe, nsample, beamac, mod, adscen, rebfactor, taxfactor, discIncent)
    docker_stdout = settings.get('docker_stdout', False)

    # 2. PREPARE ATLAS inputs - already done.

    # 3. RUN ATLAS via docker container client
    print_str = (
        "Simulating vehicle ownership for {0} "
        "with frequency {1}, npe {2} nsample {3} beamac {4} scenario {5} rebfactor {6} taxfactor {7} discIncent {8}".format(
            output_year, freq, npe, nsample, beamac, adscen, rebfactor, taxfactor, discIncent))
    formatted_print(print_str)
    
    run_container(client, settings, atlas_image, atlas_docker_vols, atlas_cmd, 
                  working_dir='/',
                  environment=["PYTHONUNBUFFERED=1","buffered=no"])
    # atlas = client.containers.run(
    #     atlas_image,
    #     volumes=atlas_docker_vols,
    #     command=atlas_cmd,
    #     stdout=docker_stdout,  ## this read settings from yaml, changed to True in atlas_settings.yaml
    #     auto_remove=True,
    #     #stdout=True,
    #     stderr=True,
	# #environment='PYTHONUNBUFFERED=1',
	# environment=["PYTHONUNBUFFERED=1","buffered=no"],
    #     detach=True)
    #     ##xxdetach=False)

    logger.info('Atlas Done!')

    return



## Atlas: evolve household vehicle ownership
# run_atlas_auto is a run_atlas upgraded version, which will run_atlas again if
# outputs are not generated. This is mainly for preventing crash due to parallel
# computing errors that can be resolved by a simple resubmission
def run_atlas_auto(settings, output_year, client, warm_start_atlas):
    # run atlas
    atlas_run_count = 1
    try:
        run_atlas(settings, output_year, client, warm_start_atlas, atlas_run_count)
    except:
        logger.error('ATLAS RUN #{} FAILED'.format(atlas_run_count))

    # rerun atlas if outputs not found and run count <= 3
    atlas_output_path = settings['atlas_host_output_folder']
    fname = 'vehicles_{}.csv'.format(output_year)
    while atlas_run_count < 3:
        atlas_run_count = atlas_run_count + 1
        if not os.path.exists(os.path.join(atlas_output_path, fname)):
            logger.error('LAST ATLAS RUN FAILED -> RE-LAUNCHING ATLAS RUN #{} BELOW'.format(atlas_run_count))
            try:
                run_atlas(settings, output_year, client, warm_start_atlas, atlas_run_count)
            except:
                logger.error('ATLAS RUN #{} FAILED'.format(atlas_run_count))

    return


## Atlas vehicle ownership model volume mount defintion, equivalent to
## docker run -v atlas_host_input_folder:atlas_container_input_folder
def get_atlas_docker_vols(settings):
    atlas_host_input_folder = os.path.abspath(settings['atlas_host_input_folder'])
    atlas_host_output_folder = os.path.abspath(settings['atlas_host_output_folder'])
    atlas_container_input_folder = os.path.abspath(settings['atlas_container_input_folder'])
    atlas_container_output_folder = os.path.abspath(settings['atlas_container_output_folder'])
    atlas_docker_vols = {
        atlas_host_input_folder: {  ## source location, aka "local"
            'bind': atlas_container_input_folder,  ## destination loc, aka "remote", "client"
            'mode': 'rw'},
        atlas_host_output_folder: {
            'bind': atlas_container_output_folder,
            'mode': 'rw'}}
    return atlas_docker_vols


## For Atlas container command
def get_atlas_cmd(settings, freq, output_year, npe, nsample, beamac, mod, adscen, rebfactor, taxfactor, discIncent):
    basedir = settings.get('basedir', '/')
    codedir = settings.get('codedir', '/')
    formattable_atlas_cmd = settings['atlas_formattable_command']
    atlas_cmd = formattable_atlas_cmd.format(freq, output_year, npe, nsample, basedir, codedir, beamac, mod, adscen, rebfactor, taxfactor, discIncent)
    return atlas_cmd


def parse_args_and_settings(settings_file='atlas_settings.yaml'):
    # read settings from config file
    with open(settings_file) as file:
        settings = yaml.load(file, Loader=yaml.FullLoader)
    vehicle_ownership_model_enabled = settings.get('vehicle_ownership_model', False)  ## Atlas
    return settings






if __name__ == '__main__':

    logger = logging.getLogger(__name__)
    logger.info("Preparing runtime environment...")

    #########################################
    #  PREPARE PILATES RUNTIME ENVIRONMENT  #
    #########################################

    # load args and settings
    settings = parse_args_and_settings()

    # parse scenario settings
    start_year = settings['start_year']
    end_year = settings['end_year']
    freq = settings.get('vehicle_ownership_freq', 1)
    container_manager = settings['container_manager']
    formatted_print(
        'RUNNING PILATES FROM {0} TO {1}'.format(start_year, end_year))

    # start docker client
    if container_manager == 'docker':
        client = initialize_docker_client(settings)
    else:
        client = None

    #################################
    #  RUN THE SIMULATION WORKFLOW  #
    #################################
    for year in range(start_year, end_year+1, freq):

        run_atlas_auto(settings, year, client, warm_start_atlas=False)

    logger.info("Finished")
