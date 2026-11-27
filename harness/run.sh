#!/usr/bin/env bash
# pcd2scene 的單一入口：環境檢查、安裝、測試、兩個示範的還原與驗收。
#
#   harness/run.sh [--docker|--native] <命令>
#
# 命令：
#   doctor         檢查這台機器能不能跑（docker 或 Python 3.11 以上、sha256sum、curl 或 python3 下載）
#   setup          docker：建映像；native：建 .venv 並裝 requirements.lock
#   test           單元與整合測試（pytest）
#   demo-synth     合成倉庫：產生點雲與真值 → 還原 → 對真值 → 驗收
#   demo-office    合成辦公室（有天花板）：同上
#   demo-room      下載 PCL room_scan1.pcd（釘 commit 與 SHA-256）→ 還原 → 驗收
#   demo-room2     下載 PCL room_scan2.pcd（同一房間另一次掃描）→ input.transform 轉正 → 還原 → 驗收
#   check-formats  用 check_urdf 與 gz sdf -k 檢查各示範的輸出（只有 docker 模式）
#   all            doctor、setup、test、四個示範，docker 模式再加 check-formats
# 每個示範都加 --stages，各步驟的圖在 out/<示範>/scene/stages/。
#   lock           由 requirements.txt 重產 requirements.lock（docker，需要網路）
#
# 模式：預設 auto，docker daemon 可用就用 docker，否則用 native。也可用環境變數 P2S_MODE。
# 環境變數：P2S_OUT（輸出，預設 out/）、P2S_DATA（下載資料，預設 data/）、P2S_CPUS、P2S_MEMORY。
# 結束碼：0 全部通過；1 驗收或測試失敗；2 環境不符。每一步的結果另寫 out/harness-summary.json。
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MODE=${P2S_MODE:-auto}
while [[ $# -gt 0 && $1 == --* ]]; do
  case $1 in
    --docker) MODE=docker ;;
    --native) MODE=native ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
CMD=${1:-all}
OUT=${P2S_OUT:-$ROOT/out}
DATA=${P2S_DATA:-$ROOT/data}
NPROC=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)
CPUS=${P2S_CPUS:-$(( NPROC / 2 > 4 ? 4 : (NPROC / 2 < 1 ? 1 : NPROC / 2) ))}
MEMORY=${P2S_MEMORY:-4g}

# 示範資料：Point Cloud Library 的 data 儲存庫（BSD-3-Clause），釘在 commit 084fa0e
PCL_DATA=https://raw.githubusercontent.com/PointCloudLibrary/data/084fa0e260580cc765ded83de4ec3f495f1d6f1e/tutorials
ROOM1_SHA256=52c373a67d8beaa318b5e8c024f06e219f14acc1db28fa7333ff5dc73840428b
ROOM2_SHA256=c713876195eb28f8cafea8666c631c15b0fd90001a4f74e92b02dfc269d5cb80

hash12() { cat "$@" | sha256sum | cut -c1-12; }
IMAGE=pcd2scene:$(cd "$ROOT" && hash12 Dockerfile requirements.lock)
CHECK_IMAGE=pcd2scene-check:$(cd "$ROOT" && hash12 harness/Dockerfile.check)
SUMMARY=()

log() { printf '\n== %s\n' "$*"; }
die() { echo "error: $*" >&2; exit 2; }
record() { SUMMARY+=("$1=$2"); }

resolve_mode() {
  if [[ $MODE == auto ]]; then
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then MODE=docker; else MODE=native; fi
  fi
  [[ $MODE == docker || $MODE == native ]] || die "mode must be docker or native"
}

# 在選定的環境裡執行 python。路徑一律用 $SRC、$OUTP、$DATAP 這三個前綴。
py() {
  mkdir -p "$OUT" "$DATA"
  if [[ $MODE == docker ]]; then
    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
      --memory "$MEMORY" --cpus "$CPUS" --pids-limit 512 --network none \
      --log-opt max-size=10m --log-opt max-file=3 \
      -v "$ROOT:/src:ro" -v "$OUT:/out" -v "$DATA:/data:ro" -w /src "$IMAGE" python "$@"
  else
    PYTHONPATH="$ROOT/src" PYTHONDONTWRITEBYTECODE=1 "$ROOT/.venv/bin/python" "$@"
  fi
}
paths() {
  if [[ $MODE == docker ]]; then SRC=/src OUTP=/out DATAP=/data; else SRC=$ROOT OUTP=$OUT DATAP=$DATA; fi
}

python_ok() {
  command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
}

