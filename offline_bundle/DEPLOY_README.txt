Deploy steps on target machine:
1) Ensure Docker and Docker Compose are installed.
2) Clone the repository and enter this folder.
3) Run: chmod +x offline_deploy.sh && ./offline_deploy.sh
4) Edit runtime/config.ini with the target service account and host.
5) Open: http://<target-ip>:5000

The default mode builds the image from the Dockerfile. For an air-gapped
machine that has image.tar, run: USE_OFFLINE_IMAGE=1 ./offline_deploy.sh

Mounted directory layout:
- ./service  -> /app/service (web service code)
- ./scripts  -> /app/scripts (task scripts)
- ./runtime  -> /app/runtime (config, script_descriptions, logs)

After deployment:
- Replace task scripts directly in ./scripts (target machine) to hot update task logic.
- If you modify files under ./service, restart container to apply service code changes.
