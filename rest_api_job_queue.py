import os
import time
import sys
import threading
import copy
import json

from multiprocessing import Lock
from multiprocessing.managers import BaseManager


import io
from contextlib import redirect_stdout, redirect_stderr

import traceback

import importlib

#Job queue parameters. These should be fine unless the queue is
#split between different servers.
url = os.getenv("JOBQUEUE_URL", '127.0.0.1')
port = os.getenv("JOBQUEUE_PORT", 37844)
auth = os.getenv("JOBQUEUE_AUTH", b"this_is_insecure.")
print(f"Using URL: {url}, port: {port}, auth: {auth}")


#Queue state
max_requests = 1000
lock = Lock()
processing_id = 1
next_id = 1
requests = {}


#Represent the available model options
models = []
default_models = [{"name": "stable_diffusion", "path": "models/ldm/stable-diffusion-v1/model.ckpt"}]
loaded_model = None
mixed_model = None
previous_mix = None

server_version = "0.0.1"
samplers = ["DDIM",
            "PLMS",
            "k_dpm_2_a",
            "k_dpm_2",
            "k_euler_a",
            "k_euler",
            "k_heun",
            "k_lms"]
def get_info():
    return json.dumps({"version": f"{server_version}", "models": [m["name"] for m in models], "samplers": samplers})


#Replace the currently loaded model (if any) with a new one.
def load_model(m):
    global webui_modified
    global loaded_model
    print(f'Loading model "{m["name"]}')
    try:
        i = sys.argv.index("--ckpt")
        try:
            sys.argv[i + 1] = m["path"]
        except:
            print("No arg following ckpt. Adding.")
            sys.argv.append(m["path"])
    except:
        print("Ckpt arg not yet in list. Adding.")
        sys.argv.append("--ckpt")
        sys.argv.append(m["path"])

    if "webui_modified" not in sys.modules:
        import webui_modified
    else:
        importlib.reload(webui_modified)
    loaded_model = m

#Generate a mixed model
#NOTE: This was generalized from a two-model mixing script
#      of indeterminate origin. I don't know if the original
#      worked "correctly", or whether I correctly generalized
#      it to N models. However, empirically it seems to work.
def generate_mixed_model(in_mix, path):
    try:
        global models
        import torch
        mix = []
        models_to_mix = []
        theta = []
        assert len(in_mix) == len(models), "Wrong number of mix scalars"
        j = 0

        for i in range(0, len(models)):
            if in_mix[i] != 0:
                models_to_mix.append(torch.load(models[i]["path"]))

                theta.append(models_to_mix[j]['state_dict'])

                mix.append(in_mix[i])
                j += 1


        #Get a list of all the keys with no duplicates.
        allkeys = []
        for i in range(0, len(models_to_mix)):
            allkeys.extend(theta[i].keys())
        allkeys = list(dict.fromkeys(allkeys))
        
        for k in allkeys:
            if 'model' in k:
                total = 0
                temptheta = 0
                for i in range(0, len(models_to_mix)):
                    if k in theta[i]:
                        total += mix[i]
                        temptheta += mix[i] * theta[i][k]

                assert total != 0, "Invalid total"
                #assert math.isfinite(temptheta), "Non-finite temptheta"

                #Ensure that the sum of mixes for this key is 1.
                theta[0][k] = temptheta / total


        mixed_model = models_to_mix[0]
        torch.save(mixed_model, path)
        del torch
    except Exception as err:
        print(f"Problem generating mixed model: {err}")
        print(traceback.format_exc())



#Currently unused. This would allow a direct, linear mix rather than
#one that adjusts weights in cases where a key is not in all source models.
#Might be useful for interpolation animations, (needs experimentation)
def generate_linear_mix(in_mix, path):
    try:
        global models
        import torch
        mix = []
        models_to_mix = []
        theta = []
        assert len(in_mix) == len(models), "Wrong number of mix scalars"
        j = 0
        for i in range(0, len(models)):
            if in_mix[i] != 0:
                models_to_mix.append(torch.load(models[i]["path"]))
                theta.append(models_to_mix[j]['state_dict'])
                mix.append(in_mix[i])
                j += 1
    

        for k in theta[0].keys():
            if 'model' in k:
                theta[0][k] = mix[0] * theta[0][k]

        for i in range(1, len(models_to_mix)):
            for k in theta[i].keys():
                if 'model' in k:
                    if k not in theta[0]:
                        theta[0][k] = mix[i] * theta[i][k]
                    else:
                        theta[0][k] += mix[i] * theta[i][k]
            
        mixed_model = models_to_mix[0]
        torch.save(mixed_model, path)
        del torch
    except Exception as err:
        print(traceback.format_exc())
        print(f"Problem generating mixed model: {err}")



#Generate a mixed model and load it.
def load_mixed_model(mix):
    global models
    global mixed_model
    global previous_mix
    mixed_model_path = "mixed_model.ckpt"
    generate_mixed_model(mix, mixed_model_path)
    mixed_model = {"name": "mixed_model", "path": mixed_model_path}
    load_model(mixed_model)
    previous_mix = mix


