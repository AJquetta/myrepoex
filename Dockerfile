FROM almalinux/9-minimal:latest

LABEL maintainer="AppThreat" \
      org.opencontainers.image.authors="Team AppThreat <cloud@appthreat.com>" \
      org.opencontainers.image.source="https://github.com/appthreat/dep-scan" \
      org.opencontainers.image.url="https://appthreat.io" \
      org.opencontainers.image.version="4.1.1" \
      org.opencontainers.image.vendor="appthreat" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.title="dep-scan" \
      org.opencontainers.image.description="Fully open-source security audit tool for project dependencies based on known vulnerabilities and advisories" \
      org.opencontainers.docker.cmd="docker run --rm -v /tmp:/tmp -p 7070:7070 -v $(pwd):/app:rw -t ghcr.io/appthreat/dep-scan --server"

ENV GOPATH=/opt/app-root/go \
    GO_VERSION=1.19.5 \
    SBT_VERSION=1.8.2 \
    GRADLE_VERSION=7.2 \
    GRADLE_HOME=/opt/gradle-${GRADLE_VERSION} \
    COMPOSER_ALLOW_SUPERUSER=1 \
    PATH=${PATH}:${GRADLE_HOME}/bin:${GOPATH}/bin:/usr/local/go/bin:/usr/local/bin/:/root/.local/bin: \
    PYTHONUNBUFFERED=1 \
    NVD_START_YEAR=2018 \
    GITHUB_PAGE_COUNT=2 \
    CDXGEN_CMD=cdxgen

RUN echo -e "[nodejs]\nname=nodejs\nstream=18\nprofiles=\nstate=enabled\n" > /etc/dnf/modules.d/nodejs.module \
    && microdnf install -y php php-curl php-zip php-bcmath php-json php-pear php-mbstring php-devel make gcc git-core python3 python3-pip ruby ruby-devel \
        pcre2 which tar zip unzip maven sudo java-11-openjdk-headless nodejs ncurses glibc-common glibc-all-langpacks xorg-x11-fonts-75dpi \
    && curl -LO https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-2/wkhtmltox-0.12.6.1-2.almalinux9.x86_64.rpm \
    && if [ "$TARGETPLATFORM" = "linux/amd64" ]; then rpm -ivh wkhtmltox-0.12.6.1-2.almalinux9.x86_64.rpm; fi \
    && rm wkhtmltox-0.12.6.1-2.almalinux9.x86_64.rpm \
    && npm install -g @cyclonedx/cdxgen \
    && python3 -m pip install --upgrade pip \
    && curl -LO "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" \
    && unzip -q gradle-${GRADLE_VERSION}-bin.zip -d /opt/ \
    && chmod +x /opt/gradle-${GRADLE_VERSION}/bin/gradle \
    && rm gradle-${GRADLE_VERSION}-bin.zip \
    && curl -LO "https://github.com/sbt/sbt/releases/download/v${SBT_VERSION}/sbt-${SBT_VERSION}.zip" \
    && unzip -q sbt-${SBT_VERSION}.zip -d /opt/ \
    && chmod +x /opt/sbt/bin/sbt \
    && rm sbt-${SBT_VERSION}.zip \
    && curl -LO "https://dl.google.com/go/go${GO_VERSION}.linux-amd64.tar.gz" \
    && tar -C /usr/local -xzf go${GO_VERSION}.linux-amd64.tar.gz \
    && rm go${GO_VERSION}.linux-amd64.tar.gz \
    && useradd -ms /bin/bash appthreat \
    && pecl channel-update pecl.php.net \
    && pecl install timezonedb \
    && echo 'extension=timezonedb.so' >> /etc/php.ini \
    && php -r "copy('https://getcomposer.org/installer', 'composer-setup.php');" && php composer-setup.php \
    && mv composer.phar /usr/local/bin/composer \
    && python3 -m pip install pipenv certifi

COPY . /opt/dep-scan

RUN cd /opt/dep-scan \
    && python3 -m pip install -e . \
    && rm -rf /var/cache/yum \
    && microdnf clean all

ENTRYPOINT [ "depscan" ]
