# ECE436 Wireless Communications — ath9k fairness experiments

Local repository for the ECE436/NITLab Wi-Fi experiments around medium-access fairness/unfairness with the Linux backports `ath9k` driver.

The project contains:

```text
backports-5.4.56-1/        Backports driver source tree used for ath9k changes
backports-5.4.56-1.tar.xz  Original kernel.org backports archive
run.sh                     Interactive experiment runner and result pipeline
results/                   Collected experiment logs and parsed CSVs (generated)
plots/                     Throughput plots from parsed results (generated)
experiment.conf            Saved local experiment settings, when exported
```

## Source version

The driver source is from the official kernel.org backports stable archive:

```text
https://cdn.kernel.org/pub/linux/kernel/projects/backports/stable/v5.4.56/backports-5.4.56-1.tar.xz
```

## What `run.sh` does

`run.sh` is the main workflow script for preparing NITLab nodes, deploying the modified driver, running iperf experiments, and collecting/plotting results. Running it without arguments opens an interactive menu:

```bash
./run.sh
# or
./run.sh menu
```

The menu is split into four tabs:

```text
1) Setup                  image nodes, generate/deploy patch, save/load config
2) Custom driver options  choose ath9k_hw module parameters and inspect nodes
3) Test                   run single-STA, dual-STA, or two-AP experiments
4) Results                fetch logs, parse CSV summaries, create plots, cleanup
```

### 1. Setup

The setup tab configures the experiment environment and prepares the NITLab nodes.

Main actions:

```text
generate patch from source code
  Creates an ath9k-only patch from local changes under backports-5.4.56-1/drivers/net/wireless/ath/ath9k.

set default nodes
  Stores AP1, optional AP2, fair STA, unfair STA, and their IP addresses.

set default rates
  Sets offered iperf rates, run duration, default fixed rate, and fair-STA lead time.

load image to nodes
  Runs OMF through the gateway and waits for root SSH readiness on each node.

send patch + apply + build/install backports on nodes
  Copies the patch to each node, applies it under BACKPORTS_DIR, builds backports, installs the modules, runs depmod, and verifies that the custom ath9k_hw parameters exist.

load/export settings from/to config
  Reads or writes experiment.conf so the same nodes/rates/options can be reused later.

edit general settings
  Updates gateway, slice name, image, node log path, local result/plot paths, SSIDs, channel, source repo, and base git ref.
```

Important defaults can be overridden either in `experiment.conf` or as environment variables before running the script:

```bash
GATEWAY=nitlab3.inf.uth.gr
SLICE_NAME=dtsiantos
IMAGE=baseline_wireless_communications.ndz
BACKPORTS_DIR=/root/backports-5.4.56-1
NODE_LOG_DIR=/root/ece436_exp_logs
LOCAL_RESULTS_DIR=./results
PLOTS_DIR=./plots
```

### 2. Custom driver options

This tab controls the custom `ath9k_hw` module parameters used for the fair and unfair stations:

```text
selfish_mode       custom selfish MAC behavior
disable_backoff    backoff-disabling experiment mode exposed by the patch
chanel_idle        driver parameter name intentionally keeps the current typo
selfish_txop_us    custom TXOP duration in microseconds; 0 disables it
```

The script stores options separately for the fair and unfair STA:

```bash
FAIR_DRIVER_OPTS="selfish_mode=0 disable_backoff=0 chanel_idle=0 selfish_txop_us=0"
UNFAIR_DRIVER_OPTS="selfish_mode=1 disable_backoff=1 chanel_idle=0 selfish_txop_us=0"
```

From the menu you can also load the drivers immediately and run a node status/debug check. The status command prints ath9k modules, current module parameters, wlan0 state, iw output, and recent ath9k-related dmesg lines.

### 3. Test

The test tab runs the actual iperf experiments. Each run writes logs on the nodes under `NODE_LOG_DIR` and snapshots the active `experiment.conf` in the experiment directory.

Supported topologies:

```text
fair node only
  AP1 + fair STA. Runs a rate sweep for the fair STA.

unfair node only
  AP1 + unfair STA. Runs a rate sweep for the unfair STA.

fair + unfair nodes
  AP1 serves both STAs. The fair STA can start first, then the unfair STA starts after DUAL_FAIR_LEAD_SECONDS.

AP1-fair + AP2-unfair nodes
  Two-AP topology: fair STA sends to AP1 and unfair STA sends to AP2. Optional AP1 channel-switch automation and AP2/unfair auto-follow can be enabled.
```

