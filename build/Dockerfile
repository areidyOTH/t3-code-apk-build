# Official Node linux/amd64 manifest, verified from Docker Hub on 2026-10-10.
FROM node:24.21.0-bookworm@sha256:9af606de2e947cfb3f276633b7c5130c4cd22365aa10f5a647b7675d5cfce0c0
USER root
# Immutable Debian snapshot; the final image ID and package inventory are emitted.
RUN rm -f /etc/apt/sources.list.d/* && \
    printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261001T000000Z bookworm main\n' > /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends openjdk-17-jdk-headless python3 unzip ninja-build cmake pkg-config && \
    rm -rf /var/lib/apt/lists/*
ENV ANDROID_HOME=/opt/android ANDROID_SDK_ROOT=/opt/android JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
RUN curl -fL https://dl.google.com/android/repository/commandlinetools-linux-15859902_latest.zip -o /tmp/tools.zip && \
    echo '4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583  /tmp/tools.zip' | sha256sum -c - && \
    mkdir -p /opt/android/cmdline-tools && unzip -q /tmp/tools.zip -d /opt/android/cmdline-tools && \
    mv /opt/android/cmdline-tools/cmdline-tools /opt/android/cmdline-tools/pinned && rm /tmp/tools.zip && \
    yes | /opt/android/cmdline-tools/pinned/bin/sdkmanager --licenses >/dev/null
# Versions follow the frozen Expo/React Native recipe; no latest SDK selection.
RUN curl -fL https://dl.google.com/android/repository/build-tools_r37_linux.zip -o /tmp/build-tools.zip && \
    echo '01af179347cbcd9c208b7f8171f7b21f6dd1d2f85bcd15e88caa51d5d7b86060  /tmp/build-tools.zip' | sha256sum -c - && \
    unzip -q /tmp/build-tools.zip -d /tmp/build-tools && mkdir -p /opt/android/build-tools && \
    mv /tmp/build-tools/android-37.0 /opt/android/build-tools/37.0.0 && rm /tmp/build-tools.zip && \
    /opt/android/cmdline-tools/pinned/bin/sdkmanager 'platforms;android-37.0' 'ndk;27.1.12297006' 'cmake;3.22.1'
# Native libraries using AGP's default need 36 alongside the app's explicit 37.
# Verified against Google's repository metadata; SDK remains root-owned.
RUN curl -fL https://dl.google.com/android/repository/build-tools_r36_linux.zip -o /tmp/build-tools36.zip && \
    echo '5d9ac77fb6ff43d9da518a337b4fcf8f9097113df531d99ccefe80ef7ce8250b  /tmp/build-tools36.zip' | sha256sum -c - && \
    unzip -q /tmp/build-tools36.zip -d /tmp/build-tools36 && \
    mv /tmp/build-tools36/android-16 /opt/android/build-tools/36.0.0 && \
    rm /tmp/build-tools36.zip && rmdir /tmp/build-tools36
ENV ANDROID_NDK_HOME=/opt/android/ndk/27.1.12297006
ENV COREPACK_HOME=/opt/corepack
RUN curl -fL https://ziglang.org/download/0.15.2/zig-x86_64-linux-0.15.2.tar.xz -o /tmp/zig.tar.xz && \
    echo '02aa270f183da276e5b5920b1dac44a63f1a49e55050ebde3aecc9eb82f93239  /tmp/zig.tar.xz' | sha256sum -c - && \
    mkdir /opt/zig && tar -xJf /tmp/zig.tar.xz --strip-components=1 -C /opt/zig && rm /tmp/zig.tar.xz && \
    corepack enable && corepack prepare pnpm@11.10.0 --activate
ENV COREPACK_DEFAULT_TO_LATEST=0 COREPACK_ENABLE_NETWORK=0
ENV PATH=/opt/zig:/opt/android/build-tools/37.0.0:/opt/android/cmdline-tools/pinned/bin:$PATH
COPY container_build.py adapt.py unsigned.gradle public-environment.json /recipe/
RUN mkdir -p /work && chown node:node /work
USER node
WORKDIR /work
ENTRYPOINT ["python3", "/recipe/container_build.py"]
