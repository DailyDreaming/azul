FROM python:3.6.8-stretch

SHELL ["/bin/bash", "-c"]

RUN mkdir /build

WORKDIR /build

RUN mkdir terraform \
    && (cd terraform \
        && wget --quiet https://releases.hashicorp.com/terraform/0.12.5/terraform_0.12.5_linux_amd64.zip \
        && unzip terraform_0.12.5_linux_amd64.zip \
        && mv terraform /usr/local/bin/) \
    ; rm -rf terraform

COPY requirements.txt .
COPY requirements.dev.txt .
RUN python3.6 -m venv .venv \
    && source .venv/bin/activate \
    && pip install -U pip==10.0.1 setuptools==40.1.0 wheel==0.32.3 \
    && pip install -r requirements.dev.txt \
    ; rm requirements.txt requirements.dev.txt
