import ngrok
import redis
from pyngrok import ngrok
from flask import Flask, request, jsonify
import logging
import time
import metrics

import os
from supabase import create_client, Client

def start_tunnel(port):
    http_tunnel = ngrok.connect(proto='http', addr=port)
    return http_tunnel.public_url

def close_tunnel(public_url):
    ngrok.disconnect(public_url)
    ngrok.kill()

ngrok_tunnel = start_tunnel(5000)

print('Public URL:', ngrok_tunnel)
r = redis.Redis(host='localhost', port=6379, db=0)
r.set('ngrok_url', ngrok_tunnel)

import transcribe
# create Flask app
app = Flask(__name__)

#function to write to postgres
#will take the data we provide to it and write to a new row in supabase table called chunking_asr
def write_to_postgres(final_transcript, diarized_text, json_responses, vendor_name, vendor_ids):
    url: str = "https://api.assemblyai-solutions.com"
    key: str = "SUPABASE KEY" #note - this requires a supabase table with the schema you see below in trycatch block
    supabase: Client = create_client(url, key)
    try:
        data, count = supabase.table('chunking_asr').insert({"vendor_name": vendor_name, "vendor_ids": vendor_ids, "transcript_text": final_transcript, "diarized_text": diarized_text, "json_responses": json_responses}).execute()
        return data
    except Exception as e:
        print("ERROR with DB write", e)

def check_completion_and_compile(test_id, job_id):
    print("JOB ID", job_id)
    # Increment the processed jobs counter
    r.incr(f'processed_jobs:{test_id}')
    
    total_jobs = int(r.get(f'total_jobs:{test_id}') or 0)
    processed_jobs = int(r.get(f'processed_jobs:{test_id}') or 0)
    print("TOTAL JOBS", total_jobs, "PROCESSED JOBS", processed_jobs)
    keys_pattern = f'transcript:{test_id}:*'
    keys = r.keys(keys_pattern)
    if total_jobs > 0 and len(keys) == total_jobs:
        # All jobs have been processed, compile and reorder transcripts
        print(f"All {total_jobs} jobs for test_id {test_id} have been processed. Compiling transcripts.")
        compile_and_order_transcripts(test_id)
    else:
        if total_jobs == 0:
            print(f"Waiting for more jobs. {processed_jobs} processed.")
        else:
            print(f"Waiting for more jobs. {processed_jobs}/{total_jobs} processed.")


def clear_redis_entries(test_id):
    # Clear Redis entries related to this test_id
    keys_pattern = f'transcript:{test_id}:*'
    for key in r.scan_iter(match=keys_pattern):
        r.delete(key)
    # Also clear the counters
    r.delete(f'total_jobs:{test_id}')
    processed_jobs_pattern = f'processed_jobs:{test_id}:*'
    # Use SCAN to find all keys matching the pattern
    for key in r.scan_iter(match=processed_jobs_pattern):
        # Delete each matching key
        r.delete(key)
    r.delete(f'processed_jobs:{test_id}')
    print("Cleared Redis entries for test_id:", test_id)

times_called = 0
@app.route('/', methods=['POST'])
def webhook_handler():
    global times_called 
    times_called += 1
    print("PROCESSING FILE NUMBER ", times_called)
    filecounter = request.args.get('filenumber', type=int)
    test_id = request.args.get('test_id')
    
    if filecounter is None or test_id is None:
        return jsonify({'message': 'Missing required parameters'}), 400
    
    try:
        job_id = request.json.get('transcript_id')
        payload = transcribe.get_transcript(job_id).get('text')
        r.hset(f"transcript:{test_id}:{job_id}", mapping={"text": payload, "filecounter": filecounter})
        # Check if all jobs are complete and compile if so
        check_completion_and_compile(test_id, job_id)
        
        return jsonify({'message': 'Webhook received'}), 200
    except Exception as e:
        print(f"Error processing job: {e}")
        #decrement the processed job counter and remove t id if we're going to retry
        r.decr(f'processed_jobs:{test_id}')
        r.delete(f"transcript:{test_id}:{job_id}")
        return jsonify({'message': 'Error processing job'}), 400

def compile_and_order_transcripts(test_id):
    keys_pattern = f'transcript:{test_id}:*'
    keys = r.keys(keys_pattern)
    transcripts = []
    transcript_ids = []
    transcript_jsons = []
    transcript_utterances = []
    for key in keys:

        _, test_id_str, job_id_str = key.decode("utf-8").split(":")
        transcript_ids.append(job_id_str) # Append job_id_str, not test_id_str
    
        # Get the transcript JSON response using the extracted ID
        transcript = transcribe.get_transcript(job_id_str)
        transcript_jsons.append(transcript)
    
        # Assuming the 'utterances' key exists in the transcript and it's a list
        utterances = transcript['utterances']
        transcript_utterances.extend(utterances)
        transcript_data = r.hgetall(key)
        # Ensure you convert bytes from Redis to strings if necessary
        transcript_text = transcript_data[b'text'].decode('utf-8')
        filecounter = int(transcript_data[b'filecounter'].decode('utf-8'))
        transcripts.append((filecounter, transcript_text))
    
    # Sort transcripts by filecounter
    transcripts.sort(key=lambda x: x[0])
    final_transcript = ' '.join([text for _, text in transcripts])
    print(final_transcript)

    # Write final_transcript to PostgreSQL database
    print("WRITING DATA...")
    db_resp = write_to_postgres(final_transcript, transcript_utterances, transcript_jsons, "assemblyai", transcript_ids)
    clear_redis_entries(test_id)

if __name__ == "__main__":
    # start the Flask app
    app.run(port=5000)