from feishu_agent.bootstrap import AppComponents, build_components
from feishu_agent.core.feishu_listener import FeishuListener


def create_app() -> AppComponents:
    return build_components()


def main() -> None:
    components = create_app()
    listener = FeishuListener(orchestrator=components.orchestrator)
    listener.start()


if __name__ == "__main__":
    main()