For each test the script asks for:

```text
protocol:        UDP or TCP
Wi-Fi mode:      802.11n or 802.11g
rates/duration:  either a sweep or fixed-rate combinations
log prefix:      experiment directory name
prepare topology: whether to reload drivers, start APs, and connect STAs first
```

For dual-STA and two-AP tests, `run.sh` supports these offered-rate plans:

```text
both STAs sweep/use the same rate list
unfair STA fixed while fair STA sweeps
fair STA fixed while unfair STA sweeps
both STAs fixed at explicit rates
```

### 4. Results

The results tab automates log collection and analysis.

Main actions:

```text
fetch results from nodes
  Tars NODE_LOG_DIR on each node, copies logs through the gateway, reorganizes them by experiment and role, writes/keeps experiment.conf, parses summary.csv, and creates plots.

parse results to CSV
  Reads iperf logs and writes summary.csv with per-interval throughput, jitter/loss where available, role, port, rates, and timing offsets.

plot results
  Creates PNG throughput plots from summary.csv. For collection directories, it detects child experiments automatically.

parse + plot results
  Convenience action that parses and plots one experiment or every experiment under a collected directory.

dry-run with dummy nodes/logs
  Generates synthetic logs locally and runs the parser/plotter without needing NITLab access. Useful for checking the results pipeline.

clear logs from nodes
  Deletes contents under NODE_LOG_DIR on selected nodes after confirmation.
```

Plots use receiver bandwidth in Mbit/s versus time in seconds. When channel-switch logs are present, the plotter also extracts switch events into `channel_switch_events.csv` and marks them on the graph.

## Non-interactive commands

Most menu actions also have CLI commands:

```bash
./run.sh generate-patch [file]
./run.sh load-config experiment.conf
./run.sh export-config experiment.conf
./run.sh deploy-driver [nodes_csv] [patch_file]
./run.sh fetch-results [out_dir] [nodes_csv]
./run.sh parse-results experiment_dir [csv]
./run.sh plot-results experiment_dir [csv] [plot_dir]
./run.sh parse-plot-results experiment_or_collection_dir [csv] [plot_root]
./run.sh dry-run [out_dir]
./run.sh clear-node-logs [nodes_csv] [remote_log_dir]
./run.sh status [nodes_csv]
```

Examples:

```bash
# Save current settings for later reuse
./run.sh export-config experiment.conf

# Load saved settings and deploy the driver patch to configured nodes
./run.sh load-config experiment.conf
./run.sh generate-patch ath9k_experiment.patch
./run.sh deploy-driver node069,node075,node063,node084 ath9k_experiment.patch

# Collect logs, parse summaries, and create plots
./run.sh fetch-results ./results/collected_$(date +%Y%m%d_%H%M%S) node069,node075,node063,node084

# Re-run parser and plotter on already collected logs
./run.sh parse-plot-results ./results/collected_20260629_004619

# Test the local result pipeline without NITLab nodes
./run.sh dry-run
```

## Typical workflow

```text
1. Edit the ath9k source under backports-5.4.56-1/.
2. Run ./run.sh and use Setup -> generate patch.
3. Configure nodes/rates/settings and export experiment.conf.
4. Load the NITLab image if needed.
5. Deploy patch + build/install backports on the selected nodes.
6. Choose custom driver options for fair/unfair STAs.
7. Run a test topology from the Test tab.
8. Fetch results from nodes.
9. Review each experiment's experiment.conf, summary.csv, channel_switch_events.csv when present, and plots/*.png.
```

## Manual backports build/install

If you need to build directly on a node without `run.sh`:

```bash
cd backports-5.4.56-1
make defconfig-ath9k
make -j$(nproc)
sudo modprobe -r ath9k ath9k_common ath9k_hw ath mac80211 cfg80211 || true
sudo make install
sudo depmod -a
sudo modprobe ath9k
modinfo ath9k_hw | egrep 'filename|version|parm'
dmesg | tail -100
```

Prefer `run.sh` for experiments because it keeps the configuration, logs, parsed CSV files, and plots tied together per run.
