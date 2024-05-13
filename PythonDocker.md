
Advance Topic:

The main documentation list out all the python packages that are needed to invoke Atlas.

Here is an altenrnate way to utilize a docker that has all the python libraries in the container rather than having them installed on the host.


## prepare the environment - leverage containerized python3 and pip libraries and docker passthrough capabilities:

The following is tested to work on a Ubuntu 22.04 machine with docker-compose installed (via apt or snap)

```{bash}
docker run -it --rm --entrypoint=python3 -v `pwd`:/mnt  -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/tin6150/python:main  \
  -u ./atlas_run.py -v   2>&1  |  tee ./atlas_log.TXT
```

`pwd` is dir with atlas run config and data:
- atlas_run.py
- atlas_settings.yaml
- settings.env
- atlas_input
- atlas_output
