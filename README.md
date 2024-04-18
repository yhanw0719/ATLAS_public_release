# ATLAS_public_release
Public release of standalone ATLAS, including run instructions and sample inputs/outputs


# python env setup

TBD
hopefully can just use the container

docker pull          ghcr.io/tin6150/python:main

then run atlas as
docker run -it --rm  -v `pwd`:/mnt ghcr.io/tin6150/python:main  -u /mnt/atlas_run.py -v 2>&1 | tee ./log_atlas_testv12.out &

(might even put the Dockerfile and build process into this repo...)



# Docker in MacOS


Stack Overflow says to use::

    softwareupdate --install-rosetta


