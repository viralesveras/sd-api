# sd-api
A simple API providing a job queue for a local sd-webui instance

# Demonstration video:

https://user-images.githubusercontent.com/113930878/191446097-3a4ab3a3-6a65-4c05-a245-da149e75e30a.mp4

# FAQ

## Why make this API?
 - I needed a simple API tailored to be useful for my Photoshop plugin.


## How does it work?
 - It uses uwsgi to run a small pseudo-REST API written with Flask to connect to a job manager that runs a sd-webui instance.

## Why not just use the excellent existing Photoshop plugin by Christian Cantrell?
 - His plugin is indeed excellent, and can be found here: https://christiancantrell.com/#ai-ml .  In fact, it's so excellent that I strongly urge you to use it, because currently my version is absolutely no competitor to his at all: his is much more mature and useful, and he has a documented way to let users install it. However, as of this writing, his plugin does not yet permit connecting to a self-hosted instance, and it is not open source.


## Why release this in such an unfinished state?
 - This is such a proof-of-concept version that I almost didn't release it, but I don't want to fall into the trap of waiting until it's "perfect," so I'm making it public now. It does technically work, but installation is a nightmare and the API is not yet stable because I'm still experimenting with it. I can only work on it on weekends, so please don't expect rapid progress.

## Where is the photoshop plugin?
 - It's here: https://github.com/viralesveras/sd-ps-plugin

# Prerequisites
 - A machine running Ubuntu 20.04 or similar
 - A powerful NVIDIA GPU, like a 3090 or A6000 or better.

# Installation
Honestly, at the moment you're pretty much on your own (sorry, when I said proof-of-concept I meant it).

I *think* if you have a working conda "lsd" env from sd-webui, then the following should work.

 1. git clone --recursive git@github.com:viralesveras/sd-api.git
 1. cd sd-api
 1. *place your pre-downloaded sd-1.4 ckpt in models/ldm/stable-diffusion-v1/model.ckpt*
 1. pip3 install pyuwsgi flask
 1. ./start_rest_api.sh

If everything went well, then it should now be running. I don't think everything will go well, but you can try accessing it at http://127.0.0.1:5000/info

If it's running, you should see a small JSON output showing the server's version and supported models and samplers.

If it's not running, Python probably gave you a traceback that might have useful information.

## API Documentation
 - Coming soon(tm)

