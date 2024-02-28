#!/usr/bin/env python3

"""
NeuroBuilder: Interactive Container Builder v2
Joshua D. Scarsbrook - The University of Queensland

Released under Apache 2.0 License
"""

import argparse
import logging
from typing import Tuple
import asciinema
import asciinema.asciicast
import asciinema.player
import os
import uuid
import json
import platformdirs
import datetime
import subprocess

REGISTRY_VERSION = 1

logging.basicConfig(level=logging.DEBUG)

log = logging.getLogger("main")


def read_file(filename: str):
    with open(filename, "r") as f:
        return f.read()


def write_file(filename: str, content):
    with open(filename, "w") as f:
        f.write(content)


def read_json(filename: str):
    with open(filename, "r") as f:
        return json.load(f)


def write_json(filename: str, obj):
    with open(filename, "w") as f:
        json.dump(obj, f)


def run_command(*args):
    log.debug("run_command: %s", args)

    subprocess.check_call(args)


def get_default_environment_path() -> str:
    """
    The default data directory is in the user config directory.
    """

    return platformdirs.user_data_dir("neurobuilder")


def generate_container_id() -> str:
    return str(uuid.uuid4())


def generate_version() -> str:
    dt = datetime.datetime.now()

    return dt.strftime("%Y%m%d_%H%M")


def load_registry(env):
    registry_path = os.path.join(env, "registry.json")

    if not os.path.exists(registry_path):
        os.makedirs(os.path.dirname(registry_path))

        return {
            "version": REGISTRY_VERSION,
            "containers": {},
        }

    return read_json(registry_path)


def save_registry(env, registry):
    registry_path = os.path.join(env, "registry.json")

    if not os.path.exists(registry_path):
        os.makedirs(os.path.dirname(registry_path), exist_ok=True)

    write_json(registry_path, registry)


def get_container_path(env, name):
    # Load the registry.
    registry = load_registry(env)

    # If the container path already exists then use that.
    if name in registry["containers"]:
        return registry["containers"][name]

    # Otherwise generate a new random container id.
    container_id = generate_container_id()

    # Get the container path and create the directory.
    container_path = os.path.join(env, container_id)
    os.makedirs(container_path)

    # Add the container to the registry and save it.
    registry["containers"][name] = container_path
    save_registry(env, registry)

    return container_path


def get_container_version_path(container_path, version, mkdir=True) -> Tuple[str, bool]:
    version_path = os.path.join(container_path, version)

    if not os.path.exists(version_path):
        if mkdir:
            os.mkdir(version_path)
        return version_path, False
    else:
        return version_path, True


def get_package_manager(base: str) -> str:
    """
    Attempt to autodetect the package manager.
    """

    if "ubuntu" in base:
        return "apt"
    elif "debian" in base:
        return "apt"
    elif "centos" in base:
        return "yum"
    elif "fedora" in base:
        return "yum"
    else:
        return "unknown"


def get_template(package_manager: str, base: str) -> str:
    """
    Get the singularity build template.
    """

    template = ""

    # Bootstrap from docker.
    template += "BootStrap: docker\n"
    template += f"From: {base}\n"

    template += """%post -c /bin/bash
  set -ex
  touch /etc/localtime
  CUSTOM_ENV=/.singularity.d/env/99-zz_custom_env.sh
  cat >$CUSTOM_ENV <<EOF
#!/bin/bash
PS1='\\u@neurodesk-builder:\\w\\$ '
EOF
  chmod 755 $CUSTOM_ENV
"""

    # Change ubuntu repos to mirror.arrnet.edu.au
    if "ubuntu" in base:
        template += """sed -i -e 's/ports.ubuntu.com\\/ubuntu-ports/mirror.aarnet.edu.au\\/pub\\/ubuntu\\/ports/g' /etc/apt/sources.list
sed -i -e 's/archive.ubuntu.com\\/ubuntu/mirror.aarnet.edu.au\\/pub\\/ubuntu\\/archive/g' /etc/apt/sources.list
"""

    if package_manager == "apt":
        template += "apt update -y\n"
    elif package_manager == "yum":
        template += "yum update -y\n"

    return template


def build_container_sandbox(
    env: str, package_manager: str, base: str
) -> Tuple[str, str]:
    # Get the template.
    template = get_template(package_manager, base)

    # Make a new temporary directory.
    temp_dir = os.path.join(env, "temp", str(uuid.uuid4()))
    os.makedirs(temp_dir)

    # Create and write the template.
    template_file = os.path.join(temp_dir, "template")
    write_file(template_file, template)

    sandbox_dir = os.path.join(temp_dir, "sandbox")

    # Run Singularity to create the build directory.
    run_command("sudo", "singularity", "build", "--sandbox", sandbox_dir, template_file)

    return temp_dir, sandbox_dir


def get_container_run_command(sandbox) -> str:
    return f"sudo singularity shell --writable {sandbox}"


def get_container_recording_path(version_path) -> str:
    return os.path.join(version_path, "recording.cast")


def convert_container_to_sif(version_path, sandbox_path):
    container_path = os.path.join(version_path, "container.sif")

    run_command("sudo", "singularity", "build", container_path, sandbox_path)


def cleanup_temporary_path(temp_dir):
    run_command("sudo", "rm", "-rf", temp_dir)


