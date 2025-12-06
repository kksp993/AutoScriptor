from AutoScriptor.utils.constant import cfg
VLM_CONFIG = {
    "api_url": f"{cfg['llm']['url']}/v1/chat/completions",
    "model_name": "/model",
    "max_tokens": 512,
    "temperature": 0.5,
    "timeout": 60 ,
    "default_image": "screenshot.png",
}