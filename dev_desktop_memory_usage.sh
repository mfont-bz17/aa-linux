#!/bin/bash
BOLD='\033[1m'
NC='\033[0m'

pss_kb() {
    local pid=$1
    grep -oP '^Pss:\s+\K[0-9]+' /proc/$pid/smaps_rollup 2>/dev/null
}

total_mb=0
show() {
    local label=$1 pid=$2 kb name
    kb=$(pss_kb "$pid")
    name=$(cat /proc/$pid/comm 2>/dev/null)
    if [[ -n "$kb" ]]; then
        local mb
        mb=$(awk "BEGIN{printf \"%.1f\", $kb/1024}")
        if [[ -n "$name" && "$label" != "openbox" && "$label" != "picom" ]]; then
            label=$name
        fi
        printf "%-12s %8s MB\n" "$label" "$mb"
        total_mb=$(awk "BEGIN{printf \"%.1f\", $total_mb + $kb/1024}")
    else
        printf "%-12s %8s\n" "$label" "N/A"
    fi
}

echo -e "${BOLD}System:${NC}"
show "openbox" "$(pgrep -f 'openbox --config-file' | head -1)"
show "picom" "$(pgrep -f 'picom' | head -1)"

echo
echo -e "${BOLD}Apps:${NC}"
for p in $(DISPLAY=:99 wmctrl -lp | tr -s " " | cut -d " " -f3); do
    show "$p" "$p"
done

echo
printf "%-12s %8s MB\n" "TOTAL" "$total_mb"
