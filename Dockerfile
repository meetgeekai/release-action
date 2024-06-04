FROM --platform=linux/amd64 python:3.11-slim-buster

COPY . /release_action/
WORKDIR /release_action

ENV PYTHONPATH="${PYTHONPATH}:/release_action/"

RUN pip3 install -r '/release_action/requirements.txt'

ENTRYPOINT ["python3", "/release_action/main.py"]
