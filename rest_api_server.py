#For environment variables
import os

#For base64 conversion
import io
from base64 import b64encode, b64decode

#For the flask API server
from flask import Flask, json, request

#For the multiprocessing shared state
import rest_api_job_queue

from PIL import Image

#Experimentally, it seems this is the highest permitted on my GPU.
max_resolution = os.getenv("MAX_RESOLUTION", 720896)
print(f"Using max resolution: {max_resolution}")

admin_key = os.getenv("API_ADMIN_KEY", "admin")
print(f"Using admin key: {admin_key}")


#Convert the image into a base64 encoding for transmission via JSON.
def get_response_image(pil_img):
    byte_arr = io.BytesIO()
    pil_img.save(byte_arr, format='PNG') # convert the PIL image to byte array
    encoded_img = b64encode(byte_arr.getvalue()).decode('ascii') # encode as base64
    return f'data:image/png;base64,{encoded_img}'


#Convert the base64 encoding into an image for transmission to img2img or imgproc.
def get_param_image(image):
    header = f'data:image/png;base64,'
    assert image.startswith(header), "Image data not recognized."
    image = image[len(header):]
    test = Image.open(io.BytesIO(b64decode(image)))
    test.save("test_out.png")
    return test


#Get the request containing the status and/or the generated images
def handle_get(request_type, path, key):
    try:         
        request_id = int(path)

        manager = rest_api_job_queue.get_manager()
        manager.connect()

        if request_id == 0 and key == admin_key:
            manager.cancel_all()
            return f'{{"status" : "All requests cancelled."}}'

        request = manager.get_request(request_id)._getvalue()


        r_key = ""
        try:
            r_key = request["key"]
        except:
            pass


        if key != r_key and key != admin_key:
            msg = f'{{"error": "Authorization denied -- key does not match"}}'
            print(msg)
            return msg

        
        if request_type == "cancel":
            return json.dumps(manager.cancel(request_id)._getvalue())




        if request["type"] != request_type:
            msg = f'{{"error": "Request type {request_id} is {request["type"]}, not {request_type}."}}'
            print(msg)
            return msg


        newlist = []
        try:
            try:
                for i in request["retval"][0]:
                    newlist.append(get_response_image(i))
            except:
                for i in request["retval"]:
                    newlist.append(get_response_image(i))

            lret = list(request["retval"])
            lret[0] = newlist
            request["retval"] = tuple(lret)
            manager.set_request(request)
        except:
            pass
            
        #Remove the rather large images from the request object before sending it back.
        if request_type == "img2img":
            del request["params"]["init_info_mask"]

        if request_type == "imgproc":
            del request["params"]["image"]

        return json.dumps(request)

    except Exception as err:
        msg = f'{{"error": "Could not get request {request_type}/{path} from queue: {err}"}}'
        print(msg)
        return msg


#Return the list of available models
def handle_get_models():
    try:         
        request_id = int(path)
        manager = rest_api_job_queue.get_manager()
        manager.connect()
        return manager.get_models()
    except:
        return '{{"error": "unable to get model list"}}'


#Return the list of available samplers
def handle_get_samplers():
    try:         
        request_id = int(path)
        manager = rest_api_job_queue.get_manager()
        manager.connect()
        return manager.get_samplers()
    except:
        return '{{"error": "unable to get sampler list"}}'


#Allocate the request and start the process
def handle_post(request_type, key, include_logs, model):
    try:
        manager = rest_api_job_queue.get_manager()
        manager.connect()

        params=request.json
        for k in params:
            if params[k] == "null":
                params[k] = None


        if "width" in params and "height" in params:
            if params["width"] * params["height"] > max_resolution:
                return '{"error": "Not enough VRAM to process request."}'

        #Convert any base64 pngs into PIL images before sending them to the manager
        if request_type == "img2img":
            params["init_info_mask"]["image"] = get_param_image(params["init_info_mask"]["image"])
            params["init_info_mask"]["mask"] = get_param_image(params["init_info_mask"]["mask"])
        
        if request_type == "imgproc":
            params["image"] = get_param_image(params["image"])

        ret = manager.add_request({"done": False, "key": key, "model": model, "include_logs": include_logs, "type": request_type, "params": params, "retval": None, "status": {}})._getvalue()

        #Remove the rather large images from the request object before sending it back.
        if request_type == "img2img":
            del ret["params"]["init_info_mask"]
        if request_type == "imgproc":
            del ret["params"]["image"]

        return json.dumps(ret)
    except Exception as err:
        msg = f'{{"error": "Could not add request {request_type} to queue: {err}"}}'
        print(msg)
        return msg





#Declare the Flask API
api = Flask(__name__)




#All of the methods have a POST function to declare the request.

@api.route('/txt2img', methods=['POST'])
def post_txt2img():
    key = request.args.get('key', default="", type = str)
    model = request.args.get('model', default="", type = str)
    try:
        model = json.loads(model)
    except:
        pass
    
    include_logs = request.args.get('include_logs', default=False, type = bool)
    return handle_post("txt2img", key, include_logs, model)

@api.route('/img2img', methods=['POST'])
def post_img2img():
    key = request.args.get('key', default="", type = str)
    model = request.args.get('model', default="", type = str)
    try:
        model = json.loads(model)
    except:
        pass
    include_logs = request.args.get('include_logs', default=False, type = bool)
    return handle_post("img2img", key, include_logs, model)

@api.route('/imgproc', methods=['POST'])
def post_imgproc():
    key = request.args.get('key', default="", type = str)
    model = request.args.get('model', default="", type = str)
    try:
        model = json.loads(model)
    except:
        pass
    include_logs = request.args.get('include_logs', default=False, type = bool)
    return handle_post("imgproc", key, include_logs, model)




#All of the methods have a GET function to return the generated images.

@api.route('/txt2img/<path>', methods=['GET'])
def get_txt2img(path):
    key = request.args.get('key', default="", type = str)
    return handle_get("txt2img", path, key)

@api.route('/img2img/<path>', methods=['GET'])
def get_img2img(path):
    key = request.args.get('key', default="", type = str)
    return handle_get("img2img", path, key)

@api.route('/imgproc/<path>', methods=['GET'])
def get_imgproc(path):
    key = request.args.get('key', default="", type = str)
    return handle_get("imgproc", path, key)

@api.route('/cancel/<path>', methods=['GET'])
def get_cancel(path):
    key = request.args.get('key', default="", type = str)
    return handle_get("cancel", path, key)

@api.route('/info', methods=['GET'])
def get_info():
    manager = rest_api_job_queue.get_manager()
    manager.connect()
    return manager.get_info()._getvalue()




if __name__ == '__main__':
    api.run()
