# Azure CPU 데모 배포

현재 `platform-mvp` 구조를 바꾸지 않고 API, CPU 워커, SQLite, 영상을 한
Linux VM에 둔다. Flutter 웹은 API 이미지에 함께 빌드하고 Caddy가 동일
도메인 HTTPS를 제공한다.

## 1. VM 생성

Azure Cloud Shell(Bash)에서 실행한다. `DNS_LABEL`은 Azure 전체에서 고유해야
한다. 기본 크기는 4 vCPU/16 GiB인 `Standard_D4as_v5`이며, CPU 보정 속도가
부족하면 VM을 중지한 뒤 `Standard_D8as_v5`로 키운다.

```bash
RG=softreel-demo-rg
LOCATION=koreacentral
VM=softreel-demo-vm
ADMIN_USER=azureuser
DNS_LABEL=softreel-demo-고유문자열

# 해당 구독/리전에서 VM 크기가 보이는지 먼저 확인한다. 빈 배열이면
# Standard_D4s_v5 등 같은 4 vCPU/16 GiB 크기를 포털에서 확인해 대체한다.
az vm list-sizes --location "$LOCATION" \
  --query "[?name=='Standard_D4as_v5'].{name:name,cores:numberOfCores,memoryMb:memoryInMb}"

az group create --name "$RG" --location "$LOCATION"
az vm create \
  --resource-group "$RG" \
  --name "$VM" \
  --location "$LOCATION" \
  --image Ubuntu2404 \
  --size Standard_D4as_v5 \
  --admin-username "$ADMIN_USER" \
  --generate-ssh-keys \
  --public-ip-sku Standard \
  --public-ip-address-dns-name "$DNS_LABEL" \
  --os-disk-size-gb 128

az vm open-port --resource-group "$RG" --name "$VM" \
  --port 80 --priority 1001
az vm open-port --resource-group "$RG" --name "$VM" \
  --port 443 --priority 1002

FQDN=$(az vm show -d --resource-group "$RG" --name "$VM" \
  --query fqdns -o tsv)
echo "$FQDN"
ssh "$ADMIN_USER@$FQDN"
```

## 2. Docker와 애플리케이션 설치

VM의 SSH 터미널에서 실행한다.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
newgrp docker

git clone --branch main --single-branch \
  https://github.com/SKT-FLY-AI-9-6/gumchulgi.git
cd gumchulgi
cp deploy/azure/.env.example deploy/azure/.env
```

`deploy/azure/.env`에서 다음 세 값을 반드시 바꾼다.

- `PUBLIC_HOST`: 1단계에서 출력된 FQDN
- `JWT_SECRET`: `openssl rand -hex 48` 결과
- `ADMIN_EMAIL`, `ADMIN_PASSWORD`: 실제 관리자 계정과 강한 비밀번호

그다음 배포한다. 첫 빌드는 Flutter SDK와 Python 패키지를 받아 수 분 걸릴
수 있다.

```bash
docker compose -f deploy/azure/docker-compose.yml \
  --env-file deploy/azure/.env up -d --build
docker compose -f deploy/azure/docker-compose.yml ps
docker compose -f deploy/azure/docker-compose.yml logs -f api worker caddy
```

브라우저에서 `https://<PUBLIC_HOST>/`로 Flutter 웹, `/studio/`로 SoftReel
Studio, `/health`로 상태를 확인한다. Caddy가 80/443 포트를 통해 TLS 인증서를
자동 발급하므로 두 포트가 모두 열려 있어야 한다.

## 3. 업데이트와 백업

```bash
git pull --ff-only origin main
docker compose -f deploy/azure/docker-compose.yml \
  --env-file deploy/azure/.env up -d --build

docker run --rm \
  -v softreel-azure_softreel-data:/data \
  -v "$PWD":/backup alpine \
  tar czf /backup/softreel-data-backup.tgz -C /data .
```

SQLite와 영상은 `softreel-azure_softreel-data` Docker 볼륨에 함께 저장된다.
이 경로는 단일 VM 데모 전용이다. API나 워커를 여러 인스턴스로 늘리기 전에는
PostgreSQL, Blob Storage, Service Bus로 분리해야 한다.

## 4. 비용 중지

테스트를 쉬는 동안 VM을 할당 해제하면 컴퓨팅 과금이 중지된다.

```bash
az vm deallocate --resource-group "$RG" --name "$VM"
az vm start --resource-group "$RG" --name "$VM"
```

리소스 그룹 삭제는 VM, 디스크, Public IP를 함께 삭제하므로 데이터 백업 후에만
실행한다.
