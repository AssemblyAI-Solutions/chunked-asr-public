import requests
from pydub import AudioSegment
import webrtcvad
import io
import os
import transcribe
import redis
import metrics
import numpy as np
import shutil
import time

r = redis.Redis(host='localhost', port=6379, db=0)


def clear_redis_store(test_id):
    keys_pattern = f"transcript:{test_id}:*"
    for key in r.scan_iter(keys_pattern):
        r.delete(key)
    # Additionally, delete any other keys related to the test_id
    r.delete(f"total_count:{test_id}")
    r.delete(f"processed_count:{test_id}")

def wait_for_all_jobs_processed(test_id, total_jobs):
    while True:
        processed_jobs = 0
        for job_index in range(1, total_jobs + 1):
            if r.get(f'processed_jobs:{test_id}:{job_index}'):
                processed_jobs += 1
        if processed_jobs == total_jobs:
            print("All jobs have been processed.")
            break
        else:
            print(f"Waiting for all jobs to be processed... ({processed_jobs}/{total_jobs})")
            time.sleep(5)  # Check every 5 seconds

def process_assembly_transcripts(urls):
    test_id = 0

    # Constants
    pref_chunk_size = 30  # the chunk size you want in seconds
    target_chunk_duration_ms = pref_chunk_size * 1000  # converting chunk size to ms
    vad = webrtcvad.Vad()
    vad.set_mode(1)  # Increased to maximum aggressiveness
    output_dir_base = "./audio"

    for url_index, url in enumerate(urls, start=1):
        output_dir = os.path.join(output_dir_base, f"url_{url_index}")
        os.makedirs(output_dir, exist_ok=True)  # Ensure the audio directory exists
        print(f"Processing URL: {url}")
        process_audio_file(url, vad, target_chunk_duration_ms, output_dir, r, test_id)
    
        # Wait for all jobs to be processed
        while True:
            total_num_jobs = int(r.get('total_number_of_jobs').decode() or 0)
            keylist = r.keys('transcript:*')
            processed_jobs = len(keylist)
            print(f"Processed {processed_jobs} out of {total_num_jobs} jobs")
        
            if processed_jobs <= total_num_jobs:
                print("All jobs for this URL have been processed.")
                time.sleep(10)
                break
            else:
                print("Waiting for all jobs to be processed...")
                time.sleep(5)  # Check again in 5 seconds
        time.sleep(90)
        # Reset the counter for the next URL
        r.delete('total_number_of_jobs')

        # Delete the processed audio files
        shutil.rmtree(output_dir)
        print(f"Deleted audio files for URL: {url}")

def process_audio_file(url, vad, target_chunk_duration_ms, output_dir, r, test_id):
    response = requests.get(url)
    response.raise_for_status()  # Ensure the request was successful
    audio = AudioSegment.from_mp3(io.BytesIO(response.content))  # Load the entire audio file

    # Ensure audio is at a valid sample rate for VAD
    if audio.frame_rate not in [8000, 16000, 32000, 48000]:
        audio = audio.set_frame_rate(32000)

    segment_counter = 0
    monologue_buffer = AudioSegment.empty()
    transcript_ids = []

    # Define silence thresholds
    MAX_SILENCE_THRESHOLD_MS = 2000
    MIN_SILENCE_THRESHOLD_MS = 750
    accumulated_silence_ms = 0

    for i in range(0, len(audio), 10):  # Process the audio file in 10 ms chunks
        chunk = audio[i:i+10]
        if len(chunk) < 10:
            chunk += AudioSegment.silent(duration=10 - len(chunk), frame_rate=audio.frame_rate)
        raw_audio = np.array(chunk.get_array_of_samples())
        is_speech = vad.is_speech(raw_audio.tobytes(), audio.frame_rate)

        if is_speech:
            accumulated_silence_ms = 0
            monologue_buffer += chunk
        else:
            accumulated_silence_ms += 10
            if accumulated_silence_ms <= MAX_SILENCE_THRESHOLD_MS:
                monologue_buffer += chunk

        if len(monologue_buffer) >= target_chunk_duration_ms or (i + 10 >= len(audio) and len(monologue_buffer) > 0):
            # Export the chunk
            segment_counter += 1
            file_name = f"{output_dir}/monologue_{segment_counter}.wav"
            monologue_buffer.export(file_name, format="wav")
            print(f"Exported chunk {segment_counter} to {file_name}")

            # Reset buffer
            monologue_buffer = AudioSegment.empty()
            accumulated_silence_ms = 0

            # Process transcript
            upload_url = transcribe.upload_file(file_name)
            transcript = transcribe.create_transcript(upload_url, segment_counter, test_id, "assemblyai")
            transcript_ids.append(transcript.get('id'))
            dispatched_jobs_key = f'dispatched_jobs_count:{test_id}'
            r.incr(dispatched_jobs_key)
            dispatched_jobs = r.get(f'dispatched_jobs_count:{test_id}').decode()
            print("NUMBER OF DISPATCHED JOBS", dispatched_jobs)

    # Set last transcript id
    if transcript_ids:
        print('Setting last job ID in Redis:', transcript_ids[-1])
        r.set('test_id:' + str(test_id) + ':last_job', transcript_ids[-1])
        print("TOTAL JOBS:", len(transcript_ids))
        total_jobs_key = f'total_jobs:{test_id}'
        r.set(total_jobs_key, len(transcript_ids))  # Set the total number of jobs for this test_id
        r.set('total_number_of_jobs', len(transcript_ids))
        r.set(f'dispatching_completed:{test_id}', 'true')
        dispatched_jobs = r.get(f'dispatched_jobs_count:{test_id}').decode()
        print("NUMBER OF DISPATCHED JOBS", dispatched_jobs)
        test_id += 1
    time.sleep(90) #give it some time before we start processing the next file



# Example usage:
urls = [
    "your presigned url here..."
]

process_assembly_transcripts(urls)