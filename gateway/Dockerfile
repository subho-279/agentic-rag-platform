FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml .
RUN mvn -B -q dependency:go-offline
COPY src ./src
RUN mvn -B -q package -DskipTests

FROM eclipse-temurin:21-jre
# curl is used by the compose healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
# Run as numeric uid 1000 (same as the python image) so the shared uploads volume has one owner.
# Ubuntu-based Temurin images already define uid 1000 ("ubuntu"), so don't try to create another user.
RUN mkdir -p /data/uploads && chown 1000:1000 /data/uploads
USER 1000:1000
WORKDIR /app
COPY --from=build /build/target/gateway-0.1.0.jar app.jar
EXPOSE 8080
# Size the heap from the container's memory limit (docker-compose.prod.yml sets one).
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "app.jar"]
