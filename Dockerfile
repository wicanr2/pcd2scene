# pcd2scene 執行環境。基底以 digest 釘版，套件版本見 requirements.lock
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.lock /opt/pcd2scene/requirements.lock
RUN pip install --no-compile -r /opt/pcd2scene/requirements.lock
ENV PYTHONPATH=/src/src
WORKDIR /src
