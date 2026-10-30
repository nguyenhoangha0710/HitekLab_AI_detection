# Dockerfile mau cho Backend API (.NET 8): Backend API, IoT Service, Event & Risk Engine.
# Dat toan bo source .NET vao code/backend/ roi build bang docker compose.
#
#   BACKEND_PROJECT: duong dan file .csproj cua project Web API, tinh tu code/backend/
#   BACKEND_DLL    : ten file .dll sau khi publish (thuong = ten project + .dll)
#
# Hai gia tri nay khai bao trong .env (xem .env.example), khong can sua file nay.

FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
ARG BACKEND_PROJECT=Backend.Api/Backend.Api.csproj
WORKDIR /src

# Copy source, kiem tra co project, restore va publish.
COPY . .
RUN test -f "${BACKEND_PROJECT}" || { \
      echo "LOI: khong thay ${BACKEND_PROJECT} trong code/backend/."; \
      echo "Chua co code Backend -> bo 'backend' khoi COMPOSE_PROFILES trong .env, hoac dat BACKEND_PROJECT dung duong dan .csproj."; \
      echo "Xem code/backend/README.md"; exit 1; }
RUN dotnet restore "${BACKEND_PROJECT}"
RUN dotnet publish "${BACKEND_PROJECT}" -c Release -o /app/publish /p:UseAppHost=false --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
ARG BACKEND_DLL=Backend.Api.dll
ENV BACKEND_DLL=${BACKEND_DLL} \
    ASPNETCORE_URLS=http://+:5250 \
    ASPNETCORE_ENVIRONMENT=Development
WORKDIR /app
COPY --from=build /app/publish .

EXPOSE 5250
ENTRYPOINT ["sh", "-c", "exec dotnet \"$BACKEND_DLL\""]
