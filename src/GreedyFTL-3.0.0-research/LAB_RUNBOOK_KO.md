# Cosmos+ 실험실 실행 매뉴얼: 노트북에서 빌드, Host PC에서 측정

기준: 2026-10-05 코드. 보드 구동은 이미 확인된 기존 Vivado/SDK 2019.1 프로젝트를 사용한다.
저장소: https://github.com/sungjw0408/greedy-FTL-allocation-policy
기존 저장소 파일을 보존하기 위해 새 코드는 `experiment-kit-20261005/` 하위에 넣는다.
이 문서의 명령은 그 폴더 안에서 실행한다. 옛 20261002 패키지와 혼용하지 않는다.

실제 ARM 빌드/링크, Windows JTAG/COM, 보드 NAND/PCIe는 이 패키지로 실물 검증하지 않았다.
각 단계의 통과 조건을 만족하지 않으면 다음 단계의 쓰기 실험으로 넘어가지 않는다.
장치 이름, 실제 SDK 경로, COM/IP는 현장에서 확인해 placeholder를 바꿔야 한다.

## 0. 장비 역할과 먼저 알아둘 주의점

| 장비 | 연결과 역할 | 적용할 코드/도구 |
|---|---|---|
| Windows 노트북 | JTAG로 보드 다운로드, USB-UART로 부팅/로그 수신 | 기존 SDK 프로젝트에 펌웨어 적용, uart_bridge.py |
| Cosmos+ 보드 | NAND를 제어하며 PCIe NVMe SSD로 동작 | 정책별 ARM ELF |
| Linux Host PC | PCIe로 보드에 I/O 전송 | fio, nvme-cli, experiment.py, analyze.py |

가이드대로 UART는 노트북에 연결한다. 실험 때는 SDK Terminal의 COM 연결만 끊고,
노트북의 bridge가 받은 UART를 사설 LAN으로 Host PC에 전달한다.
Host 명령의 `--serial`은 `socket://노트북IPv4:8765`가 된다. JTAG는 노트북에 유지한다.
bridge는 UART에 데이터를 쓰지 않으며, Host는 장치 명령을 PCIe로 보낸다.

필수 안전 조건:

- 보드 전체를 폐기 가능한 실험용 SSD로 사용할 권한이 있어야 한다. 기존 데이터는 먼저 백업한다.
  **이 코드의 FTL 초기화 자체가 사용자 NAND 영역을 지운다. fio 실행 전뿐 아니라 펌웨어 Run 전부터 주의한다.**
- `X`는 bad-block table(BBT)까지 다시 만드는 전체 소거 경로다. 일반 반복 실험의 초기화와 구분한다.
- 이번 실험은 raw namespace 실험이다. Quick Guide의 `fdisk`, `mkfs`, `mount` 실습은 하지 않는다.
  `nvme format`, `blkdiscard`, Write Zeroes도 실행하지 않는다.
- FULL 가이드에서 Write Zeroes를 FLUSH case에 넣는 우회 방법은 적용하지 않는다.
  두 명령의 의미가 다르며, 이번 실험은 READ/WRITE/FLUSH만 사용한다.
- OS SSD와 Cosmos+를 반드시 구별한다. /dev/nvme0n1로 고정하지 않는다.
- 노트북과 Host는 통신 가능한 신뢰할 수 있는 사설 LAN에 둔다.
  bridge는 암호화/암호 인증이 없으므로 외부 공개, 포트포워딩, 공용망에서 사용하지 않는다.
  허용 Host IP와 Windows 방화벽을 모두 제한한다. LAN이 없으면 16절의 UART 직접 연결 대안을 사용한다.
- 실험 중 다른 DUT I/O, mount, 펌웨어 reset/Run, FPGA 재program, COM 중복 접속을 하지 않는다.
- 기존 hardware/BSP를 새로 만들거나 OS/kernel을 무작정 업그레이드하지 않는다.
  Ubuntu 버전은 아직 미확인이므로 Host에서 먼저 확인한다.

## 1. 준비하는 PC에서 GitHub에 새 코드 올리기

새 ZIP을 풀어 `GreedyFTL-3.0.0-research`의 내용을 준비한다.
Git과 GitHub CLI가 설치된 터미널에서:

```bash
gh auth login
gh auth setup-git
git clone https://github.com/sungjw0408/greedy-FTL-allocation-policy.git openssd-upload
cd openssd-upload
git status --short
```

이 clone 안에 **새 폴더 `experiment-kit-20261005`**를 만들고, 압축을 푼 소스 폴더의 내용을 넣는다.
`experiment-kit-20261005/host/experiment.py`가 되도록 한다.
폴더가 한 단계 더 중첩되지 않게 하고 `.gitignore`도 포함한다. 기존 파일은 덮어쓰지 않는다.
이미 같은 이름의 폴더가 있다면 기존 변경을 확인하고 별도 새 버전명으로 관리한다.
교재 PDF, FPGA license, 인증 토큰, 연구실 비밀번호는 업로드하지 않는다.

본인 커밋 정보를 설정하고 올린다:

```bash
git config user.name "본인 이름"
git config user.email "본인 커밋용 이메일"
git add -- experiment-kit-20261005
git diff --cached --stat
git status
git commit -m "Add Cosmos+ lab experiment kit 2026-10-05"
git push
```

