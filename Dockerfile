ARG UBUNTU_RELEASE=18.04
FROM ubuntu:${UBUNTU_RELEASE}
LABEL maintainer="SEEBURGER AG (https://github.com/seeburger-ag/openstack-pdns-updater)"

USER root

ENV DEBIAN_FRONTEND noninteractive

ENV USER_ID ${USER_ID:-45000}
ENV GROUP_ID ${GROUP_ID:-45000}

ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8

ENV OS_CACERT /opt/openstack-pdns-updater/ca-certificates.crt

RUN apt update \
    && apt upgrade -y \
    && apt install -y \
        git \
        locales \
        software-properties-common \
        python3-pip \
        libssl-dev \
    && groupadd -g $GROUP_ID dragon \
    && useradd -g dragon -u $USER_ID -m -d /home/dragon dragon \
    && locale-gen en_US.UTF-8 \
    && pip3 install --no-cache-dir os-client-config \
    && pip3 install --no-cache-dir python-powerdns \
    && pip3 install --no-cache-dir kombu \
    && pip3 install --no-cache-dir keystone \
    && pip3 install --no-cache-dir python-novaclient \
    && mkdir -p /opt/openstack-pdns-updater \
    && chown -R dragon: /opt/openstack-pdns-updater \
    && apt autoremove -y && apt clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

USER dragon

WORKDIR /opt/openstack-pdns-updater

COPY --chown=dragon openstack-pdns-updater.* environment* ca-certificates.crt* /opt/openstack-pdns-updater/

CMD [ "/opt/openstack-pdns-updater/openstack-pdns-updater.sh" ]