def cmd_create(args):
    name = args.name
    base = args.base
    version = args.version
    package_manager = args.pkg
    env = args.env

    # Use the user supplied environment path
    if env == "":
        env = get_default_environment_path()

    # Make a version number for this container.
    if version == "":
        version = generate_version()

    # Get the package manager.
    if package_manager == "":
        package_manager = get_package_manager(base)

        if package_manager == "unknown":
            raise Exception("could not autodetect package manager")

    # Get the container path or create it in the registry.
    container_path = get_container_path(env, name)

    # Check that the version is unique
    version_path, exists = get_container_version_path(container_path, version)
    if exists:
        raise Exception(f"container {name} already has version {version}.")

    # Build a sandbox for the container in a temporary directory.
    temp_dir, sandbox = build_container_sandbox(env, package_manager, base)

    # Get the command to start the container for recording.
    record_command = get_container_run_command(sandbox)

    # Get the recording path for the asciicast file.
    recording_path = get_container_recording_path(version_path)

    # Actually run the container and do the recording.
    asciinema.record_asciicast(recording_path, command=record_command)

    # Convert the container to sif format from the sandbox path.
    convert_container_to_sif(version_path, sandbox)

    # Cleanup the sandbox path.
    cleanup_temporary_path(temp_dir)


def cmd_run(args):
    name = args.name
    version = args.version
    env = args.env

    # Use the user supplied environment path
    if env == "":
        env = get_default_environment_path()

    # Get the container path.
    container_path = get_container_path(env, name)

    # Get the container version path. It has to exist for this to work.
    version_path, exists = get_container_version_path(container_path, version)
    if not exists:
        raise Exception("that version doesn't exist")

    # Get the sif file.
    sif_path = os.path.join(version_path, "container.sif")

    # Finally run singularity with the sif file.
    run_command("singularity", "run", sif_path)


# def cmd_push(args):
#     raise NotImplementedError()


# def cmd_pull(args):
#     raise NotImplementedError()


def cmd_list(args):
    env = args.env

    # Use the user supplied environment path
    if env == "":
        env = get_default_environment_path()

    # Load the registry.
    registry = load_registry(env)

    # For each container get it's versions and print the name and the version.
    for container in registry["containers"]:
        container_path = registry["containers"][container]

        for child in os.listdir(container_path):
            child_name = os.path.join(container_path, child, "container.sif")
            if os.path.exists(child_name):
                print(f"{container} {child}")


def cmd_replay(args):
    name = args.name
    version = args.version
    env = args.env

    # Use the user supplied environment path
    if env == "":
        env = get_default_environment_path()

    # Get the container path.
    container_path = get_container_path(env, name)

    # Get the container version path. It has to exist for this to work.
    version_path, exists = get_container_version_path(
        container_path, version, mkdir=False
    )
    if not exists:
        raise Exception("that version doesn't exist")

    # Get the recording filename.
    cast_filename = get_container_recording_path(version_path)

    # Replay the recording.
    with asciinema.asciicast.open_from_url(cast_filename) as a:
        player = asciinema.player.Player()
        player.play(a)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="neurobuilder", description="Build containers for neuroimaging software."
    )

    parser.add_argument(
        "--env", type=str, help="the environment path to store containers.", default=""
    )

    subparsers = parser.add_subparsers(help="sub-command help")

    parser_create = subparsers.add_parser(
        "create", help="create a new container using a interactive builder."
    )
    parser_create.add_argument(
        "--base",
        type=str,
        default="ubuntu:22.04",
        help="the base image to create the container with (default: ubuntu:22.04).",
    )
    parser_create.add_argument(
        "--pkg",
        type=str,
        default="",
        help="set the package manager to use. if not set this will be detected from base.",
    )
    parser_create.add_argument(
        "--version",
        type=str,
        default="",
        help="the version of the container to create.",
    )
    parser_create.add_argument(
        "name",
        type=str,
        help="the name of the container to create.",
    )
    parser_create.set_defaults(func=cmd_create)

    parser_run = subparsers.add_parser("run", help="run a locally saved container.")
    parser_run.add_argument(
        "name",
        type=str,
        help="the name of the container to run.",
    )
    parser_run.add_argument(
        "version",
        type=str,
        help="the version of the container to run.",
    )
    parser_run.set_defaults(func=cmd_run)

    """
    Both of these commands are for a online service that's not yet implemented.
    """
    # parser_push = subparsers.add_parser(
    #     "push", help="share a container on the online service."
    # )
    # parser_push.set_defaults(func=cmd_push)

    # parser_pull = subparsers.add_parser(
    #     "pull", help="pull a parser from the online service."
    # )
    # parser_pull.set_defaults(func=cmd_pull)

    parser_list = subparsers.add_parser(
        "list", help="list all containers and versions in the local registry."
    )
    parser_list.set_defaults(func=cmd_list)

    parser_replay = subparsers.add_parser(
        "replay", help="replay the terminal session used to create a container."
    )
    parser_replay.add_argument(
        "name",
        type=str,
        help="the name of the container to replay.",
    )
    parser_replay.add_argument(
        "version",
        type=str,
        help="the version of the container to replay.",
    )
    parser_replay.set_defaults(func=cmd_replay)

    args = parser.parse_args()
    args.func(args)
