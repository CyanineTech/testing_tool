Testing Tool Platform deployment

1. Install Docker and Docker Compose.
2. Copy this directory to the target machine.
3. Set PLATFORM_USER and PLATFORM_PASSWORD in .env.
4. Set the target service values in runtime/config.ini.
5. Run ./offline_deploy.sh.
6. Open http://<target-ip>:5000 and authenticate with the .env credentials.

The deployment starts three services:
- gateway: Nginx, host port 5000
- tool-script-runner: internal port 8000
- tool-camera-sim: internal port 8002

Business services are not published to host ports. Logs and camera state are stored in named volumes.
Use docker compose up -d --build after changing service code, gateway configuration, or frontend files.