#Add a new request
def add_request(request):
    global next_id
    global requests
    global max_requests
    with lock:
        try:
            request["id"] = next_id
            requests[next_id] = request
            next_id = next_id + 1

            #Clear old requests so we don't run out of memory.
            if next_id > max_requests:
                requests[next_id - max_requests] = {} 
            return request
        except Exception as err:
            msg = f'{{"error": "Error adding request: {err}"}}'
            print(msg)
            return msg


#Get the shared state of the request object.
def get_request(request_id):
    global processing_id
    global next_id
    global requests
    try:
        #Make a copy so nothing can accidentally change the state while we work.
        with lock:
            r = copy.deepcopy(requests[request_id])


        #Let the requester know their current position in the queue.
        try:
            if r["done"]:
                r["status"]["jobs_ahead"] = 0
            else:
                r["status"]["jobs_ahead"] = max(0, request_id - processing_id)
                if r["status"]["jobs_ahead"] != 0:
                    r["status"]["cur_task"] = "waiting"

        except Exception as err:
            print(f"Unable to get number of jobs ahead: {err}. Using 999.")
            r["status"]["jobs_ahead"] = 999


        #Get the percentage of the currently running job.
        #Maybe eventually we provide a proper estimate of the time until completion?
        try:
            if r["done"]:
                r["status"]["cur_job_progress"] = 1
                r["status"]["cur_task"] = "done"
            else:
                current_processing_request = requests[processing_id]
                current_processing_status = current_processing_request["status"]
                cur_step = current_processing_status["step"]
                cur_iter = current_processing_status["iter"]
                total_steps = current_processing_status["total_steps"]
                total_iters = current_processing_status["total_iters"]
                progress = (cur_iter * total_steps + cur_step) / (total_iters * total_steps)
                r["status"]["cur_job_progress"] = progress
        except Exception as err:
            print(f"Unable to get current job progress: {err}. Assuming 0.")
            r["status"]["cur_job_progress"] = 0

        return r
    except Exception as err:
        msg = f'{{"error": "Error getting request {request_id}: {err}"}}'
        print(msg)
        return msg


#Set the shared state of the request object.
def set_request(request):
    global next_id
    global requests
    with lock:
        try:
            requests[request["id"]] = request
        except Exception as err:
            msg = f'{{"error": "Error setting request: {err}"}}'
            print(msg)


#Get the next unassigned request ID.
def get_next_id():
    global next_id
    global requests
    with lock:
        return next_id


#Cancel one job.
def cancel(request_id):
    global processing_id
    with lock:
        try:
            if not requests[request_id]["done"]:
                requests[request_id]["cancel"] = True
            return requests[request_id]
        except Exception as err:
            msg = f'{{"error": "Error cancelling request: {err}"}}'
            print(msg)
            return msg


#Cancel all jobs.
def cancel_all():
    global next_id
    global processing_id
    old_id = processing_id
    processing_id = next_id
    for i in range(old_id, next_id):
        print(f"old_id: {old_id}, i: {i}, next_id: {next_id}")
        cancel(i)


#Get the BaseManager object that shares the state between the workers.
def get_manager():
    manager = BaseManager((url, int(port)), authkey=auth.encode('utf8'))
    manager.register('get_info', get_info)
    manager.register('cancel', cancel)
    manager.register('cancel_all', cancel_all)
    manager.register('add_request', add_request)
    manager.register('get_request', get_request)
    manager.register('get_next_id', get_next_id)
    manager.register('set_request', set_request)
    return manager


#mock object for webui's JobQueue to permit cancellation.
class JobInfo:
    images = []
    should_stop = threading.Event()
    job_status = ""


