ARG UBUNTU_RELEASE=24.04
FROM ubuntu:${UBUNTU_RELEASE}
LABEL maintainer="SEEBURGER AG (https://github.com/seeburger-ag/openstack-pdns-updater)"

USER root

ENV DEBIAN_FRONTEND=noninteractive

ARG USER_ID=45000
ARG GROUP_ID=45000
ENV USER_ID=${USER_ID}
ENV GROUP_ID=${GROUP_ID}

ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

ENV OS_CACERT=/opt/openstack-pdns-updater/ca-certificates.crt
ENV SKIP_DELETE=False

RUN apt update && apt dist-upgrade -y --autoremove --purge
RUN apt install -y git locales software-properties-common python3-pip libssl-dev python3-os-client-config python3-keystone python3-novaclient python3-kombu
RUN apt clean
RUN groupadd -g $GROUP_ID dragon \
    && useradd -g dragon -u $USER_ID -m -d /home/dragon dragon \
    && locale-gen en_US.UTF-8
RUN mkdir -p /opt/openstack-pdns-updater \
    && chown -R dragon: /opt/openstack-pdns-updater \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
RUN pip3 install python-powerdns --no-cache-dir --break-system-packages

USER dragon

WORKDIR /opt/openstack-pdns-updater

COPY --chown=dragon openstack-pdns-updater.* environment* ca-certificates.crt* /opt/openstack-pdns-updater/

CMD [ "/opt/openstack-pdns-updater/openstack-pdns-updater.sh" ]
