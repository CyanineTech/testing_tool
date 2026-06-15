from feishu_agent.config import load_settings
from feishu_agent.deploy.cli import main


if __name__ == "__main__":
    raise SystemExit(main(settings=load_settings()))
