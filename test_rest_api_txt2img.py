import requests
import base64
import time
import json as js

server_url = "http://127.0.0.1:5000"

r = requests.post(f"{server_url}/txt2img", json=js.loads('{"prompt": "A blue sphere on a red table", "ddim_steps": 50, "sampler_name": "k_euler_a", "toggles": [1, 2, 3, 4, 5], "realesrgan_model_name": "RealESRGAN_x4plus", "ddim_eta": 0, "n_iter": 4, "batch_size": 1, "cfg_scale": 7.5, "seed": "null", "height": 512, "width": 512, "fp": "null", "variant_amount": 0.0}'))

response = js.loads(r.text)
print(f"response: {response}")
request_id = response["id"]

done = False
while not done:
    r = requests.get(f"{server_url}/txt2img/{request_id}")
    response = js.loads(r.text)
    retval = response["retval"]
    if retval is not None:
        i = 1
        for image in retval[0]:
            img = base64.b64decode(image)
            with open(f"out{i}.png", "wb") as f:
                f.write(img)
            i = i + 1
        done = True
    else:
        print("Not ready yet...")
        time.sleep(1)