cmd_doctor() {
  log "doctor ($MODE)"
  local bad=0
  echo "repo:     $ROOT ($(cd "$ROOT" && git rev-parse --short HEAD 2>/dev/null || echo 'not a git checkout'))"
  echo "os:       $(uname -sm)"
  echo "cpus:     $NPROC (harness uses $CPUS in docker mode)"
  if command -v sha256sum >/dev/null 2>&1; then echo "sha256sum: ok"; else echo "sha256sum: MISSING"; bad=1; fi
  if command -v curl >/dev/null 2>&1; then echo "download: curl"
  elif command -v python3 >/dev/null 2>&1; then echo "download: python3 urllib (curl not found)"
  else echo "download: MISSING (need curl or python3)"; bad=1; fi
  if [[ $MODE == docker ]]; then
    docker version --format 'docker:   {{.Server.Version}}' || { echo "docker:   daemon unreachable"; bad=1; }
  else
    if python_ok; then echo "python:   $(python3 -V)"; else echo "python:   need Python >= 3.11 (found: $(python3 -V 2>&1 || echo none))"; bad=1; fi
    python3 -c 'import venv, ensurepip' 2>/dev/null && echo "venv:     ok" || { echo "venv:     MISSING (Debian/Ubuntu: apt install python3-venv)"; bad=1; }
  fi
  echo "out:      $OUT"
  echo "data:     $DATA"
  [[ $bad == 0 ]] || die "environment check failed"
  record doctor ok
}

cmd_setup() {
  log "setup ($MODE)"
  if [[ $MODE == docker ]]; then
    if docker image inspect "$IMAGE" >/dev/null 2>&1; then
      echo "image $IMAGE already built"
    else
      docker build -t "$IMAGE" "$ROOT"
    fi
  else
    python_ok || die "native mode needs Python >= 3.11"
    if [[ ! -x $ROOT/.venv/bin/python ]]; then python3 -m venv "$ROOT/.venv"; fi
    "$ROOT/.venv/bin/pip" install --disable-pip-version-check -q -r "$ROOT/requirements.lock"
  fi
  record setup ok
}

cmd_test() {
  log "test ($MODE)"
  paths
  if py -m pytest -q -p no:cacheprovider "$SRC/tests"; then record test pass; else record test FAIL; return 1; fi
}

# 合成示範：run_synth <版面> <輸出名> <紀錄名>
run_synth() {
  local layout=$1 name=$2 step=$3
  log "$step ($MODE)"
  paths
  rm -rf "${OUT:?}/$name"
  py -m pcd2scene synth "$OUTP/$name/data" --layout "$layout"
  py -m pcd2scene build "$OUTP/$name/data/$layout.pcd" -c "$OUTP/$name/data/catalog.yaml" \
    -o "$OUTP/$name/scene" --stages
  py -m pcd2scene compare "$OUTP/$name/scene/scene.json" "$OUTP/$name/data/truth.json" \
    --out "$OUTP/$name/scene/compare.json" || true
  if py -m pcd2scene accept "$OUTP/$name/scene" "$SRC/examples/$name/accept.json" \
      --json "$OUTP/$name/scene/accept.json"; then
    record "$step" pass
  else
    record "$step" FAIL; return 1
  fi
}
cmd_demo_synth() { run_synth warehouse synth_warehouse demo-synth; }
cmd_demo_office() { run_synth office synth_office demo-office; }

# 下載 PCL 示範點雲：fetch_pcl <檔名> <SHA-256>
fetch_pcl() {
  local file=$1 sha=$2 dst=$DATA/$1 url=$PCL_DATA/$1
  mkdir -p "$DATA"
  if [[ -f $dst ]] && echo "$sha  $dst" | sha256sum -c --quiet - 2>/dev/null; then
    echo "$file present (sha256 ok)"; return 0
  fi
  echo "downloading $url"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 -o "$dst.part" "$url" || die "download failed"
  else
    python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' \
      "$url" "$dst.part" || die "download failed"
  fi
  echo "$sha  $dst.part" | sha256sum -c --quiet - || { rm -f "$dst.part"; die "sha256 mismatch for $file"; }
  mv "$dst.part" "$dst"
}

