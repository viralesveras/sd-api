#!/usr/bin/env bash

conda activate lsd

#Don't let the job queue stick around after the script exits
function clean_up {

    # Perform program exit housekeeping
    echo "Killing job loop ${JOB_LOOP_PID}"
    kill $JOB_LOOP_PID
    echo "Killing job queue ${JOB_QUEUE_PID}"
    kill $JOB_QUEUE_PID
    exit
}

function run_job_queue {
    while true
    do
        trap clean_up SIGHUP SIGINT SIGTERM
        python rest_api_job_queue.py &
        export JOB_QUEUE_PID=$! 
        echo "JOB_QUEUE_PID: ${JOB_QUEUE_PID}"
        wait $JOB_QUEUE_PID
    done
    clean_up
}

#Start the manager
trap clean_up SIGHUP SIGINT SIGTERM
run_job_queue &
export JOB_LOOP_PID=$!
echo "JOB_LOOP_PID: ${JOB_LOOP_PID}"

#Set some default environment variables
API_ADMIN_KEY="admin"
API_URL="0.0.0.0"
API_PORT="5000"
JOBQUEUE_URL="127.0.0.1"
JOBQUEUE_PORT="37844"
JOBQUEUE_AUTH="this_is_insecure."

#Start the API server
echo "Using API URL: ${API_URL}, port: ${API_PORT}"
uwsgi --http "${API_URL}:${API_PORT}" --master -p 4 -w rest_api_server:api --enable-threads

#Make double sure the job queue is not still running.
clean_up