#This processes each of the requests in the order received.
def process_queue():
    global next_id
    global requests
    global processing_id
    global loaded_model
    global models
    global previous_mix

    os.chdir('stable-diffusion-webui/')

    load_model(models[0])
    print("Starting process queue")
    processing_id = 1



    #Helper function to add progress status to returned object
    def add_status(i):
        with lock:
            try:
                status = {
                    "jobs_ahead": 0,
                    "cur_task": "model_eval",
                    "step": i['i'], 
                    "iter": i['iter'],
                    "total_steps": i['total_steps'],
                    "total_iters": i['total_iters']
                }

                request["status"] = status
                requests[processing_id] = request
            except Exception as err:
                msg = '{"error": "Error: Failed to add status to output: {err}"}}'
                print(f"Failed to add status to output: {err}")

    while True:
        try:
            if processing_id == next_id:
                #Only check ten times per second to avoid wasting CPU cycles.
                time.sleep(0.1)
            else:
                #TODO: Code review
                #TODO: Merge latest from upstream
                #TODO: Test on tablet
                #TODO: Share (merge request for webui (+fork so that it's usable until then), API repo, plugin repo)


                #TODO P2 (plugin): figure out dropdown. Maybe just radios? What triggers the UXP failure from the JS side?
                #TODO P2 (plugin): more than one image
                #TODO P2 (plugin): model changing/mixing
                #TODO P2 (plugin): display image selector grid
                #TODO P3 (plugin): expose relevant advanced settings
                #TODO P3 (plugin): img2img UI
                #TODO P3 (plugin): imgproc UI
                #TODO P4 (plugin): task-based grouping
                #TODO P4 (plugin): proper mask layers? Alpha-based? needs experimentation
                #TODO P4 (plugin): session and/or user key
                #TODO P4 (plugin): selection-based img2img 
                #TODO P5 (plugin): outpainting -- defered
                #TODO P5 (plugin): inpainting -- deferred
                #TODO P5 (plugin): blend layers -- deferred
                #TODO P5 (plugin): "AI brush" -- deferred

                #TODO: Documentation

                #TODO: Workflow 1: Request a generated image and insert it into image (almost done except for plugin, needs checkboxes, progress, etc.)
                #TODO: Workflow 2: Makea selection (or layer, or visible) for img2img. Maybe also mask? Force mask layer or let it be specified separately?
                #TODO: Workflow 3: Upload selection (or layer, or visible) for image processing (GFPGAN, GoBIG, RealESRGAN, etc)


                try:
                    #Previously I did this with a lock instead, but it still seems to get altered somehow.
                    #I think it happens after the lock exits but before the function returns the object.
                    #Whatever, now I just make a copy of the request instead so it can't get corrupted.
                    request = copy.deepcopy(requests[processing_id])
                    print(f'Processing {request["type"]} request {processing_id}...')
                    request["success"] = True


                    #Call the relevant generation function.
                    def call_webui_impl(request, ji):
                        if request["type"] == "txt2img":
                            request["retval"] = webui_modified.txt2img(**request["params"], job_info=ji, callback=add_status)
                        elif request["type"] == "img2img":
                            request["retval"] = webui_modified.img2img(**request["params"], job_info=ji, callback=add_status)
                        elif request["type"] == "imgproc":
                            request["retval"] = webui_modified.imgproc(**request["params"], callback=add_status)
                        else:
                            request["success"] = False
                            print("ERROR: Unknown request type!")
                    

                    #Helper function to handle the worker thread and permit cancellation.
                    def call_webui():
                        try:
                            ji = JobInfo()
                            ji.images = []
                            ji.should_stop = threading.Event()
                            ji.job_status = ""

                            t = threading.Thread(target=call_webui_impl, args=(request,ji))
                            t.start()

                            while t.is_alive():
                                if("cancel" in request):
                                    ji.should_stop.set()
                                    t.join()
                                    msg = f"Request {processing_id} was cancelled."
                                    print(msg)
                                    request["cancel"] = True
                                    request["success"] = False
                                else:
                                    t.join(1)
                        except Exception as err:
                            print(f"Error in call_webui: {err}")
                        return request


                    
                    #Load the specified model. If none specified, use first option.
                    request["status"]["cur_task"] = "model_load"
                    set_request(request)
                    if isinstance(request["model"], str):
                        if loaded_model["name"] != request["model"]:
                            if request["model"] == "" and loaded_model != models[0]:
                                load_model(models[0])
                            else:
                                for m in models:
                                    if m["name"] == request["model"]:
                                        load_model(m)
                                        break
                    else:
                        #A mixed model was selected. This takes a list of weights for the models
                        #The weights should add up to 1.
                        mix = request["model"]
                        try:
                            if mix != previous_mix or loaded_model is not None and loaded_model["name"] != "mixed_model":
                                print("Loading new mixed model")
                                load_mixed_model(mix)
                        except:
                            msg = f'{{"error": "Invalid mix specified"}}'
                            print(msg)
                        previous_mix = mix
                            


                    #Determine whether to include logs of the process.
                    include_logs = False
                    if "include_logs" in request:
                        try:
                            include_logs = request["include_logs"] != False
                        except:
                            pass


                    #Call webui, forwarding the logs into the returned request if enabled.
                    request["status"]["cur_task"] = "model_eval"
                    set_request(request)
                    if include_logs:
                        out = io.StringIO()
                        err = io.StringIO()
                        with redirect_stdout(out):
                            with redirect_stderr(err):
                                call_webui()
                        request["log_out"] = out.getvalue()
                        request["log_err"] = err.getvalue()
                    else:
                        call_webui()

                #Return an error message if something went wrong.
                except Exception as err:
                    print(traceback.format_exc())
                    request["success"] = False
                    request["status"] = str(err)

                #Return the request to client (when they do a GET request)
                print("Setting request as done.")
                request["done"] = True
                set_request(request)

                #Move on to the next request
                processing_id = min(next_id, processing_id + 1)


        except Exception as err:
            #If there is an uncaught failure, do a soft restart.
            msg = f'{{"error": "Fatal error while processing requests:{err}.\nCancelling all pending requests."}}'
            print(msg)
            requests = {}
            processing_id = 1
            next_id = 1


#Start the server for the job queue.
def start_server():
    while True:
        manager = get_manager()
        server = manager.get_server()
        server.serve_forever()


#Start server and start processing queue.
if __name__ == '__main__':
    sys.path.insert(0, './scripts') 

    try:
        with open("models.json") as f:
            models = json.load(f)["models"]
    except:
        print("Couldn't load models. Using defaults.")
        models = default_models

    threading.Thread(target=start_server).start()
    process_queue()