# 真實掃描示範：run_room <檔名> <SHA-256> <範例名> <紀錄名>
run_room() {
  local file=$1 sha=$2 name=$3 step=$4
  log "$step ($MODE)"
  paths
  fetch_pcl "$file" "$sha"
  rm -rf "${OUT:?}/$name"
  py -m pcd2scene build "$DATAP/$file" -c "$SRC/examples/$name/config.yaml" -o "$OUTP/$name/scene" --stages
  if py -m pcd2scene accept "$OUTP/$name/scene" "$SRC/examples/$name/accept.json" \
      --json "$OUTP/$name/scene/accept.json"; then
    record "$step" pass
  else
    record "$step" FAIL; return 1
  fi
}
cmd_demo_room() { run_room room_scan1.pcd "$ROOM1_SHA256" room_scan demo-room; }
cmd_demo_room2() { run_room room_scan2.pcd "$ROOM2_SHA256" room_scan2 demo-room2; }

cmd_check_formats() {
  log "check-formats"
  [[ $MODE == docker ]] || { echo "skipped: needs docker"; record check-formats skipped; return 0; }
  if ! docker image inspect "$CHECK_IMAGE" >/dev/null 2>&1; then
    docker build -t "$CHECK_IMAGE" -f "$ROOT/harness/Dockerfile.check" "$ROOT/harness"
  fi
  local dirs=() d
  for d in synth_warehouse synth_office room_scan room_scan2; do
    [[ -f $OUT/$d/scene/scene.urdf ]] && dirs+=("$d")
  done
  [[ ${#dirs[@]} -gt 0 ]] || die "no demo output; run a demo first"
  if docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp --network none --memory 2g --cpus 2 --pids-limit 256 \
      --log-opt max-size=10m --log-opt max-file=3 -v "$OUT:/out:ro" "$CHECK_IMAGE" bash -c '
        set -e
        for d in '"${dirs[*]}"'; do
          cd /out/$d/scene
          check_urdf scene.urdf > /dev/null && echo "URDF ok  $d"
          gz sdf -k scene.sdf > /dev/null && echo "SDF ok   $d"
        done'; then
    record check-formats pass
  else
    record check-formats FAIL; return 1
  fi
}

cmd_lock() {
  log "lock"
  local base
  base=$(sed -n 's/^FROM //p' "$ROOT/Dockerfile" | head -1)
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp --memory 2g --cpus 2 --pids-limit 256 \
    --log-opt max-size=10m --log-opt max-file=3 -v "$ROOT/requirements.txt:/r.txt:ro" "$base" sh -c \
    'python -m venv /tmp/v && /tmp/v/bin/pip -q install --disable-pip-version-check -r /r.txt && /tmp/v/bin/pip freeze --all --exclude pip' \
    > "$ROOT/requirements.lock.new"
  { echo "# 由 requirements.txt 在 python:3.12-slim（digest 見 Dockerfile）上 pip freeze 產生。更新：harness/run.sh lock"
    cat "$ROOT/requirements.lock.new"; } > "$ROOT/requirements.lock"
  rm -f "$ROOT/requirements.lock.new"
  git -C "$ROOT" diff --stat -- requirements.lock || true
}

write_summary() {
  mkdir -p "$OUT"
  local s="{" first=1 kv
  for kv in "${SUMMARY[@]}"; do
    [[ $first == 1 ]] || s+=", "
    s+="\"${kv%%=*}\": \"${kv#*=}\""
    first=0
  done
  s+="}"
  printf '{"mode": "%s", "commit": "%s", "steps": %s}\n' "$MODE" \
    "$(cd "$ROOT" && git rev-parse HEAD 2>/dev/null || echo unknown)" "$s" > "$OUT/harness-summary.json"
  log "summary ($OUT/harness-summary.json)"
  for kv in "${SUMMARY[@]}"; do printf '  %-14s %s\n' "${kv%%=*}" "${kv#*=}"; done
}

resolve_mode
rc=0
case $CMD in
  doctor) cmd_doctor ;;
  setup) cmd_setup ;;
  test) cmd_test || rc=1 ;;
  demo-synth) cmd_demo_synth || rc=1 ;;
  demo-office) cmd_demo_office || rc=1 ;;
  demo-room) cmd_demo_room || rc=1 ;;
  demo-room2) cmd_demo_room2 || rc=1 ;;
  check-formats) cmd_check_formats || rc=1 ;;
  lock) [[ $MODE == docker ]] || die "lock needs docker"; cmd_lock ;;
  all)
    cmd_doctor
    cmd_setup
    cmd_test || rc=1
    cmd_demo_synth || rc=1
    cmd_demo_office || rc=1
    cmd_demo_room || rc=1
    cmd_demo_room2 || rc=1
    cmd_check_formats || rc=1
    ;;
  *) die "unknown command: $CMD (see harness/run.sh --help)" ;;
esac
[[ ${#SUMMARY[@]} -eq 0 ]] || write_summary
exit $rc
