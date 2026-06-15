from feishu_agent.app import app as fastapi_app


def create_app():
    return fastapi_app


app = fastapi_app