# test_tools

## Quick start

Requirements: Docker and Docker Compose.

```bash
git clone <repository-url>
cd test_tools
./start.sh
```

On the first run, edit `offline_bundle/runtime/config.ini` with the target
service host, account, and password, then run `./start.sh` again if task
scripts need to be used. Open `http://<target-ip>:5000` in a browser.

The default startup builds the Docker image from source. For an air-gapped
machine with a separately supplied `offline_bundle/image.tar`, use:

```bash
USE_OFFLINE_IMAGE=1 ./start.sh
```

Runtime configuration, tokens, logs, Docker image archives, and Python cache
files are intentionally excluded from Git.