commit 전 다른 사람/작업의 변경이 stage되어 있으면 먼저 정리 방법을 확인한다.
기존 저장소를 git init으로 다시 만들거나 force push하지 않는다.
GitHub에서 새 폴더와 `host/uart_bridge.py`, `tools/apply_sdk_sources.py`, 이 문서가 보이는지 확인한다.
단순히 ZIP 파일만 올리는 것이 아니라 내부 소스를 올린다.
결과 로그/ELF는 기본 .gitignore에서 제외되므로 나중에 별도 백업해야 한다.

## 2. Windows 노트북에 코드 준비

이미 설치된 Git/Python/GitHub CLI를 사용해도 된다. 없고 winget이 있는 Windows라면 설치 예:

```powershell
winget install --exact --id Git.Git
winget install --exact --id GitHub.cli
winget install --exact --id Python.Python.3.11
```

설치 뒤 PowerShell을 새로 연다. Vivado/SDK는 이미 동작하는 2019.1을 유지한다.

```powershell
git --version
gh --version
py -3 --version
gh auth login
gh auth setup-git
New-Item -ItemType Directory -Force C:\OpenSSD
git clone https://github.com/sungjw0408/greedy-FTL-allocation-policy.git C:\OpenSSD\repo
Set-Location C:\OpenSSD\repo\experiment-kit-20261005
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install "pyserial>=3.5,<4"
git rev-parse HEAD
git status --short
```

이미 clone했다면 미저장 변경이 없는지 확인한 뒤 `git pull --ff-only`를 사용한다.
venv를 activate하지 않고 python.exe를 직접 쓰므로 PowerShell 실행 정책을 변경할 필요가 없다.
노트북에서는 fio/NVMe 벤치마크를 실행하지 않는다.

## 3. 기존 SDK 프로젝트 백업 및 소스 적용

노트북에서 이미 동작하는 Vivado 프로젝트를 열고 File > Launch SDK.
Project Explorer의 `run-gftl3/src`에서 실제 파일 위치를 확인한다.
SDK/application 전체를 먼저 별도 폴더에 백업한다. bitstream/HDF/BSP도 보존한다.
이 패키지 자체를 BSP로 import하거나 새 hardware 프로젝트로 사용하지 않는다.

PowerShell에서 다음 변수의 SDK 경로만 실제 위치로 바꾼다:

```powershell
$Repo = 'C:\OpenSSD\repo\experiment-kit-20261005'
$SdkProject = 'C:\REPLACE_WITH_ACTUAL_SDK_WORKSPACE\run-gftl3'
$SdkSrc = Join-Path $SdkProject 'src'
Set-Location $Repo
Test-Path (Join-Path $SdkSrc 'address_translation.c')
Test-Path (Join-Path $SdkSrc 'ftl_config.h')
Test-Path (Join-Path $SdkSrc 'nvme\nvme_io_cmd.c')
```

모두 True여야 한다. SDK source root가 다른 구조면 실제 source 위치를 지정한다.
SDK 자동 build를 잠시 끄고, 우선 차이만 생성한다:

```powershell
.\.venv\Scripts\python.exe tools\apply_sdk_sources.py --sdk-src "$SdkSrc" --report C:\OpenSSD\preview-20261005
notepad C:\OpenSSD\preview-20261005\changes.diff
```

`PREVIEW ONLY; SDK unchanged`면 아직 SDK 소스는 그대로다.
기존 보드용 수정이 사라지는 차이가 없는지 확인한다. 표준 GreedyFTL과 크게 다르거나
hardware 의존 변경이 섞여 있으면 중단하고 개별 merge한다. 무조건 덮어쓰지 않는다.

검토 후 적용:

```powershell
.\.venv\Scripts\python.exe tools\apply_sdk_sources.py --sdk-src "$SdkSrc" --report C:\OpenSSD\backup-20261005 --apply --confirm-reviewed-diff
```

