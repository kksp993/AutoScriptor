import cv2
from paddleocr import TextRecognition
model = TextRecognition(
    model_name="PP-OCRv5_server_rec",
    device="cpu",
    enable_hpi=False,
    use_tensorrt=True,
    enable_mkldnn=True,
    mkldnn_cache_capacity=8192,
    cpu_threads=1,
)
img = cv2.imread("D:\Projects\AutoScriptor\screenshot.png")
output = model.predict(input=img, batch_size=1)
print(output)