도구는 모든 기존 대상 파일을 `backup-20261005\originals\`에 백업한 후 복사한다.
preview/backup은 새 폴더여야 한다. 재적용이면 날짜/번호가 다른 이름을 사용한다.
17개 연구 변경 파일만 적용하며 다음은 덮어쓰지 않는다:

```text
ftl_config.h / main.c / memory_map.h / nsc_driver.*
linker script / BSP / FPGA 설계와 bitstream
```

이 보존 파일과 연구 소스의 호환성은 SDK build와 보드 검증이 필요하다.
SDK에서 F5/Refresh하고 `research_stats.c`가 실제 build에 포함되는지 확인한다.
새 allocation_policy.h, research_config.h, research_stats.h도 src에 있어야 한다.
host/tests/tools/fio는 SDK source에 넣지 않는다. tests/bsp_stubs는 실제 BSP가 아니다.

## 4. 보드 설정과 RAM 경계 확인

기존 `ftl_config.h`에서 다음 값과 실제 hardware/BSP/NAND를 대조하고 전 정책에서 고정한다:

```text
NUMBER_OF_CONNECTED_CHANNEL, USER_CHANNELS, USER_WAYS
BITS_PER_FLASH_CELL (SLC/MLC), USER_BLOCKS_PER_LUN
```

FULL 가이드에는 connected channel=4 예시가 있지만 실제 배선 확인 없이 4Ch/8Way로 단정하지 않는다.
우선 실험실에서 동작하던 설정을 보존한다. NAND ID가 없는 Way, geometry 불일치, configuration
restriction 오류가 있으면 중단한다. 호스트에서 출력하는 통계로 실제 geometry도 확인한다.

실제 사용하는 lscript.ld와 main.c의 memory layout을 확인한다.
이 연구 소스의 기본 layout은 firmware 0x00100000-0x001FFFFF, NVMe management 시작0x00200000이다.
같은 layout이라면 `_end = .;` 뒤, SECTIONS의 마지막 `}` 전에 다음을 추가한다:

```text
ASSERT(_end <= 0x00200000, "Firmware exceeds 1 MiB management segment")
```

다른 layout이면 그대로 복사하지 말고 실제 경계를 검토한다. ASSERT 실패를 삭제해서 우회하지 않는다.
trace buffer/heap/stack을 포함한 link map을 확인한다. 새 구조체 때문에 request pool/table 주소도
sizeof 기반 계산과 정렬이 맞는지 확인한다. 기존 linker script 전체를 무조건 교체하지 않는다.

## 5. 정책별 ELF 만들기

SDK 프로젝트 Properties > C/C++ Build > Settings의 ARM compiler Symbols/Defined symbols(-D)에 설정.
SDK 화면 이름은 구성에 따라 조금 다를 수 있다. Symbols 입력칸에는 앞의 -D 없이 이름만 넣는다.
처음 Channel-first 할당 검증용:

```text
ALLOCATION_POLICY_CHANNEL_FIRST
ALLOCATION_TRACE_COUNT=512
RESEARCH_TRACE_LEVEL=1
RESEARCH_TRACE_CAPACITY=2048
```

ALLOCATION_POLICY_*는 항상 하나만 정의한다. 검증 후 지연시간 측정용 설정:

```text
ALLOCATION_TRACE_COUNT=0
RESEARCH_TRACE_LEVEL=1
RESEARCH_TRACE_CAPACITY=2048
```

정책 macro는 Channel-first/Way-first/Page-first 중 하나만 사용:

```text
ALLOCATION_POLICY_CHANNEL_FIRST
ALLOCATION_POLICY_WAY_FIRST
ALLOCATION_POLICY_PAGE_FIRST
```

모든 정책에 같은 optimization/Debug 또는 Release 설정을 사용한다.
Clean All 후 Build Project/Build All을 실행해 **마지막은 build로 끝낸다**.
가이드대로 clean만 마지막에 하면 ELF가 삭제되거나 오래된 파일을 선택할 수 있으므로 생성 시각을 확인한다.
Console Errors=0, research_stats.c compile, link map/RAM boundary, 경고 내용을 확인한다.

실제 SDK 출력 ELF 경로를 Console/Run Configuration에서 확인한 뒤 저장:

```powershell
$SdkElf = Join-Path $SdkProject 'Debug\run-gftl3.elf'
Get-Item "$SdkElf"
New-Item -ItemType Directory -Force "$Repo\firmware"
Copy-Item "$SdkElf" "$Repo\firmware\channel-first-allocation.elf"
Get-FileHash "$Repo\firmware\channel-first-allocation.elf" -Algorithm SHA256
```

Debug/run-gftl3.elf는 예시다. 실제 build 출력 파일을 지정한다.
trace count를0으로 바꿔 재Clean/Build하고 channel-first.elf로 별도 보관한다.
나머지 정책도 macro만 바꿔 각각 검증용/측정용 ELF를 만든다:

```text
firmware/channel-first-allocation.elf   firmware/channel-first.elf
firmware/way-first-allocation.elf       firmware/way-first.elf
firmware/page-first-allocation.elf      firmware/page-first.elf
```

Build All 한 번으로 세 정책이 자동 생성되지 않는다. 변경→Clean/Build→별도 이름 저장을 반복한다.
각 ELF의 compiler symbols/optimization, board ftl_config.h, BSP/HDF/bitstream 버전, commit을 보관한다.
소프트웨어 정책만 바꾸는 매번 Vivado synthesis/implementation을 다시 할 필요는 없다.
hardware를 바꿀 때만 matching bitstream/HDF/BSP를 재생성해야 한다.

## 6. 가이드대로 보드 부팅: Host PC는 아직 OFF

다른 이용자/작업이 없는지 확인한 뒤 필요하면 Host에서 `sudo shutdown -h now`로 종료한다.
장비 연결/전원 조작은 연구실의 전원OFF 안전 절차를 따른다.

1. PCIe는 보드-Host PC, JTAG와 USB-UART는 보드-노트북에 연결한다.
2. 보드 전원ON, SDK Terminal을 실제 UART COM으로 연결한다. COM3은 가이드의 예시다.
   115200 baud, 8 data bits, 1 stop bit, parity none, flow control none.
3. Run Configuration의 ELF/bitstream/PS 초기화가 이번 정책과 일치하는지 확인한다.
   저장한 다른 ELF가 아니라 현재 Debug ELF를 선택한다면 그 파일을 마지막으로 어떤 macro로
   build했는지 확인한다. 가능하면 이번 실험용 저장 ELF를 명시적으로 선택한다.
4. 가이드의 Run 실행, `[NAND device reset complete]`와 입력 prompt를 기다린다.
5. 첫 설치에서 BBT 재작성과 전체 소거가 허용된 경우 가이드의 X+Enter를 사용한다.
   반복 실험에서 기존 BBT를 보존하려면 해당 prompt에서 X 이외(예: Enter)를 보내는 경로를 쓸 수 있다.
   **두 경로 모두 이 코드에서는 사용자 영역을 지운다. 소거 중 전원을 끊지 않는다.**
6. `FTL reset complete` / `Turn on the host PC`가 나온 뒤 Host PC를 켠다.

차이는 address_translation.c::InitBlockDieMap()에 있다. 초기화/BBT 규칙을 전 정책에서 동일하게 적용하고 기록한다.
반복 때 임의로 BBT를 재작성하여 마모/초기조건이 달라지지 않도록 한다.

## 7. Linux Host 준비: 첫 한 번

보드 연결 전 OS SSD에서 준비해도 된다. Ubuntu 버전과 Python을 먼저 확인한다:

```bash
cat /etc/os-release
python3 --version
```

아래는 Ubuntu22.04 계열 예시이며 Python3.9+가 필요하다. 오래된 OS에서 조건이 안 맞으면
그 지점에서 멈추고 환경을 확인한다. 검증된 Host kernel을 무단으로 교체하지 않는다.

```bash
sudo apt update
sudo apt install git gh fio nvme-cli python3-venv build-essential pciutils openssh-server
gh auth login
gh auth setup-git
git clone https://github.com/sungjw0408/greedy-FTL-allocation-policy.git openssd-research
cd openssd-research/experiment-kit-20261005
python3 -c 'import sys; assert sys.version_info >= (3,9), "Python 3.9+ required"'
python3 -m venv .venv
.venv/bin/pip install -r host/requirements.txt
python3 tools/check_host.py
fio --version
nvme version
git rev-parse HEAD
git status --short
mkdir -p firmware results
```

Linux Host에는 Vivado/SDK가 필요 없다. 두 PC clone의 commit을 확인하고 실험 중에는 같은 버전으로 고정한다.
이미 clone한 경우 로컬 변경부터 확인하고 git pull --ff-only. 공용 PC의 개인 로그인 정보도 관리한다.
GitHub CLI를 설치할 수 없다면 GitHub에서 소스 ZIP을 받을 수 있지만 commit 식별자를 별도로 기록한다.

## 8. 실제 ELF를 Host에 복사

Host 터미널에서 사용자/현재 소스 위치/IP 확인:

```bash
whoami
pwd
hostname -I
```

노트북에서 Host의 현재 소스 폴더 아래 firmware/로 ELF를 복사한다. USB 복사도 가능하다.
SSH가 연구실에서 허용된 경우 Windows PowerShell 예시(사용자/IP/실제 home 경로는 교체):

```powershell
Set-Location C:\OpenSSD\repo\experiment-kit-20261005
scp .\firmware\*.elf HOST_USER@HOST_IP:/home/HOST_USER/openssd-research/experiment-kit-20261005/firmware/
```

Host에서 hash 확인:

```bash
sha256sum firmware/*.elf
```

Windows Get-FileHash와 일치해야 한다. --firmware-elf는 이 파일의 hash 기록용이며 보드 다운로드 명령이 아니다.
실제로 JTAG로 다운로드한 ELF와 정확히 같은 파일을 지정한다.

## 9. DUT namespace 확인 및 공통 변수 설정

Host PC에서 읽기 확인 명령:

```bash
lspci -nn
sudo nvme list
lsblk -o NAME,SIZE,MODEL,SERIAL,FSTYPE,MOUNTPOINTS
findmnt /
```

가이드의 Xilinx Non-Volatile memory controller Device7028을 확인한다.
OS SSD가 아닌 Cosmos namespace/controller를 PCIe/sysfs와 대조한다. /dev/nvme0n1 또는 nvme1n1 등 실제 값을 쓴다.
아래 세 placeholder를 현장의 값으로 바꾼 뒤 같은 터미널에서 실행한다:

```bash
LAB_DUT='/dev/REPLACE_WITH_COSMOS_NAMESPACE'
LAB_CTRL='/dev/REPLACE_WITH_COSMOS_CONTROLLER'
LAB_LAPTOP_IP='REPLACE_WITH_LAPTOP_PRIVATE_IPV4'
LAB_UART="socket://${LAB_LAPTOP_IP}:8765"
```

예: DUT=/dev/nvme1n1이면 CTRL=/dev/nvme1. 새 터미널/재부팅 후에는 변수도 다시 설정한다.
placeholder 상태로 다음 명령을 실행하지 않는다.

```bash
readlink -f "/sys/class/block/$(basename "$LAB_DUT")/device"
readlink -f "/sys/class/nvme/$(basename "$LAB_CTRL")/device"
cat "/sys/class/nvme/$(basename "$LAB_CTRL")/device/vendor"
cat "/sys/class/nvme/$(basename "$LAB_CTRL")/device/device"
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS "$LAB_DUT"
swapon --show
ls -l "/sys/class/block/$(basename "$LAB_DUT")/holders"
sudo fuser -v "$LAB_DUT"
```

가이드 기준 vendor/device는0x10ee/0x7028이고 runner도 이 값을 확인한다.
다르면 OS SSD 오지정/다른 bitstream을 먼저 조사한다. 경고 무시를 위해 PCI ID를 바꾸지 않는다.
실제 Cosmos bitstream의 ID가 다르다고 확인된 경우에만 --expected-pci-id를 지정한다.

mount되어 있다면 확인된 테스트 파티션만 unmount. 설명용 placeholder 명령:

```bash
sudo umount /dev/CONFIRMED_COSMOS_PARTITION
```

모든 NVMe/OS disk를 unmount하지 않는다. swap/RAID/device-mapper가 있으면 관리자의 확인이 필요하다.
runner도 mount/swap/holder를 검사하지만 DUT 식별 책임을 대신하지 않는다.
파일 관리자에서 DUT를 mount하지 않고, 로그는 Host의 OS SSD에 저장한다.

## 10. 노트북 UART bridge 시작

보드 초기화가 끝난 뒤 SDK Terminal의 COM 연결만 Disconnect한다. SDK/펌웨어 자체를 중단하지 않는다.
SDK Terminal과 bridge는 같은 COM을 동시에 열 수 없다.
Windows PowerShell에서:

```powershell
Set-Location C:\OpenSSD\repo\experiment-kit-20261005
ipconfig
.\.venv\Scripts\python.exe -m serial.tools.list_ports
```

실제 노트북/Host의 사설 IPv4, 부팅에 사용한 UART COM으로 다음을 바꾼다:

```powershell
$LaptopIP = 'REPLACE_WITH_LAPTOP_PRIVATE_IPV4'
$HostIP = 'REPLACE_WITH_HOST_PRIVATE_IPV4'
$BoardCOM = 'REPLACE_WITH_UART_COM_PORT'
```

필요한 경우만, 관리자 PowerShell에서 이 Host에 한정한 Private network 방화벽 규칙을 추가한다.
새 관리자 창의 변수는 다른 창과 공유되지 않으므로 그 창에서도 $LaptopIP/$HostIP를 실제 값으로 다시 설정한다:

```powershell
New-NetFirewallRule -DisplayName 'OpenSSD UART Bridge 8765' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -LocalAddress "$LaptopIP" -RemoteAddress "$HostIP" -Profile Private
```

방화벽 전체를 끄거나 Public network에 열지 않는다. 일반 PowerShell에서 bridge 실행:

```powershell
.\.venv\Scripts\python.exe host\uart_bridge.py --port "$BoardCOM" --baud 115200 --bind "$LaptopIP" --client-ip "$HostIP" --tcp-port 8765
```

`Read-only bridge`면 대기 시작. 이 창은 계속 열어 둔다.
Host 실행 시 Host connected, 종료 시 disconnected가 나오는 것은 정상이다.
bridge는 여러 실행 사이에 계속 유지할 수 있다. TCP 데이터가 UART에 쓰이지 않으며 X 입력도 할 수 없다.
실행 중 다른 miniterm/SDK Terminal/socket 접속을 하지 않는다.

## 11. UART/펌웨어 확인

Host에서 새 output 이름으로 실행:

```bash
sudo .venv/bin/python host/experiment.py \
  --namespace "$LAB_DUT" --controller "$LAB_CTRL" --serial "$LAB_UART" \
  --policy channel-first --phase inspect --size-bytes 67108864 \
  --output results/channel-first-inspect \
  --execute --allow-device "$LAB_DUT"
```

inspect는 새로운 fio write를 하지 않지만 initial FLUSH와 C1 통계를 실행한다.
기존 dirty buffer를 기록할 수 있으므로 엄밀히 read-only인 명령은 아니다.
schema=2, actual policy=channel-first, 실제 channels/ways/pages가 JSON으로 출력되어야 한다.
명령에 입력한 정책 라벨이 아니라 actual firmware stats를 확인한다.
timeout/schema/정책 불일치/ASSERT가 있으면 COM/IP/방화벽/ELF/SDK 적용 대상부터 확인하고 중단한다.

## 12. 각 정책의 실제 allocation 검증

fresh 보드에 해당 *-allocation.elf(TRACE_COUNT=512)를 Run하고 6-11절까지 완료한 상태에서,
다른 쓰기 workload보다 먼저 실행한다. Channel-first 예:

```bash
sudo .venv/bin/python host/experiment.py \
  --namespace "$LAB_DUT" --controller "$LAB_CTRL" --serial "$LAB_UART" \
  --policy channel-first --phase allocation --size-bytes 67108864 \
  --firmware-elf firmware/channel-first-allocation.elf \
  --output results/channel-first-allocation-check \
  --execute --allow-device "$LAB_DUT"

.venv/bin/python tools/check_allocation_trace.py \
  results/channel-first-allocation-check/uart.log \
  --policy channel-first \
  --stats results/channel-first-allocation-check/allocation.stats.txt
```

64MiB sequential write와 FLUSH를 수행하는 파괴적 검증이다. PASS를 확인한다.
stats에서 실제 geometry를 가져오므로 임의로4/8/128을 넣지 않는다.
최초 n=0 누락, 정책/순서/페이지 증가/블록 전환이 다르면 실패한다.
Page-first 검증 trace 길이는 USER_PAGES_PER_BLOCK보다 커야 한다.
Way-first/Page-first는 policy, ELF, output만 바꿔 같은 검증을 한다.

검증 후 Host 종료→bridge Ctrl+C→TRACE_COUNT=0인 측정 ELF로 Run→fresh 초기화→Host 부팅→bridge 재개.
검증에서 쓴 데이터를 남긴 상태로 본 측정을 시작하지 않는다.

## 13. FLUSH와 데이터 검증

측정용 ELF(TRACE_COUNT=0)로 부팅한 뒤:

```bash
sudo .venv/bin/python host/experiment.py \
  --namespace "$LAB_DUT" --controller "$LAB_CTRL" --serial "$LAB_UART" \
  --policy channel-first --phase verify --size-bytes 67108864 \
  --firmware-elf firmware/channel-first.elf \
  --output results/channel-first-integrity \
  --execute --allow-device "$LAB_DUT"

.venv/bin/python -m json.tool results/channel-first-integrity/manifest.json
```

CRC32C write→FLUSH→검증 read. integrity_verified=true, fio error=0, NAND failure=0 확인 후 진행한다.
verify-read.fio에는 rw=write/verify_only=1이 있지만 fio의 verify_only는 원래 쓰기를 반복하지 않고 검증 읽기를 한다.
64MiB는 현재 최대64Die 기본 data cache16MiB보다 큰 범위다. cache를 변경했다면 범위도 검토한다.
전원 차단/재부팅 후 데이터 복구 검증이 아니다. 데이터 불일치가 있으면 성능 결과로 사용하지 않는다.

## 14. pilot 및 본 실험

최초 비교 부하 후보:

```text
writer: 16KiB random write, 4 threads × QD8 (최대32 outstanding)
probe: 4KiB random read, 1 thread × QD1, rate cap1000 IOPS
전처리: sequential fill + random overwrite2 pass 상당 write량
warmup30초, 측정120초; seed 동일
주소 범위: 아래에서 구한 전체 namespace의16KiB 정렬 범위
```

20GiB 예시는 큰 보드에서 GC를 발생시키지 못할 수 있다. 여기서는 pilot 후보로 전체 exported namespace를 사용한다.
총 쓰기량/소요 시간/마모가 크므로 연구실의 사용 허가를 확인한다. 범위를 줄이면 GC 여부를 다시 검증한다.
보드 capacity/OP 자체를 줄이는 펌웨어 변경은 별도의 실험 설계이며 이 매뉴얼에서는 자동 변경하지 않는다.

```bash
LAB_CAPACITY=$(sudo blockdev --getsize64 "$LAB_DUT")
LAB_SIZE=$((LAB_CAPACITY / 16384 * 16384))
printf 'Capacity=%s bytes; workload size=%s bytes\n' "$LAB_CAPACITY" "$LAB_SIZE"
```

검증/pilot 후마다 동일 초기화부터 시작한다. C0 counter reset은 NAND 초기화가 아니다.
전 정책에서 size/seed/runtime/jobs/QD/전처리 규칙을 동일하게 고정한다.
rate_iops는 open-loop 도착 보장이 아닌 cap이다. 실제 달성 IOPS를 함께 확인한다.
uncapped writer는 정책별 write량/GC 빈도가 달라질 수 있다. 고정 부하 추가 비교에서는
pilot에서 정한 동일 --writer-iops를 전 정책에 적용한다(한 thread당 cap).

### 장치를 쓰지 않고 계획 생성

```bash
.venv/bin/python host/experiment.py \
  --namespace "$LAB_DUT" --controller "$LAB_CTRL" --serial "$LAB_UART" \
  --policy channel-first --mode gc --phase all --size-bytes "$LAB_SIZE" \
  --writer-jobs 4 --writer-qd 8 --worker-model threads \
  --probe-iops 1000 --probe-qd 1 --runtime 120 \
  --overwrite-passes 2 --warmup-seconds 30 --seed 20261005 \
  --output results/channel-first-plan

fio --parse-only results/channel-first-plan/measure.fio
```

--execute가 없으면 장치 command를 실행하지 않는다. .fio를 확인한다.
실제 runner도 쓰기 전에 모든 job을 parse-only로 검사한다. 기존 코드의 신규fio 전용
log_issue_time 옵션은 제거하여 fio3.28/3.33에서 해당 옵션으로 실패하는 문제를 피했다.

### pilot

아래 본 실험 command와 같은 내용으로 output만 results/channel-first-pilot-r1로 바꿔 실행한다.
GC 발생, 총 시간, IOPS/GC율/migration 양의 안정성, trace overflow를 확인한다.
GC가 한 번 발생했다고 steady state가 보장되는 것은 아니다. 필요하면 overwrite/warmup을 조절하여
전 정책에 같은 조건을 다시 적용한다. pilot 완료 후 fresh 초기화부터 본 실험을 시작한다.

### Channel-first 본 실험

```bash
sudo .venv/bin/python host/experiment.py \
  --namespace "$LAB_DUT" --controller "$LAB_CTRL" --serial "$LAB_UART" \
  --policy channel-first --mode gc --phase all --size-bytes "$LAB_SIZE" \
  --writer-jobs 4 --writer-qd 8 --worker-model threads \
  --probe-iops 1000 --probe-qd 1 --runtime 120 \
  --overwrite-passes 2 --warmup-seconds 30 --seed 20261005 --repeat 1 \
  --firmware-elf firmware/channel-first.elf \
  --output results/channel-first-gc-r1 \
  --execute --allow-device "$LAB_DUT"
```

실행 내부 순서:

```text
PCI ID/용량/mount/swap/holder/fio 설정 검사
→ UART 연결 → initial FLUSH → 실제 firmware schema/정책 검사
→ sequential fill → FLUSH → random overwrite2 pass → FLUSH
→ 별도 warmup30초 → FLUSH → C0 통계 초기화 → C2 START
→ writer+read probe 동시120초 (stonewall 없음)
→ C2 END → 이미 생성된 NAND 완료 → window 통계
→ 마지막 dirty buffer FLUSH → drained 통계 → C3 이벤트 출력/로그 저장
→ GC/NAND error 검증 → manifest 저장
```

전체 소요 시간은120초가 아니다. fill/overwrite가 보드 용량/속도에 따라 매우 오래 걸릴 수 있다.
fio의 stdout은 파일에 저장되므로 화면이 조용할 수 있다. 다른 Host 터미널에서 진행 확인:

```bash
pgrep -a fio
ls -lh results/channel-first-gc-r1
tail -n 15 results/channel-first-gc-r1/uart.log
```

추가 DUT I/O를 하지 않는 확인이다. 측정 중 별도 C1/C3 통계 출력 명령을 보내지 않는다.
중단/오류 run은 무효로 보존하고 새 output 이름으로 재시작한다. 결과 폴더는 삭제/재사용하지 않는다.

### Way-first, Page-first와 반복

매 정책/독립 반복마다 종료 후 Host shutdown→bridge 종료→다음 ELF Run→동일 초기화→
Host boot→DUT명/IP 재확인→변수 재설정→bridge 재개한다. 재부팅으로 DUT명이 바뀔 수 있다.
9절의 공통 변수와 14절의 LAB_CAPACITY/LAB_SIZE도 매번 다시 계산한다.
상단 command의 다음 세 항목을 반드시 같이 바꾼다:

| policy | firmware-elf | output |
|---|---|---|
| channel-first | firmware/channel-first.elf | results/channel-first-gc-r1 |
| way-first | firmware/way-first.elf | results/way-first-gc-r1 |
| page-first | firmware/page-first.elf | results/page-first-gc-r1 |

반복2는 `--repeat 2`와 output r2를 지정한다. repeat은 자동 loop가 아닌 식별자다.
각 정책3-5회부터 시작하여 필요한 정밀도에 맞게 늘린다. 순서를 교차 배치하고 온도/시각을 기록한다.
한 정책 실행 결과가 나왔다고 다른 정책을 Host command로만 바꾸면 안 된다. ELF부터 바꿔야 한다.

## 15. No-GC reference, 성공 판정, 그래프

### read-only No-GC reference

동일 fresh 초기화/전처리/size/seed로 본 command의 --mode를 baseline,
output을 results/channel-first-baseline-r1로 바꾼다. 전처리는 쓰기지만 측정에는 read probe만 있다.
runner가 측정구간 GC count=0인지 확인한다. 전 정책에서 동일 방식으로 실시할 수 있다.
writer가 없으므로 GC run과 전체 부하가 다르다. 차이를 그대로 순수 GC 추가 지연이라고 해석하지 않는다.
같은 mixed 부하의 No-GC 대조는 별도 준비/짧은 조건과 GC absence 확인이 필요하다.

### 본 실험 성공 판정

```bash
.venv/bin/python -m json.tool results/channel-first-gc-r1/manifest.json
cat results/channel-first-gc-r1/window.stats.txt
cat results/channel-first-gc-r1/drained.stats.txt
```

- 본 측정은 valid=true, dry_run=false, fio 각 job error=0.
- actual firmware policy 일치, allocation_trace_count=0.
- gc_failed_req_count=0, host_failed_req_count=0.
- GC run은 window gc_count>0와 completed erase 확인. baseline은 window GC count=0.
- probe_clat.*.log의 read sample 수/실제 IOPS/total_ios를 확인.
- trace_dropped=0은 이벤트 timeline 완전성의 필요 조건. >0이면 timeline은 불완전하다.
  누적 counter는 계속 기록되지만 완전한 GC 시간 추적으로 발표하지 않는다.
- 할당/데이터 검증 PASS, ELF/commit/config/온도/초기화 규칙도 기록.

inspect/allocation/verify/prepare는 성능 run이 아니므로 valid=false일 수 있다.
각각 firmware_inspected, allocation_generated, integrity_verified, prepared 플래그로 확인한다.
GC없음/error인 본 측정의 valid를 수동으로 true로 바꾸지 않는다.

### 그래프 생성

```bash
.venv/bin/python host/analyze.py \
  results/channel-first-gc-r1 results/way-first-gc-r1 results/page-first-gc-r1 \
  --output results/comparison-p99-r1 --window-seconds 1 --metric p99

.venv/bin/python host/analyze.py \
  results/channel-first-gc-r1 results/way-first-gc-r1 results/page-first-gc-r1 \
  --output results/comparison-p999-r1 --window-seconds 5 --metric p99_9
```

summary.csv, 정책별 latency-windows/events/gc-intervals.csv, 통합PNG/SVG, CCDF를 생성한다.
전체 P99는 구간 P99 평균이 아니라 전체 원시 표본에서 계산한다.
1초/낮은IOPS의 P99.9는 한두 극단값에 민감하므로 sample count와 5초 구간/전체run/독립 반복도 본다.
X축은 정책별 독립 실행의 경과 시간이며 같은50초를 동일한 요청이라고 해석하지 않는다.

### 계측의 범위와 한계

같은 Die의 GC issued-phase와 Host NAND-ready queue wait가 겹친 시간을 측정한다.
정확한 Channel bus 점유/denial도, GC만이 일으킨 지연도 아니다. old gc_*_blocked도 pending-GC일 때의
전체 queue wait라는 proxy다. NVMe read probe별 collision 집단과 P99를 직접 연결하지 않았다.
fio와 firmware timer의 기준점도 다르므로 미보정 GC 음영을 그래프에 자동 겹치지 않는다.
buffered trace도 메모리 기록/clock 호출 비용이 있다. trace level0/1을 동일 조건으로 비교해
관찰 오버헤드도 점검한다. level2는 짧은 진단용이며 이벤트가 빠르게 overflow할 수 있다.

WA는 최종 FLUSH 후 drained 통계로 계산한다. window는 fio 이후 이미 생성된 NAND drain까지 포함하며,
drained에는 최종 FLUSH가 만든 추가 GC도 들어갈 수 있어 둘을 구분한다.
migration counter는 계획한 이동 수, GC program은 성공 write 수다.
일반 write completion은 DRAM DMA 단계이며 FUA/write-through, power-loss recovery, 완전한
NVMe 오류 전파는 미구현이다. 이번 주지표는 Host read completion의 tail latency다.
정확히는 fio clat(제출부터 완료까지)을 사용하며 slat를 더한 fio total lat이나
요청 발생부터 제출까지의 애플리케이션 대기시간을 포함한 end-to-end latency와 구분한다.

## 16. 결과 백업, 종료, 문제 해결

아래를 저장한다:

```text
source commit/dirty 상태, SDK 적용 diff/backup, board ftl_config, BSP/HDF/bitstream 버전
정책별 실제 ELF와 SHA256, compiler flags/optimization, geometry/timer
각 run manifest/.fio/fio.json/probe_clat/UART/window/drained/trace
분석 CSV/PNG/SVG, 정책 순서/온도/날짜/반복/초기화·BBT 규칙
```

결과/ELF는 기본 gitignore에 의해 push되지 않는다. 별도 저장소에 반드시 백업한다.
Windows에서 Host 결과 복사 예:

```powershell
scp -r HOST_USER@HOST_IP:/home/HOST_USER/openssd-research/experiment-kit-20261005/results C:\OpenSSD\results-backup-20261005
```

정상 종료: workload와 로그 저장 완료 확인→bridge Ctrl+C→필요하면 Host 정상 종료.
전용 방화벽 규칙이 더 이상 필요 없으면 관리자 PowerShell에서 본인이 만든 규칙만 제거:

```powershell
Remove-NetFirewallRule -DisplayName 'OpenSSD UART Bridge 8765'
```

| 문제 | 중단 후 확인할 것 |
|---|---|
| COM access denied | SDK Terminal/다른 logger 연결 해제, 실제 UART COM 확인 |
| bridge bind/TCP 실패 | 실제 IP/route/허용 Host IP/Private 방화벽/Wi-Fi isolation |
| PCI ID mismatch | OS SSD 오지정 여부, 실제 controller/bitstream 확인 |
| mount/swap/holder guard | 정확한 DUT 사용 상태; 경고 우회나 전체 disk 해제 금지 |
| schema/policy 불일치 | 기존 ELF, Run Configuration, SDK 적용 대상, Clean/Build 확인 |
| ASSERT/unsupported opcode | run 무효; 기존 board/kernel 호환성, 다른 장치 접근 조사 |
| allocation trace guard | 검증용에서 TRACE_COUNT=0 측정 ELF로 전환 후 fresh boot |
| no GC | 주소 범위/총 쓰기량/전처리 부족; 동일 조건으로 재pilot |
| trace dropped | 짧은 진단/trace1/capacity 증가 검토; link map 확인 필수 |
| output folder exists | 삭제하지 말고 새 이름 사용 |
| NAND failure/CRC mismatch | 성능 실험 중단; geometry/BSP/NAND/FLUSH부터 검증 |
| Python/fio 부족 | 버전/parse-only 확인; 무단 kernel 업그레이드 금지 |

LAN bridge가 불가능하면 JTAG는 노트북에 유지하고 **USB-UART만 Linux Host로 옮기는** 대안이 있다.
가이드 배선의 변경이므로 연구실에서 허가/연결을 확인한다. FTL 초기화 완료 후 COM Disconnect하고
UART USB를 옮긴 뒤 Host에서:

```bash
ls -l /dev/serial/by-id/
sudo dmesg --ctime
```

정확한 UART를 확인하여 --serial에 local path(예/dev/ttyUSB0)를 지정한다.
bridge/방화벽은 필요 없지만 재초기화 prompt를 입력할 연결은 마련해야 한다.
JTAG와 DUT PCIe의 역할은 바꾸지 않는다.

## 17. 첫 실험 체크리스트

```text
[ ] 새20261005 패키지 소스를 지정 GitHub의 별도 폴더에 push, 두PC 동일commit
[ ] 기존 동작 SDK/application/보드설정 백업, 변경diff 검토 후 연구소스 적용
[ ] BSP/geometry/link map/RAM 경계 확인, 정책별 검증ELF/측정ELF 저장
[ ] Host에 동일ELF 복사/hash 확인, Ubuntu/Python/fio 도구 조건 통과
[ ] 전체 소거 허가/백업, Host OFF 상태에서 가이드대로 보드 초기화
[ ] FTL ready 후 Host ON, Cosmos namespace/PCI ID 확인, mount/swap/holder 없음
[ ] SDK COM만 disconnect, 노트북 bridge, Host inspect 성공
[ ] 정책별 실제 allocation PASS, 측정용 ELF에서 data integrity PASS
[ ] pilot GC/부하·GC 안정성/총시간/trace overflow 확인, 비교 조건 확정
[ ] fresh 초기화+전처리부터 전 정책/독립 반복 실험, valid와NAND errors 확인
[ ] raw 표본으로P99/P99.9/GC/WA 분석, 한계 명시, 결과와ELF 별도 백업
```

장비 연결/SDK 부팅 흐름은 사용자 제공 OpenSSD Board Quick Start Guide/FULL을 참고했다.
전자는 Dankook University 2026 Semiconductor SW, 과학기술정보통신부·정보통신기획평가원
SW중심대학사업 지원 교재에 기반한다. 교재 자체는 GitHub에 배포하지 않는다.

보충 1차 자료:

- [GitHub 코드 올리기](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)
- [GitHub CLI 설치](https://github.com/cli/cli#installation)
- [pySerial socket URL 및 보안 주의](https://pyserial.readthedocs.io/en/stable/url_handlers.html)
- [fio parse-only/verify-only/log 문서](https://fio.readthedocs.io/en/latest/fio_doc.html)
